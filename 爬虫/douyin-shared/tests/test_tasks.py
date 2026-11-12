import json
from pathlib import Path
import tempfile
import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from douyin_crawler.config import Config, ROOT, parse_args
from douyin_crawler.filters import Filters
from douyin_crawler.history import History
from douyin_crawler.models import Video
from douyin_crawler.runtime import build_task
from douyin_crawler.sources import AuthorSource, HashtagSource, SearchSource

TEMP = ROOT / ".cache" / "tests"
TEMP.mkdir(parents=True, exist_ok=True)
AUTHOR = "MS4wTestAuthor"


def work(work_id="12345678901", **changes):
    raw = {"aweme_id": work_id, "desc": "AI 猫咪视频 #猫咪", "item_title": "Cat documentary",
           "author": {"sec_uid": AUTHOR}, "text_extra": [{"hashtag_name": "猫咪"}],
           "video": {"duration": 12000, "play_addr": {"data_size": 1000, "url_list": []}}}
    raw.update(changes)
    return raw


class SourceTests(unittest.TestCase):
    def test_author_terminal_page_still_returns_last_videos(self):
        source = AuthorSource(Config(source="author", author=AUTHOR, all=True).validate())
        first = f"https://www.douyin.com/aweme/v1/web/aweme/post/?{urlencode({'sec_user_id': AUTHOR, 'max_cursor': 0})}"
        self.assertTrue(source.matches(first))
        self.assertFalse(source.matches(first.replace(AUTHOR, "MS4wOtherAuthor")))
        source.read(first, {"has_more": 1, "max_cursor": 100, "aweme_list": [work()]})
        self.assertFalse(source.exhausted)
        last = first.replace("max_cursor=0", "max_cursor=100")
        videos = source.read(last, {"has_more": 0, "max_cursor": 200, "aweme_list": [work("12345678902")]})
        self.assertTrue(source.exhausted)
        self.assertEqual([v.id for v in videos], ["12345678902"])

    def test_author_excludes_other_authors_and_stalled_cursor(self):
        source = AuthorSource(Config(source="author", author=AUTHOR).validate())
        url = f"https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id={AUTHOR}&max_cursor=100"
        with self.assertRaisesRegex(RuntimeError, "cursor"):
            source.read(url, {"has_more": 1, "max_cursor": 100, "aweme_list": []})
        result = source.read(url, {"has_more": 0, "aweme_list": [work(author={"sec_uid": "MS4wOther"})]})
        self.assertEqual(result, [])

    def test_search_extracts_nested_results_and_scopes_keyword(self):
        source = SearchSource(Config(source="search", keyword="猫咪").validate())
        url = "https://www.douyin.com/aweme/v1/web/general/search/single/?" + urlencode({"keyword": "猫咪"})
        self.assertTrue(source.matches(url))
        self.assertFalse(source.matches(url.replace("keyword=", "other=")))
        result = source.read(url, {"data": [{"aweme_info": work()}], "has_more": "0"})
        self.assertEqual([v.id for v in result], ["12345678901"])
        self.assertTrue(source.exhausted)

    def test_all_needs_a_finite_source(self):
        with self.assertRaisesRegex(ValueError, "does not support"):
            build_task(Config(all=True).validate())
        source, _ = build_task(Config(source="author", author=AUTHOR, all=True).validate())
        self.assertTrue(source.supports_all)


class FilterTests(unittest.TestCase):
    def test_hashtag_is_exact_and_structured_metadata_wins(self):
        config = Config(source="hashtag", tag="猫咪").validate()
        filters = Filters(config)
        self.assertIn("%23", HashtagSource(config).url)
        self.assertIsNone(filters.reject(Video.from_raw(work())))
        different = work(text_extra=[{"hashtag_name": "猫咪日常"}])
        self.assertEqual(filters.reject(Video.from_raw(different)), "hashtag")

    def test_title_contains_is_case_insensitive_and_all_words_required(self):
        filters = Filters(Config(title_contains=["cat", "AI"]).validate())
        self.assertIsNone(filters.reject(Video.from_raw(work())))
        self.assertEqual(filters.reject(Video.from_raw(work(item_title="狗", desc="AI 狗"))), "title_contains")

    def test_configurable_rule_and_plugin_reuse(self):
        config = Config(plugins=["plugins.min_likes"], rules=[{"type": "min_likes", "value": 10}]).validate()
        for _ in range(2):
            _, filters = build_task(config)
            self.assertEqual(filters.reject(Video.from_raw(work(statistics={"digg_count": 9}))), "min_likes")
            self.assertIsNone(filters.reject(Video.from_raw(work(statistics={"digg_count": 10}))))


class StateAndConfigTests(unittest.TestCase):
    def test_missing_and_partial_files_are_not_completed(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as name:
            root = Path(name)
            history = History(root / "history.sqlite3")
            try:
                file = root / "video.mp4"
                history.record("1", file, {"bytes": 10, "md5": "test"})
                file.with_suffix(".mp4.part").write_bytes(b"0123456789")
                self.assertFalse(history.contains("1"))
                file.write_bytes(b"short")
                self.assertFalse(history.contains("1"))
                file.write_bytes(b"0123456789")
                self.assertTrue(history.contains("1"))
            finally:
                history.close()

    def test_config_relative_paths_and_cli_limit_override_all(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as name:
            config = Path(name) / "task.json"
            config.write_text(json.dumps({"source": "author", "author": AUTHOR, "all": True, "output_dir": "media"}), encoding="utf-8")
            parsed = parse_args(["--config", str(config), "--limit", "2"])
            self.assertFalse(parsed.all)
            self.assertEqual(parsed.limit, 2)
            self.assertEqual(parsed.output_dir, Path(name) / "media")

    def test_all_defaults_remove_short_video_caps(self):
        parsed = Config(source="author", author=AUTHOR, all=True).validate()
        self.assertEqual((parsed.limit, parsed.max_duration, parsed.max_video_mb), (0, 0, 0))
        with self.assertRaises(ValueError):
            Config(source="author", author=AUTHOR, all=True, limit=1).validate()


class RuntimeTests(unittest.TestCase):
    def test_all_drains_terminal_page_prefetched_during_download(self):
        from douyin_crawler import runtime

        class Response:
            status = 200

            def __init__(self, cursor, payload):
                self.url = f"https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id={AUTHOR}&max_cursor={cursor}"
                self.payload = payload

            async def json(self):
                return self.payload

        class Page:
            callback = None

            async def goto(self, url, **kwargs):
                if "/user/" in url:
                    self.callback(Response(0, {"has_more": 1, "max_cursor": 100, "aweme_list": [work()]}))

            def on(self, event, callback):
                self.callback = callback

            def remove_listener(self, *args):
                pass

            async def wait_for_timeout(self, milliseconds):
                await asyncio.sleep(0)

            def get_by_text(self, *args, **kwargs):
                return SimpleNamespace(count=AsyncMock(return_value=0))

        page = Page()

        class Browser:
            pages = [page]
            close = AsyncMock()

        class Driver:
            chromium = SimpleNamespace(launch_persistent_context=AsyncMock(return_value=Browser()))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        async def exercise(config):
            loop = asyncio.get_running_loop()

            def downloader(normalized, output, source):
                work_id = normalized["aweme_id"]
                output.mkdir(parents=True, exist_ok=True)
                path = output / f"{work_id}.mp4"
                path.write_bytes(b"download fixture")
                path.with_suffix(".json").write_text(json.dumps({"bytes": path.stat().st_size, "md5": "fixture", "hash_verified": True}), encoding="utf-8")
                if work_id == "12345678901":
                    loop.call_soon_threadsafe(page.callback, Response(100, {"has_more": 0, "max_cursor": 200, "aweme_list": [work("12345678902")]}))
                return path

            with patch.object(runtime, "async_playwright", return_value=Driver()), \
                 patch.object(runtime, "wait_login", new=AsyncMock()), \
                 patch.object(runtime, "wait_verification", new=AsyncMock()), \
                 patch.object(runtime, "resolve_playback", new=AsyncMock(side_effect=lambda context, video: video.raw)), \
                 patch.object(runtime, "download", side_effect=downloader), \
                 patch.object(runtime, "inspect_tracks", return_value=[]):
                return await runtime.run(config)

        with tempfile.TemporaryDirectory(dir=TEMP) as name:
            root = Path(name)
            config = Config(source="author", author=AUTHOR, all=True, max_scrolls=0,
                            output_dir=root / "media", state_dir=root / "runs", profile_dir=root / "profile").validate()
            self.assertEqual(asyncio.run(exercise(config)), 0)
            report = json.loads(next((root / "runs").glob("*/report.json")).read_text(encoding="utf-8"))
            self.assertEqual([v["id"] for v in report["downloaded"]], ["12345678901", "12345678902"])
            self.assertEqual(report["coverage"], "all_accessible_matching_videos")


if __name__ == "__main__":
    unittest.main()
