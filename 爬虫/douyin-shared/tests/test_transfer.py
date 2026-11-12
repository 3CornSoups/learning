import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest.mock import patch

import httpx

from douyin_crawler.jobs import ManifestWriter, load_manifest, validate_manifest
from douyin_crawler.models import Video
from server_worker import run

ROOT = Path(__file__).resolve().parent.parent
TEMP = ROOT / ".cache" / "transfer-tests"
TEMP.mkdir(parents=True, exist_ok=True)


def box(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def media_fixture():
    tracks = b""
    for kind in (b"vide", b"soun"):
        header = box(b"mdhd", struct.pack(">IIIII", 0, 0, 0, 1000, 1000) + b"\0" * 4)
        handler = box(b"hdlr", b"\0" * 8 + kind + b"\0" * 12)
        tracks += box(b"trak", box(b"mdia", header + handler))
    return box(b"ftyp", b"isom\0\0\0\0") + box(b"moov", tracks) + box(b"mdat", b"media" * 50)


def create_manifest(path, body):
    work_id = "1234567890123456789"
    video = Video(work_id, "test", "test", "MS4wTest", frozenset(), 1000, len(body), {})
    normalized = {"awemeId": work_id, "Cookie": "SECRET_SESSION_VALUE",
                  "video": {"playAddr": [{"src": "https://v26-web.douyinvod.com/test.mp4?signature=temporary"}],
                            "playAddrSize": len(body), "playAddrFileHash": hashlib.md5(body).hexdigest()}}
    writer = ManifestWriter(path, "test_batch")
    writer.add(video, normalized, "feed")
    return work_id


class TransferTests(unittest.TestCase):
    def test_export_whitelists_fields_and_rejects_credentials(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as name:
            path = Path(name) / "jobs.json"
            create_manifest(path, media_fixture())
            self.assertNotIn("SECRET_SESSION_VALUE", path.read_text(encoding="utf-8"))
            manifest = load_manifest(path)
            manifest["tasks"][0]["headers"] = {"Cookie": "secret"}
            with self.assertRaises(ValueError):
                validate_manifest(manifest)
            with self.assertRaises(FileExistsError):
                ManifestWriter(path, "new_batch")

    def test_worker_download_verify_replay_and_no_overwrite_on_corruption(self):
        body = media_fixture()
        requests = []

        def handle(request):
            requests.append(request)
            self.assertNotIn("cookie", request.headers)
            start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers["range"]).groups())
            return httpx.Response(206, content=body[start:end + 1], headers={
                "Content-Range": f"bytes {start}-{end}/{len(body)}", "Content-Type": "video/mp4"})

        client_type = httpx.Client
        transport = httpx.MockTransport(handle)
        with tempfile.TemporaryDirectory(dir=TEMP) as name:
            root = Path(name)
            work_id = create_manifest(root / "jobs.json", body)
            with patch("httpx.Client", side_effect=lambda **kwargs: client_type(transport=transport, **kwargs)):
                self.assertEqual(run(root / "jobs.json", root / "downloads", root / "probe.json", probe_only=True), 0)
                self.assertEqual(run(root / "jobs.json", root / "downloads", root / "first.json"), 0)
                self.assertEqual((root / "downloads" / f"{work_id}.mp4").read_bytes(), body)
                requests.clear()
                self.assertEqual(run(root / "jobs.json", root / "downloads", root / "repeat.json"), 0)
                self.assertEqual(requests, [])
                repeated = json.loads((root / "repeat.json").read_text(encoding="utf-8"))
                self.assertEqual(repeated["tasks"][0]["state"], "skipped_verified")
                file = root / "downloads" / f"{work_id}.mp4"
                file.write_bytes(body + b"corrupt")
                self.assertEqual(run(root / "jobs.json", root / "downloads", root / "bad.json"), 1)
                self.assertEqual(file.read_bytes(), body + b"corrupt")

    def test_forbidden_media_requires_local_refresh_not_retry_or_login(self):
        client_type = httpx.Client
        with tempfile.TemporaryDirectory(dir=TEMP) as name:
            root = Path(name)
            create_manifest(root / "jobs.json", media_fixture())
            transport = httpx.MockTransport(lambda request: httpx.Response(403))
            with patch("httpx.Client", side_effect=lambda **kwargs: client_type(transport=transport, **kwargs)):
                self.assertEqual(run(root / "jobs.json", root / "downloads", root / "report.json", probe_only=True), 3)
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["completed"])
            self.assertEqual(report["tasks"][0]["state"], "refresh_required")


if __name__ == "__main__":
    unittest.main()
