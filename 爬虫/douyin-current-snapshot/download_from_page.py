"""Download a specified Douyin video from a locally saved page response.

No login credentials are required. Signed playback URLs remain local and may expire.
"""
import argparse
import hashlib
import json
import re
import sys
import shutil
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from asset_refs import lookup_video, link_asset, publish_video
from douyin_crawler.media_hosts import allowed_media_url


class MediaHTTPError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Media HTTP {status}; partial data retained")


def fetch_ranges(client, url, headers, partial, expected, workers=8):
    """Resume a prefix, fetch disjoint byte ranges, then assemble in order."""
    prefix = partial.stat().st_size if partial.exists() else 0
    if prefix > expected:
        raise ValueError("Partial file exceeds expected size.")
    if prefix:
        with partial.open("rb") as stream:
            if stream.read(12)[4:8] != b"ftyp":
                raise ValueError("Existing partial file is not MP4.")
    remaining = expected - prefix
    if not remaining:
        return
    span = (remaining + workers - 1) // workers
    ranges = []
    for index, start in enumerate(range(prefix, expected, span)):
        end = min(expected - 1, start + span - 1)
        segment = partial.with_name(f"{partial.name}.range-{start}-{end}")
        if segment.is_symlink():
            raise ValueError("Refusing to write a download segment through a symbolic link")
        ranges.append((start, end, segment))

    def fetch(spec):
        start, end, segment = spec
        size = segment.stat().st_size if segment.exists() else 0
        if size > end - start + 1:
            raise ValueError("Range file exceeds expected length.")
        if size == end - start + 1:
            return
        request_start = start + size
        with client.stream("GET", url, headers={**headers, "Range": f"bytes={request_start}-{end}"}) as response:
            if response.status_code != 206:
                raise MediaHTTPError(response.status_code)
            if response.headers.get("content-range") != f"bytes {request_start}-{end}/{expected}":
                raise ValueError("Unexpected Content-Range; refusing to assemble data.")
            with segment.open("ab") as stream:
                for chunk in response.iter_bytes(64 * 1024):
                    stream.write(chunk)
        if segment.stat().st_size != end - start + 1:
            raise ValueError("Incomplete range; partial data retained.")

    print(f"Resuming {prefix / 1_000_000:.1f} MB; {len(ranges)} parallel ranges", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch, spec) for spec in ranges]
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=5)
            for future in done:
                future.result()
            size = prefix + sum(path.stat().st_size if path.exists() else 0 for _, _, path in ranges)
            print(f"Downloaded {size / 1_000_000:.1f} MB / {expected / 1_000_000:.1f} MB", flush=True)
    with partial.open("ab") as destination:
        for _, _, path in ranges:
            with path.open("rb") as source:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    # Keep range files until assembly finishes. Only this run's verified segments are removed.
    for _, _, path in ranges:
        path.unlink()


def extract_work(page, aweme_id):
    match = re.search(
        r'<script\b(?=[^>]*\bid=["\']RENDER_DATA["\'])[^>]*>(.*?)</script>',
        page, re.S,
    )
    if not match:
        raise ValueError("Page has no RENDER_DATA; save the original document response.")
    data = json.loads(unquote(match.group(1)))
    pending = [data]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if str(item.get("awemeId", item.get("aweme_id", ""))) == aweme_id and isinstance(item.get("video"), dict):
                return item
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    raise ValueError(f"Requested work {aweme_id} is absent from the page.")


def download(work, output, source="saved_page_RENDER_DATA_main_playAddr"):
    video = work["video"]
    addresses = video.get("playAddr", [])
    if not addresses:
        raise ValueError("No main playback address; do not treat a separate track as a complete video.")
    url = addresses[0].get("src") if isinstance(addresses[0], dict) else addresses[0]
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if not allowed_media_url(url):
        raise ValueError("Unexpected playback host; manual inspection required.")
    expected = video.get("playAddrSize") or video.get("dataSize")
    output.mkdir(parents=True, exist_ok=True)
    aweme_id = str(work.get("awemeId", work.get("aweme_id")))
    final = output / f"{aweme_id}.mp4"
    partial = final.with_suffix(".mp4.part")
    if final.exists():
        raise FileExistsError(f"Refusing to overwrite {final}; choose a new output directory.")
    if final.is_symlink() or partial.is_symlink():
        raise ValueError("Refusing to write through an existing symbolic link")
    cached = lookup_video(aweme_id, video.get("playAddrFileHash"), expected)
    if cached:
        link_asset(cached, final)
        report = {"aweme_id":aweme_id,"description":work.get("desc"),"duration_ms":video.get("duration"),
                  "bytes":cached.stat().st_size,"md5":video["playAddrFileHash"],
                  "metadata_md5":video["playAddrFileHash"],"size_verified":True,"hash_verified":True,
                  "file":final.name,"source":source,"asset_reused":True}
        final.with_suffix(".json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        return final
    digest = hashlib.md5()
    total = 0
    headers = {"Referer": "https://www.douyin.com/", "User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
    with httpx.Client(timeout=httpx.Timeout(60, connect=20), follow_redirects=True) as client:
        if expected:
            fetch_ranges(client, url, headers, partial, expected)
            with partial.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    total += len(chunk)
            declared = expected
        else:
            raise ValueError("No expected media size; manual inspection required before downloading.")
    if total == 0 or total != expected or total != declared:
        raise ValueError(f"Size mismatch: received={total}, metadata={expected}, HTTP={declared}; partial file retained.")
    with partial.open("rb") as stream:
        if stream.read(12)[4:8] != b"ftyp":
            raise ValueError("Downloaded file is not MP4.")
    actual_hash = digest.hexdigest()
    expected_hash = video.get("playAddrFileHash")
    if expected_hash and actual_hash != expected_hash:
        raise ValueError("File hash differs from page metadata; partial file retained.")
    partial.rename(final)
    publish_video(final, aweme_id, actual_hash)
    report = {
        "aweme_id": aweme_id, "description": work.get("desc"),
        "duration_ms": video.get("duration"), "bytes": total,
        "md5": actual_hash, "metadata_md5": expected_hash,
        "size_verified": True, "hash_verified": bool(expected_hash),
        "file": final.name, "source": source,
    }
    final.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "description"}, indent=2), flush=True)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", type=Path, required=True)
    parser.add_argument("--aweme-id", required=True)
    parser.add_argument("-o", "--output-dir", type=Path, default=Path(__file__).parent / "verified_downloads")
    args = parser.parse_args()
    if not re.fullmatch(r"\d{10,25}", args.aweme_id):
        parser.error("--aweme-id must be a numeric work ID")
    try:
        download(extract_work(args.page.read_text(encoding="utf-8-sig"), args.aweme_id), args.output_dir)
    except Exception as exc:
        # Avoid exposing signed media URLs through network exception messages.
        message = str(exc) if isinstance(exc, (ValueError, FileExistsError, RuntimeError)) else type(exc).__name__
        print(f"FAILED: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
