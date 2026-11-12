"""Offline regression checks. Never access Douyin or a real Cookie."""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from douyin_server.backend import response_evidence
from douyin_server.cli import main
from douyin_server.support import ROOT, input_ids, read_cookie, video_id, inspect_file, OutputLock
from douyin_server.workflow import collect

ID = '7704637489155305930'
OTHER = '7704257974576012442'
MEDIA = b'\x00\x00\x00\x18ftypisom' + bytes(range(200))


class InputTests(unittest.TestCase):
    def test_urls_and_reject_foreign_domains(self):
        self.assertEqual(video_id('https://www.douyin.com/jingxuan?modal_id=' + ID), ID)
        for bad in ('https://evil.example/video/' + ID, 'https://v.douyin.com/x/', '1',
                    'https://www.douyin.com.evil.example/video/' + ID):
            with self.assertRaises(ValueError):
                video_id(bad)

    def test_comments_duplicates_and_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'urls'
            p.write_text('\ufeff# comment\n' + ID + '\nhttps://www.douyin.com/video/' + ID + '\n' + OTHER, encoding='utf-8')
            self.assertEqual(input_ids(p), [ID, OTHER])
            p.write_text(ID + '\ninvalid', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '2'):
                input_ids(p)

    def test_cookie_format_without_echoing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'cookie'
            p.write_text('Cookie: UIFID=secret; b=2; c=3; d=4; e=a=b\n', encoding='utf-8')
            _, values = read_cookie(p)
            self.assertEqual(values['e'], 'a=b')
            for bad in ('UIFID=secret', 'UIFID=secret\nb=2;c=3;d=4;e=5', 'not a cookie secret'):
                p.write_text(bad, encoding='utf-8')
                with self.assertRaises(ValueError) as found:
                    read_cookie(p)
                self.assertNotIn('secret', str(found.exception))

    def test_source_hash_and_html_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'test.mp4'
            p.write_bytes(MEDIA)
            result = inspect_file(p, [{'md5': hashlib.md5(MEDIA).hexdigest(), 'size': len(MEDIA)}])
            self.assertTrue(result['source_hash_verified'])
            with self.assertRaises(ValueError):
                inspect_file(p, expected_md5='0' * 32)
            p.write_bytes(b'<html>challenge</html>')
            with self.assertRaises(ValueError):
                inspect_file(p)

    def test_response_evidence_accepts_invalid_json_and_redacts_body(self):
        for body in (b'[]', b'null', b'<html>Cookie=secret</html>', b'{"aweme_detail":[]}'):
            result = response_evidence(body, 200)
            self.assertFalse(result['has_detail'])
            self.assertNotIn('secret', json.dumps(result))

    def test_dry_run_needs_no_f2_or_cookie(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as console:
            p = Path(tmp) / 'urls'
            p.write_text(ID, encoding='utf-8')
            with patch('douyin_server.cli.dependencies', side_effect=AssertionError('must not import/check F2')):
                self.assertEqual(main(['download', '-i', str(p), '--dry-run']), 0)
            self.assertEqual(json.loads(console.getvalue())['count'], 1)

    def test_lock_blocks_another_process_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = 'from douyin_server.support import OutputLock; import sys;\nwith OutputLock(sys.argv[1]): pass'
            with OutputLock(tmp):
                result = subprocess.run([sys.executable, '-c', code, tmp], cwd=ROOT, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
            result = subprocess.run([sys.executable, '-c', code, tmp], cwd=ROOT, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_failure_redacts_raw_backend_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'videos'
            async def operation(work_id):
                if work_id == OTHER:
                    raise ValueError('Cookie=secret&signed_url=private')
                (output / (work_id + '_test.mp4')).write_bytes(MEDIA)
                return True
            report = await collect([ID, OTHER], output, Path(tmp) / 'report.json', 2, operation, {})
            self.assertEqual((report['downloaded'], report['failed']), (1, 1))
            self.assertNotIn('secret', json.dumps(report))
            self.assertEqual(report['pending_ids'], [])

    async def test_changed_existing_file_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            p = output / (ID + '_test.mp4')
            async def operation(_):
                p.write_bytes(MEDIA)
                return True
            report = await collect([ID], output, output / 'report.json', 1, operation, {})
            self.assertEqual(report['downloaded'], 1)
            p.write_bytes(MEDIA + b'changed')
            async def skip(_):
                return True
            report = await collect([ID], output, output / 'retry.json', 1, skip, {})
            self.assertEqual(report['failed'], 1)

    async def test_cancellation_writes_interrupted_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / 'report.json'
            async def wait(_):
                await asyncio.sleep(10)
            task = asyncio.create_task(collect([ID, OTHER], Path(tmp) / 'videos', report_path, 1, wait, {}))
            await asyncio.sleep(.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            report = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertEqual(report['state'], 'interrupted')
            self.assertIn(OTHER, report['pending_ids'])

    async def test_cli_partial_failure_has_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            p = Path(tmp) / 'urls'
            p.write_text(ID, encoding='utf-8')
            async def failure(*args):
                return {'state': 'complete', 'downloaded': 0, 'skipped': 0, 'failed': 1, 'pending_ids': [],
                        'elapsed_seconds': 1, 'new_bytes': 0, 'batch_MBps': 0}
            with patch('douyin_server.cli.dependencies', return_value={'ok': True}), \
                 patch('douyin_server.cli.read_cookie', return_value=('fake', {})), \
                 patch('douyin_server.cli.output_path', side_effect=lambda s: ROOT / s if not Path(s).is_absolute() else Path(s)), \
                 patch('douyin_server.workflow.execute', side_effect=failure):
                self.assertEqual(main(['download', '-i', str(p), '-o', str(Path(tmp) / 'out')]), 1)


if __name__ == '__main__':
    unittest.main()
