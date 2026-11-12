"""Download exported media jobs; no browser, login, Cookie or GPU is needed."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

import httpx

from download_from_page import download, MediaHTTPError
from verify_media import inspect, inspect_tracks
from douyin_crawler.jobs import atomic_json, load_manifest


class RefreshRequired(RuntimeError):
    pass


def probe(job, client):
    media = job["work"]["video"]
    end = min(65535, media["playAddrSize"] - 1)
    with client.stream("GET", media["playAddr"][0]["src"], headers={
            "Range": f"bytes=0-{end}", "Referer": "https://www.douyin.com/",
            "User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}) as response:
        if response.status_code in (401, 403, 410):
            raise RefreshRequired(f"Media HTTP {response.status_code}; local address refresh or network diagnosis required")
        if response.status_code != 206:
            raise RuntimeError(f"Media probe HTTP {response.status_code}")
        if response.headers.get("content-range") != f"bytes 0-{end}/{media['playAddrSize']}":
            raise ValueError("Media probe Content-Range differs from the task")
        body = b"".join(response.iter_bytes())
        if len(body) != end + 1 or body[4:8] != b"ftyp":
            raise ValueError("Media probe is not the expected MP4 prefix")
    return {"probe_bytes": len(body), "expected_bytes": media["playAddrSize"]}


def verify_file(path, job, verify_frames):
    expected = job["work"]["video"]
    if path.stat().st_size != expected["playAddrSize"]:
        raise ValueError("Existing file has an unexpected size")
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    wanted = expected["playAddrFileHash"]
    if wanted and checksum != wanted:
        raise ValueError("File MD5 differs from the media task")
    tracks = inspect_tracks(path)
    validation = inspect(path) if verify_frames else {"tracks": tracks}
    if verify_frames:
        atomic_json(path.with_suffix(".validation.json"), validation)
    return {"file": str(path.resolve()), "bytes": path.stat().st_size, "md5": checksum,
            "hash_verified": bool(wanted), "validation": validation}


def run(manifest_path, output_dir, report_path, probe_only=False, verify_frames=False):
    manifest = load_manifest(manifest_path)
    output_dir, report_path = Path(output_dir), Path(report_path)
    report = {"batch_id": manifest["batch_id"], "pid": os.getpid(), "ppid": os.getppid(),
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "operation": "probe" if probe_only else "download", "completed": False,
              "tasks": [{"id": job["id"], "state": "pending"} for job in manifest["tasks"]]}
    result_code = 1
    try:
        atomic_json(report_path, report)
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, connect=15)) as client:
            for job, status in zip(manifest["tasks"], report["tasks"]):
                try:
                    if probe_only:
                        status.update(probe(job, client), state="probe_passed")
                    else:
                        path = output_dir / f"{job['id']}.mp4"
                        existed = path.exists()
                        if not existed:
                            probe(job, client)
                            path = download(job["work"], output_dir, f"remote_{job['source']}")
                        status.update(verify_file(path, job, verify_frames), state="skipped_verified" if existed else "downloaded")
                        if not existed:
                            metadata_path = path.with_suffix(".json")
                            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                            metadata.update(job["metadata"], batch_id=manifest["batch_id"], tracks_verified=True)
                            atomic_json(metadata_path, metadata)
                    print(f"{job['id']}: {status['state']}", flush=True)
                    atomic_json(report_path, report)
                except Exception as exc:
                    refresh = isinstance(exc, RefreshRequired) or (isinstance(exc, MediaHTTPError) and exc.status in (401, 403, 410))
                    status["state"] = "refresh_required" if refresh else "failed"
                    status["error"] = type(exc).__name__
                    if isinstance(exc, (ValueError, RefreshRequired)):
                        status["message"] = str(exc)
                    print(f"{job['id']}: {status['state']} ({type(exc).__name__})", flush=True)
                    result_code = 3 if refresh else 1
                    break
            else:
                report["completed"] = True
                result_code = 0
    finally:
        report["ended_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(report_path, report)
    return result_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--verify-frames", action="store_true")
    args = parser.parse_args()
    try:
        return run(args.manifest, args.output_dir, args.report, args.probe, args.verify_frames)
    except Exception as exc:
        # Never log signed URLs from HTTP client exceptions.
        print(f"Worker stopped: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
