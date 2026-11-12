"""Bounded worker pool, integrity-checked outcomes and machine-readable reports."""
import asyncio
import contextvars
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import time

from .support import atomic_json, inspect_file, OutputLock, ValidationError
from .asset_refs import lookup_video, link_asset, publish_video, verify_link, video_store

CURRENT = contextvars.ContextVar('video_id', default=None)


class DiscardOutput(io.TextIOBase):
    # Original libraries can print signed URLs. Reports only save structured
    # error classes / response evidence; raw library output is not persisted.
    def write(self, text):
        return len(text)
    def flush(self):
        pass


async def collect(ids, output, report_path, concurrency, operation, evidence, verify='basic', segments=1):
    """Pure orchestration seam: `operation(id)` returns the original success bool."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / '.douyin-index.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
    report = {'schema_version': 1, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'state': 'running', 'requested_ids': ids, 'concurrency': concurrency,
              'segments': segments, 'verify': verify, 'output': str(output.resolve()), 'files': [],
              'definitions': {'MB': '1000000 bytes', 'elapsed': 'entire task including metadata, queueing, transfer and validation'}}
    queue = asyncio.Queue()
    for work_id in ids:
        queue.put_nowait(work_id)
    started = time.perf_counter()
    atomic_json(report_path, report)

    async def worker():
        while True:
            try:
                work_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            token = CURRENT.set(work_id)
            before = bool(list(output.glob(work_id + '_*.mp4')))
            row = {'id': work_id, 'state': 'failed'}
            item_started = time.perf_counter()
            try:
                success = await operation(work_id)
                paths = list(output.glob(work_id + '_*.mp4'))
                if not success:
                    raise ValidationError('作品处理失败；请查看 metadata 字段，并先用单条清单排查接口')
                if len(paths) != 1:
                    raise ValidationError('没有唯一的视频文件；图集不在当前服务器入口的验收范围内')
                candidates = [h for e in evidence.get(work_id, []) for h in e.get('hashes', [])]
                previous = index.get(work_id, {})
                inspected = inspect_file(paths[0], candidates, ffprobe=verify == 'ffprobe',
                                         expected_md5=previous.get('md5') if before else None)
                index[work_id] = {'md5': inspected['md5'], 'bytes': inspected['bytes']}
                atomic_json(index_path, index)
                row.update(inspected, state='skipped' if before else 'downloaded')
            except Exception as exc:
                # Our own validation errors contain no signed addresses.
                row['error_type'] = type(exc).__name__
                row['error'] = str(exc) if isinstance(exc, ValidationError) else '后端异常；先检查 doctor 和单条任务'
            finally:
                row['elapsed_seconds'] = time.perf_counter() - item_started
                row['metadata'] = [{k: v for k, v in e.items() if k != 'hashes'} for e in evidence.get(work_id, [])]
                report['files'].append(row)
                CURRENT.reset(token)
                queue.task_done()
                atomic_json(report_path, report)

    tasks = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(ids)))]
    try:
        await asyncio.gather(*tasks)
        report['state'] = 'complete'
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if report['state'] == 'running':
            report['state'] = 'interrupted'
        report['elapsed_seconds'] = time.perf_counter() - started
        report['downloaded'] = sum(r['state'] == 'downloaded' for r in report['files'])
        report['skipped'] = sum(r['state'] == 'skipped' for r in report['files'])
        report['failed'] = sum(r['state'] == 'failed' for r in report['files'])
        reported_ids = {r['id'] for r in report['files']}
        report['pending_ids'] = [i for i in ids if i not in reported_ids]
        report['new_bytes'] = sum(r.get('bytes', 0) for r in report['files'] if r['state'] == 'downloaded')
        report['batch_MBps'] = report['new_bytes'] / 1e6 / report['elapsed_seconds']
        atomic_json(report_path, report)
    return report


async def execute(ids, cookie, output, report_path, concurrency=5, verify='basic', segments=1, range_connections=12):
    import httpx
    from .backend import make_backend, response_evidence
    initial_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with redirect_stdout(DiscardOutput()), redirect_stderr(DiscardOutput()):
            original, handler = make_backend(cookie)
    finally:
        logging.disable(initial_logging)
    send = httpx.AsyncClient.send
    original_download = original.download_file
    previous_logging = logging.root.manager.disable
    evidence = {}

    async def observed_send(client, request, *args, **kwargs):
        response = await send(client, request, *args, **kwargs)
        if '/aweme/v1/web/' in request.url.path and CURRENT.get():
            body = await response.aread()
            evidence.setdefault(CURRENT.get(), []).append(response_evidence(body, response.status_code))
        return response

    with OutputLock(output):
        httpx.AsyncClient.send = observed_send
        logging.disable(logging.CRITICAL)
        try:
            async with httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=50, max_connections=100), verify=False) as client:
                if segments > 1:
                    from . import range_downloader
                    gate = asyncio.Semaphore(range_connections)
                    async def ranged(client, url, path):
                        if path.suffix.lower() != '.mp4':
                            return await original_download(client, url, path)
                        try:
                            return await range_downloader.download(client, url, path, segments=segments, connections=gate)
                        except (httpx.HTTPError, range_downloader.RangeUnavailable):
                            return False
                    original.download_file = ranged
                network_download = original.download_file
                async def reusable_download(client, url, path):
                    path = Path(path)
                    if path.suffix.lower() != '.mp4' or video_store() is None:
                        return await network_download(client, url, path)
                    work_id = CURRENT.get()
                    for item in evidence.get(work_id, []):
                        for checksum in item.get('hashes', []):
                            cached = lookup_video(work_id, checksum['md5'], checksum.get('size'))
                            if cached:
                                if path.exists() or path.is_symlink():
                                    if not path.is_symlink():
                                        return True
                                    verify_link(path)
                                else:
                                    link_asset(cached, path)
                                return True
                    if path.is_symlink():
                        verify_link(path)
                        return True
                    if path.with_suffix(path.suffix + '.tmp').is_symlink():
                        raise ValidationError('拒绝通过符号链接写入临时下载文件')
                    success = await network_download(client, url, path)
                    if success and path.is_file():
                        inspect_file(path)
                        publish_video(path, work_id)
                    return success
                original.download_file = reusable_download
                semaphore = asyncio.Semaphore(concurrency)
                async def operation(work_id):
                    return await original.process_url(semaphore, client, 'https://www.douyin.com/video/' + work_id, handler, Path(output))
                with redirect_stdout(DiscardOutput()), redirect_stderr(DiscardOutput()):
                    return await collect(ids, output, report_path, concurrency, operation, evidence, verify, segments)
        finally:
            original.download_file = original_download
            httpx.AsyncClient.send = send
            logging.disable(previous_logging)
