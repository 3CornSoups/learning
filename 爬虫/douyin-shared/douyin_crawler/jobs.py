"""Credential-free media jobs shared by the local collector and remote worker."""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from .media_hosts import allowed_media_url


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def make_job(video, normalized, source):
    media = normalized["video"]
    address = media["playAddr"][0]
    url = address["src"] if isinstance(address, dict) else address
    return {"id": video.id, "source": source, "metadata": video.summary(),
            "work": {"awemeId": video.id, "desc": video.description,
                     "video": {"playAddr": [{"src": url}],
                               "playAddrSize": media.get("playAddrSize") or media.get("dataSize"),
                               "playAddrFileHash": media.get("playAddrFileHash"),
                               "duration": video.duration_ms}}}


def validate_manifest(manifest):
    if set(manifest) != {"schema_version", "batch_id", "created_utc", "tasks"} or manifest["schema_version"] != 1:
        raise ValueError("Unsupported media manifest schema")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", manifest["batch_id"]):
        raise ValueError("Invalid batch ID")
    tasks = manifest["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Manifest has no tasks")
    seen = set()
    for job in tasks:
        if set(job) != {"id", "source", "metadata", "work"}:
            raise ValueError("Unexpected job fields; authentication data is not accepted")
        work_id = job["id"]
        if not isinstance(work_id, str) or not re.fullmatch(r"\d{10,25}", work_id) or work_id in seen:
            raise ValueError("Invalid or duplicate work ID")
        seen.add(work_id)
        if set(job["metadata"]) != {"id", "title", "author_id", "hashtags", "duration_ms", "size_bytes"}:
            raise ValueError("Unexpected metadata fields")
        work = job["work"]
        if set(work) != {"awemeId", "desc", "video"} or work["awemeId"] != work_id or job["metadata"]["id"] != work_id:
            raise ValueError("Invalid normalized work")
        media = work["video"]
        if set(media) != {"playAddr", "playAddrSize", "playAddrFileHash", "duration"}:
            raise ValueError("Unexpected media fields")
        size = media["playAddrSize"]
        if type(size) is not int or size <= 0:
            raise ValueError("A positive expected media size is required")
        file_hash = media["playAddrFileHash"]
        if file_hash is not None and not re.fullmatch(r"[a-fA-F0-9]{32}", file_hash):
            raise ValueError("Invalid expected MD5")
        addresses = media["playAddr"]
        if not isinstance(addresses, list) or len(addresses) != 1 or set(addresses[0]) != {"src"}:
            raise ValueError("Exactly one resolved playback address is required")
        url = urlsplit(addresses[0]["src"])
        host = url.hostname or ""
        if not allowed_media_url(addresses[0]["src"]):
            raise ValueError("Unexpected resolved playback host")
    return manifest


class ManifestWriter:
    def __init__(self, path, batch_id):
        self.path = Path(path)
        if self.path.exists():
            raise FileExistsError("Manifest already exists; choose a new export path")
        self.data = {"schema_version": 1, "batch_id": batch_id,
                     "created_utc": datetime.now(timezone.utc).isoformat(), "tasks": []}

    def add(self, video, normalized, source):
        job = make_job(video, normalized, source)
        proposed = {**self.data, "tasks": [*self.data["tasks"], job]}
        validate_manifest(proposed)
        atomic_json(self.path, proposed)
        self.data = proposed


def load_manifest(path):
    return validate_manifest(json.loads(Path(path).read_text(encoding="utf-8-sig")))
