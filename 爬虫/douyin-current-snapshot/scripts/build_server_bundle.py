#!/usr/bin/env python3
"""Build a credential-free, allowlisted server tarball. No network calls."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    '.gitignore', 'README.md', 'run.py', 'run.sh', 'pyproject.toml', 'uv.lock',
    'auth/README.md', 'examples/urls.txt',
    'docs/cookie.md', 'docs/operations.md', 'docs/maintenance.md', 'docs/performance.md', 'docs/asset-reuse.md',
    'douyin_server/__init__.py', 'douyin_server/cli.py', 'douyin_server/support.py',
    'douyin_server/backend.py', 'douyin_server/workflow.py', 'douyin_server/range_downloader.py', 'douyin_server/asset_refs.py',
    'scripts/setup.sh', 'scripts/jobs_to_urls.py',
    'vendor/download_douyin.py', 'vendor/download_by_urls.py', 'vendor/SOURCE.json',
    'vendor/pyproject.toml', 'vendor/uv.lock',
    'tests/test_server.py', 'tests/test_range_downloader.py', 'tests/test_assets.py',
)


def build(destination=None, project=ROOT):
    source = project / 'server'
    output = Path(destination) if destination else project / 'dist'
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in sorted(FILES):
        item = source / name
        if item.is_symlink() or not item.is_file():
            raise ValueError('Missing or symbolic release file: ' + name)
        files[name] = item.read_bytes()
    records = {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}
    manifest = ''.join(f'{digest}  {name}\n' for name, digest in records.items()).encode('utf-8')
    files['MANIFEST.sha256'] = manifest
    target = output / 'douyin-server-0.2.0.tar.gz'
    temporary = target.with_suffix('.tmp')
    try:
        with temporary.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as archive:
                for name, body in sorted(files.items()):
                    info = tarfile.TarInfo('douyin/' + name)
                    info.size = len(body)
                    info.mode = 0o755 if name.endswith('.sh') else 0o644
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(body))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + '.sha256').write_text(f'{digest}  {target.name}\n', encoding='ascii')
    target.with_name(target.name + '.manifest.json').write_text(
        json.dumps({'archive': target.name, 'sha256': digest, 'files': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


if __name__ == '__main__':
    print(build())
