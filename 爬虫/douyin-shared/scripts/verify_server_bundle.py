#!/usr/bin/env python3
"""Verify release contents and run credential-free commands after extraction."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

from build_server_bundle import ROOT, FILES, build


def verify():
    target = ROOT / 'dist/douyin-server-0.2.0.tar.gz'
    checks = {}
    expected = {'douyin/' + n for n in FILES} | {'douyin/MANIFEST.sha256'}
    with tarfile.open(target, 'r:gz') as archive:
        members = archive.getmembers()
        assert {m.name for m in members} == expected
        assert all(m.isfile() and not m.issym() and '..' not in PurePosixPath(m.name).parts for m in members)
        manifest = archive.extractfile('douyin/MANIFEST.sha256').read().decode('utf-8')
        for line in manifest.splitlines():
            digest, name = line.split('  ', 1)
            assert hashlib.sha256(archive.extractfile('douyin/' + name).read()).hexdigest() == digest
        checks['archive_files_and_embedded_hashes'] = len(members)
        for m in members:
            if m.name.endswith('.sh'):
                assert m.mode == 0o755
                assert b'\r\n' not in archive.extractfile(m).read()
        cache = ROOT / '.cache/handoff-verification'
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            # Every member was validated as a regular file beneath a fixed prefix.
            for m in members:
                dest = Path(directory) / m.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.extractfile(m).read())
            project = Path(directory) / 'douyin'
            for args in (['--help'], ['download', '-i', 'examples/urls.txt', '--dry-run']):
                result = subprocess.run([sys.executable, str(project / 'run.py'), *args],
                                        cwd=directory, capture_output=True, text=True, encoding='utf-8')
                assert result.returncode == 0, result.stderr
            checks['extracted_help_and_cwd_independent_dry_run'] = True
    # A private file added to server/ must not silently enter a release.
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        project = Path(directory)
        for name in FILES:
            dest = project / 'server' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / 'server' / name).read_bytes())
        for name in ('auth/cookie.txt', 'downloads/test.mp4', '.cache/private.txt', 'tests/private.txt'):
            dest = project / 'server' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b'PRIVATE_CANARY_DO_NOT_PACKAGE')
        artifact = build(project / 'dist', project=project)
        with tarfile.open(artifact, 'r:gz') as archive:
            assert {m.name for m in archive.getmembers()} == expected
            assert all(b'PRIVATE_CANARY_DO_NOT_PACKAGE' not in archive.extractfile(m).read() for m in archive.getmembers())
        checks['credential_media_cache_canaries_excluded'] = True
        # Reproducible output: private extras do not change the archive.
        assert artifact.read_bytes() == target.read_bytes()
        checks['reproducible_archive'] = True
    checks['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    (ROOT / 'dist/offline-verification.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    verify()
