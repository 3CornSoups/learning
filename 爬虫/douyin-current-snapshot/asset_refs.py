"""Registered immutable file references. No third-party imports or implicit copies."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import uuid


def digest(path, algorithm="sha256"):
    value = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def record_path(path):
    return Path(str(path) + ".asset.json")


def link_asset(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if not source.is_file():
        raise ValueError("Asset target must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        record = verify_link(destination)
        if Path(record["target"]) != source:
            raise ValueError("Existing asset link points to another target")
        return record
    st = source.stat()
    record = {"logical_path": str(destination), "target": str(source), "bytes": st.st_size,
              "sha256": digest(source), "device": st.st_dev, "inode": st.st_ino}
    destination.symlink_to(source)
    try:
        atomic(record_path(destination), record)
    except BaseException:
        destination.unlink()
        raise
    return record


def verify_link(path):
    path = Path(path).absolute()
    if not path.is_symlink():
        raise ValueError("Expected a registered symbolic asset link")
    record = json.loads(record_path(path).read_text(encoding="utf-8"))
    target = path.resolve(strict=True)
    st = target.stat()
    if (record["logical_path"] != str(path) or record["target"] != str(target)
            or record["bytes"] != st.st_size or record["device"] != st.st_dev
            or record["inode"] != st.st_ino or record["sha256"] != digest(target)):
        raise ValueError("Asset target identity or contents changed")
    return record


@contextmanager
def store_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".asset-store.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b" "); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def video_store():
    value = os.environ.get("CZK_VIDEO_STORE")
    return Path(value).resolve() if value else None


def lookup_video(work_id, md5=None, size=None):
    root = video_store()
    # A current source checksum is necessary to reuse across different batches.
    if root is None or not md5:
        return None
    with store_lock(root):
        index = root / "index.json"
        data = json.loads(index.read_text("utf-8")) if index.exists() else {}
        for row in data.get(str(work_id), []):
            path = Path(row["target"])
            if row.get("md5") != md5 or (size and row["bytes"] != size):
                continue
            if not path.is_file() or path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
                raise ValueError("Registered media was changed or removed")
            return path
    return None


def publish_video(path, work_id, md5=None):
    """Move newly downloaded bytes once; existing links are verified in place."""
    root = video_store()
    path = Path(path).absolute()
    if root is None:
        return path
    if not re.fullmatch(r'[0-9]{1,25}', str(work_id)):
        raise ValueError('Asset work ID must contain only digits')
    if path.is_symlink():
        verify_link(path)
        return path
    sha = digest(path)
    md5 = md5 or digest(path, "md5")
    with store_lock(root):
        target = root / str(work_id) / (sha + path.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if digest(target) != sha:
                raise ValueError("Asset-store collision or corrupt target")
            # This is a verified duplicate produced by this download operation.
            path.unlink()
        else:
            if path.stat().st_dev != target.parent.stat().st_dev:
                raise ValueError("Asset store must share a filesystem; refusing an implicit copy")
            path.rename(target)
        index = root / "index.json"
        data = json.loads(index.read_text("utf-8")) if index.exists() else {}
        rows = data.setdefault(str(work_id), [])
        row = {"target": str(target), "bytes": target.stat().st_size, "sha256": sha, "md5": md5}
        if row not in rows:
            rows.append(row)
        atomic(index, data)
        link_asset(target, path)
    return path
