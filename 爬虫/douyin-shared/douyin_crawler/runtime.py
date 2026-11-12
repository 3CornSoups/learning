import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import json
import os
import re
import hashlib
from urllib.parse import urlsplit, unquote

from playwright.async_api import async_playwright

from download_from_page import download
from verify_media import inspect_tracks
from .browser import wait_login, wait_verification, resolve_playback
from .config import ROOT
from .filters import Filters
from .history import History
from .sources import SOURCES
from .jobs import ManifestWriter

LOADED_PLUGINS = set()


def build_task(config):
    for module in config.plugins:
        if module not in LOADED_PLUGINS:
            importlib.import_module(module).register()
            LOADED_PLUGINS.add(module)
    if config.source not in SOURCES:
        raise ValueError(f"Unknown source {config.source}; available: {', '.join(SOURCES)}")
    source = SOURCES[config.source](config)
    if config.all and not source.supports_all:
        raise ValueError(f"Source {config.source} does not support --all; use --limit")
    return source, Filters(config)


async def run(config):
    # Validate plugins and filters before opening a browser or creating output files.
    source, filters = build_task(config)
    temporary = ROOT / ".cache" / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(temporary)
    os.environ["TMP"] = str(temporary)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = config.state_dir / stamp
    run_dir.mkdir()
    report = {"started_utc": stamp, "source": config.source, "source_url": source.url,
              "config": asdict(config), "discovered": [], "selected": [], "downloaded": [],
              "skipped": [], "failed": [], "responses": [], "exported": [], "completed": False, "coverage": "partial", "pid": os.getpid(), "ppid": os.getppid()}
    exporter = ManifestWriter(config.export_manifest, stamp) if config.export_manifest else None
    history = History(config.state_dir / "history.sqlite3", (ROOT / "verified_downloads", config.output_dir))
    candidates = {}
    processed = set()
    tasks = set()
    fatal = []

    def save():
        report["updated_utc"] = datetime.now(timezone.utc).isoformat()
        report["discovered"] = [video.summary() for video in candidates.values()]
        report["source_pages"] = source.pages
        report["source_exhausted"] = source.exhausted
        temp = run_dir / "report.json.tmp"
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temp.replace(run_dir / "report.json")
        (run_dir / "candidates.json").write_text(json.dumps({key: value.raw for key, value in candidates.items()}, ensure_ascii=False), encoding="utf-8")

    def finish(reason):
        report["completed"] = True
        report["stop_reason"] = reason
        report["coverage"] = "all_accessible_matching_videos" if reason == "source_exhausted" else "requested_batch"
        print(f"COMPLETED: {reason}; downloaded={len(report['downloaded'])}, selected={len(report['selected'])}", flush=True)
        return 0

    async def observe(response):
        parsed = urlsplit(response.url)
        host = parsed.hostname or ""
        if not (host == "douyin.com" or host.endswith(".douyin.com")):
            return
        if parsed.path == "/aweme/v1/web/user/profile/self/" and response.status == 200:
            try:
                identity = await response.json()
                user = identity.get("user") or identity.get("user_info") or {}
                uid = user.get("uid") or user.get("sec_uid")
                report["server_authenticated_profile"] = bool(uid and identity.get("status_code", 0) == 0)
                if uid:
                    report["identity_hash"] = hashlib.sha256(str(uid).encode()).hexdigest()
            except Exception:
                pass
        if "/aweme/" in parsed.path:
            report.setdefault("observed_paths", []).append(parsed.path)
        if not source.matches(response.url):
            return
        entry = {"path": parsed.path, "status": response.status}
        report["responses"].append(entry)
        try:
            if response.status != 200:
                raise RuntimeError(f"Source HTTP {response.status}")
            videos = source.read(response.url, await response.json())
            added = 0
            for video in videos:
                if video.id not in candidates:
                    added += 1
                candidates[video.id] = video
            entry["new_candidates"] = added
            print(f"Source page {source.pages}: {added} new works, exhausted={source.exhausted}", flush=True)
            save()
        except Exception as exc:
            entry["error"] = type(exc).__name__
            fatal.append(exc)

    def on_response(response):
        task = asyncio.create_task(observe(response))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(config.profile_dir), channel=None if config.browser_channel == "chromium" else config.browser_channel, headless=False,
                accept_downloads=False, viewport={"width": 1360, "height": 900},
            )
            try:
                if config.storage_state:
                    await context.set_storage_state(config.storage_state)
                page = context.pages[0] if context.pages else await context.new_page()
                page.on("response", on_response)
                await page.goto(source.url, wait_until="domcontentloaded", timeout=60000)
                print("Waiting for manual login if needed...", flush=True)
                await wait_login(context, page, config.login_timeout)
                if config.login_only:
                    return finish("login_saved")
                if urlsplit(getattr(page, "url", source.url)).path != urlsplit(source.url).path:
                    await page.goto(source.url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(8000)
                await wait_verification(page, config.login_timeout)
                onboarding = page.get_by_text("我知道了", exact=True)
                if await onboarding.count() and await onboarding.first.is_visible():
                    await onboarding.first.click()
                if config.inspect:
                    (run_dir / "page.html").write_text(await page.content(), encoding="utf-8")
                    (run_dir / "page.txt").write_text(await page.locator("body").inner_text(), encoding="utf-8")
                    return finish("inspection_saved")
                scroll = 0
                while True:
                    if tasks:
                        await asyncio.gather(*list(tasks))
                    if fatal:
                        raise fatal[0]
                    for work_id, video in list(candidates.items()):
                        if work_id in processed:
                            continue
                        processed.add(work_id)
                        reason = "already_downloaded" if history.contains(work_id) else filters.reject(video)
                        if reason:
                            report["skipped"].append({"id": work_id, "reason": reason})
                            continue
                        report["selected"].append(video.summary())
                        if exporter:
                            normalized = await resolve_playback(context, video)
                            exporter.add(video, normalized, config.source)
                            report["exported"].append(video.summary())
                            print(f"Exported media job {work_id}", flush=True)
                        elif not config.discover_only:
                            try:
                                normalized = await resolve_playback(context, video)
                                print(f"Downloading {work_id}", flush=True)
                                path = await asyncio.to_thread(download, normalized, config.output_dir, f"browser_{config.source}")
                                tracks = inspect_tracks(path)
                                saved = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
                                saved.update(video.summary())
                                saved["tracks_verified"] = True
                                path.with_suffix(".json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
                                history.record(work_id, path, saved)
                                report["downloaded"].append({"id": work_id, "file": str(path), "bytes": saved["bytes"], "downloaded_utc": datetime.now(timezone.utc).isoformat(),
                                                             "hash_verified": saved["hash_verified"], "tracks": tracks})
                            except Exception as exc:
                                report["failed"].append({"id": work_id, "error": type(exc).__name__})
                                raise
                        save()
                        if config.limit and len(report["selected"]) >= config.limit:
                            return finish("limit_reached")
                        if config.download_interval:
                            await page.wait_for_timeout(config.download_interval * 1000)
                    if tasks:
                        await asyncio.gather(*list(tasks))
                    if fatal:
                        raise fatal[0]
                    # The browser may prefetch more pages during a download.
                    # Drain those works before trusting a terminal has_more=0.
                    if any(work_id not in processed for work_id in candidates):
                        continue
                    save()
                    if source.exhausted:
                        return finish("source_exhausted")
                    if scroll >= config.max_scrolls:
                        break
                    await source.advance(page)
                    scroll += 1
                    print(f"Advancing {config.source}: {scroll}/{config.max_scrolls}", flush=True)
                    await page.wait_for_timeout(config.wait_seconds * 1000)
                    await wait_verification(page, config.login_timeout)
                report["stop_reason"] = "scroll_limit_without_source_end"
                print("INCOMPLETE: scroll limit reached; source exhaustion was not confirmed", flush=True)
                return 2
            finally:
                page.remove_listener("response", on_response)
                if tasks:
                    await asyncio.gather(*list(tasks), return_exceptions=True)
                await context.close()
    except Exception as exc:
        report["error"] = type(exc).__name__
        report["error_message"] = re.sub(r"https?://\S+", "[URL]", str(exc))[:3000]
        report["stop_reason"] = "error"
        print(f"FAILED: {report['error_message']}", flush=True)
        return 1
    finally:
        save()
        history.close()
        print(f"Report: {run_dir / 'report.json'}", flush=True)


def main(argv=None):
    from .config import parse_args
    try:
        return asyncio.run(run(parse_args(argv)))
    except (ValueError, ImportError, AttributeError) as exc:
        print(f"Configuration error: {exc}", flush=True)
        return 2
