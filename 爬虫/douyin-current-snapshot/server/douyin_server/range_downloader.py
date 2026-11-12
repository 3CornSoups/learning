"""Bounded async HTTP range downloader. No browser or F2 dependencies.

Validate every range and the assembled file before atomic publication. Signed
URLs and cookies must never be logged. This module does not manage credentials.
"""
import asyncio
import hashlib
from pathlib import Path
import re
import tempfile

import httpx

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Referer': 'https://www.douyin.com/',
    'Accept-Encoding': 'identity',
}


class RangeUnavailable(Exception):
    pass


def validate_range(response, start, end, total):
    wanted = f'bytes {start}-{end}/{total}'
    if response.status_code != 206 or response.headers.get('Content-Range') != wanted:
        raise RangeUnavailable('Server did not honor the exact byte range')
    if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
        raise RangeUnavailable('Encoded ranges cannot be safely joined')
    if 'Content-Length' in response.headers and int(response.headers['Content-Length']) != end-start+1:
        raise RangeUnavailable('Unexpected segment length')


async def download(client, url, destination, *, expected_size=None, expected_md5=None,
                   segments=4, min_segment=256*1024, connections=None, retries=1,
                   max_bytes=100_000_000, events=None):
    """Return True only after full size/hash checks; raise sanitized errors.

    Small files use fewer segments. A server ignoring Range falls back to a
    validated single GET. Retries are bounded and restricted to failed pieces.
    Temporary files live beside the destination and are removed on failure.
    Caller controls the client's connection pool; an optional shared semaphore
    also caps active requests across files. Cancellation awaits all children.
    """
    if not 1 <= segments <= 16 or min_segment < 1 or retries < 0:
        raise ValueError('Invalid download limits')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    gate = connections or asyncio.Semaphore(segments)
    metrics = events if events is not None else []

    with tempfile.TemporaryDirectory(prefix=destination.stem+'.parts-', dir=destination.parent) as directory:
        folder = Path(directory)
        total = None
        range_ok = False
        resolved_url = url
        validator = None
        async with gate:
            async with client.stream('GET', url, headers={**HEADERS, 'Range':'bytes=0-0'},
                                     follow_redirects=True, timeout=30) as response:
                resolved_url = str(response.url)
                match = re.fullmatch(r'bytes 0-0/(\d+)', response.headers.get('Content-Range',''))
                if response.status_code == 206 and match:
                    total = int(match[1])
                    validate_range(response, 0, 0, total)
                    probe = await response.aread()
                    if len(probe) != 1:
                        raise RangeUnavailable('Truncated range probe')
                    range_ok = True
                    etag = response.headers.get('ETag')
                    validator = etag if etag and not etag.startswith('W/') else response.headers.get('Last-Modified')
                elif response.status_code == 200:
                    total = int(response.headers.get('Content-Length', 0)) or expected_size
                else:
                    raise RangeUnavailable(f'Range probe HTTP {response.status_code}')
        if total is None or not 0 < total <= max_bytes:
            raise RangeUnavailable('Unknown or excessive file size')
        if expected_size is not None and total != expected_size:
            raise RangeUnavailable('Source size changed')
        count = min(segments, max(1, total//min_segment)) if range_ok else 1
        metrics.append({'range_supported':range_ok, 'segments':count, 'bytes':total})

        async def piece(index):
            start = total*index//count
            end = total*(index+1)//count-1
            path = folder/str(index)
            for attempt in range(retries+1):
                try:
                    headers = dict(HEADERS)
                    if range_ok:
                        headers['Range'] = f'bytes={start}-{end}'
                        if validator:
                            headers['If-Range'] = validator
                    async with gate:
                        async with client.stream('GET', resolved_url, headers=headers,
                                                 follow_redirects=True, timeout=30) as response:
                            if range_ok:
                                validate_range(response,start,end,total)
                            elif response.status_code != 200:
                                raise RangeUnavailable(f'Single GET HTTP {response.status_code}')
                            received = 0
                            with path.open('wb') as handle:
                                async for chunk in response.aiter_bytes(chunk_size=256*1024):
                                    received += len(chunk)
                                    if received > end-start+1:
                                        raise RangeUnavailable('Oversized segment')
                                    handle.write(chunk)
                            if received != end-start+1:
                                raise RangeUnavailable('Truncated segment')
                    return path
                except (httpx.HTTPError, RangeUnavailable) as exc:
                    metrics.append({'segment':index,'attempt':attempt+1,'error':type(exc).__name__})
                    if attempt == retries or isinstance(exc,RangeUnavailable):
                        raise RangeUnavailable(f'Segment {index} failed: {type(exc).__name__}') from None
                    await asyncio.sleep(.5*(attempt+1))

        tasks = [asyncio.create_task(piece(i)) for i in range(count)]
        try:
            parts = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assembled = folder/'assembled'
        digest = hashlib.md5()
        with assembled.open('wb') as output:
            for part in parts:
                with part.open('rb') as source:
                    while chunk := source.read(1024*1024):
                        digest.update(chunk)
                        output.write(chunk)
        if assembled.stat().st_size != total:
            raise RangeUnavailable('Assembled size mismatch')
        if expected_md5 is not None and digest.hexdigest() != expected_md5:
            raise RangeUnavailable('Assembled MD5 mismatch')
        assembled.replace(destination)
    return True
