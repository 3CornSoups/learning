"""Protocol-level integrity tests, with no Douyin traffic or credentials."""
import asyncio
import hashlib
from pathlib import Path
import re
import tempfile
import unittest

import httpx
from douyin_server.range_downloader import download, RangeUnavailable


class IntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,behavior,*,bad_hash=False):
        payload=bytes(range(251))*4200
        requested=[];active=0
        async def serve(request):
            nonlocal active
            header=request.headers.get('Range')
            requested.append(header)
            if behavior=='ignore':
                return httpx.Response(200,headers={'Content-Length':str(len(payload))},content=payload)
            a,b=map(int,re.fullmatch(r'bytes=(\d+)-(\d+)',header).groups())
            body=payload[a:b+1]
            wrong=behavior=='wrong-range' and b>0
            if behavior=='truncated' and b>0:
                body=body[:-1]
            if behavior=='corrupt' and b>0:
                body=bytes([body[0]^1])+body[1:]
            if behavior=='cancel' and b>0:
                active+=1
                try:
                    await asyncio.sleep(10)
                finally:
                    active-=1
            return httpx.Response(206,headers={'Content-Range':f'bytes {a+int(wrong)}-{b}/{len(payload)}',
                    'Content-Length':str(len(body))},content=body)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path=Path(directory)/'video.mp4'
            async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
                call=download(client,'https://test.invalid/media',path,expected_size=len(payload),
                              expected_md5='0'*32 if bad_hash else hashlib.md5(payload).hexdigest(),segments=4,retries=0)
                if behavior=='cancel':
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(call,.05)
                    self.assertEqual(active,0)
                elif behavior in ('wrong-range','truncated','corrupt') or bad_hash:
                    with self.assertRaises(RangeUnavailable):
                        await call
                else:
                    self.assertTrue(await call)
                    self.assertEqual(path.read_bytes(),payload)
                    if behavior=='ok':
                        self.assertEqual(len(requested),5)
                self.assertEqual(list(Path(directory).glob('*.parts-*')),[])
                if behavior not in ('ok','ignore') or bad_hash:
                    self.assertFalse(path.exists())

    async def test_ranges(self):await self.exercise('ok')
    async def test_ignored_range(self):await self.exercise('ignore')
    async def test_wrong_content_range(self):await self.exercise('wrong-range')
    async def test_truncation(self):await self.exercise('truncated')
    async def test_corruption(self):await self.exercise('corrupt')
    async def test_expected_digest(self):await self.exercise('ok',bad_hash=True)
    async def test_cancellation(self):await self.exercise('cancel')


if __name__=='__main__':unittest.main()
