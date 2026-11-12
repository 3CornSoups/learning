import os
from pathlib import Path
import tempfile
import unittest
from douyin_server.asset_refs import link_asset, verify_link
from douyin_server.support import inspect_file, ValidationError


class AssetTests(unittest.TestCase):
    def test_registered_media_and_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4';source.write_bytes(b'\0\0\0\x18ftypisom'+b'0'*30)
            link=root/'batch.mp4'
            try:link_asset(source,link)
            except OSError as exc:
                if os.name=='nt' and getattr(exc,'winerror',None)==1314:self.skipTest('symlink permission')
                raise
            self.assertEqual(inspect_file(link)['bytes'],42)
            source.write_bytes(b'\0\0\0\x18ftypisom'+b'1'*30)
            with self.assertRaises(ValidationError):inspect_file(link)

    def test_unregistered_link_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';source.write_bytes(b'\0\0\0\x18ftypisom')
            link=Path(folder)/'link'
            try:link.symlink_to(source)
            except OSError as exc:
                if os.name=='nt' and getattr(exc,'winerror',None)==1314:self.skipTest('symlink permission')
                raise
            with self.assertRaises(ValidationError):inspect_file(link)
