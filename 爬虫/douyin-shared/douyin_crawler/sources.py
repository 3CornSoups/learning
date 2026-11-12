"""Source adapters own navigation, response scope and pagination termination."""
from dataclasses import dataclass
from urllib.parse import urlsplit, parse_qs, quote
import re

from .models import find_videos

SOURCES = {}


def register_source(name, factory):
    if name in SOURCES:
        raise ValueError(f"Source already registered: {name}")
    SOURCES[name] = factory


def author_id(value):
    if value.startswith("https://"):
        parsed = urlsplit(value)
        if parsed.hostname not in ("www.douyin.com", "douyin.com"):
            raise ValueError("Author URL must be a douyin.com user homepage")
        value = parsed.path.removeprefix("/user/").rstrip("/") if parsed.path.startswith("/user/") else ""
    if not re.fullmatch(r"MS4[\w.-]+", value):
        raise ValueError("Provide an author /user/MS4... homepage or sec_user_id; short share URLs are not supported")
    return value


@dataclass
class Source:
    url: str
    exhausted: bool = False
    pages: int = 0
    supports_all: bool = False

    def matches(self, url):
        raise NotImplementedError

    def read(self, url, payload):
        status = payload.get("status_code", 0)
        if status not in (0, "0", None):
            raise RuntimeError(f"Source returned status_code={status}")
        self.pages += 1
        return list(find_videos(payload))

    async def advance(self, page):
        await page.bring_to_front()
        await page.mouse.move(1000, 650)
        await page.mouse.wheel(0, 1500)


class FeedSource(Source):
    def __init__(self, config):
        super().__init__("https://www.douyin.com/?recommend=1&from_nav=1")
        self.keyboard_batch = int(config.source_options.get("keyboard_batch", 1))
        if not 1 <= self.keyboard_batch <= 5:
            raise ValueError("keyboard_batch must be between 1 and 5")

    def matches(self, url):
        return urlsplit(url).path == "/aweme/v1/web/tab/feed/"

    async def advance(self, page):
        active = page.locator('[data-e2e="feed-active-video"]')
        if not getattr(self, "_keyboard_focused", False) and await active.count():
            await page.bring_to_front()
            await active.first.click()
            self._keyboard_focused = True
        for _ in range(self.keyboard_batch):
            await page.keyboard.press("ArrowDown")
            if self.keyboard_batch > 1:
                await page.wait_for_timeout(2000)


class AuthorSource(Source):
    def __init__(self, config):
        self.author = author_id(config.author)
        super().__init__(f"https://www.douyin.com/user/{self.author}")
        self.supports_all = True

    def matches(self, url):
        parsed = urlsplit(url)
        return parsed.path == "/aweme/v1/web/aweme/post/" and parse_qs(parsed.query).get("sec_user_id") == [self.author]

    def read(self, url, payload):
        videos = super().read(url, payload)
        if "has_more" in payload:
            self.exhausted = payload["has_more"] in (False, 0, "0")
            cursor = payload.get("max_cursor")
            request_cursor = parse_qs(urlsplit(url).query).get("max_cursor", ["0"])[0]
            if not self.exhausted and request_cursor != "0" and str(cursor) == request_cursor:
                raise RuntimeError("Author pagination cursor did not advance")
        return [video for video in videos if not video.author_id or video.author_id == self.author]


class SearchSource(Source):
    def __init__(self, config):
        self.keyword = config.keyword
        super().__init__(f"https://www.douyin.com/search/{quote(self.keyword, safe='')}?type=video")

    def matches(self, url):
        parsed = urlsplit(url)
        if not any(fragment in parsed.path for fragment in ("/general/search/", "/search/item/")):
            return False
        return parse_qs(parsed.query).get("keyword") == [self.keyword]

    def read(self, url, payload):
        videos = super().read(url, payload)
        if "has_more" in payload:
            self.exhausted = payload["has_more"] in (False, 0, "0")
        return videos


class HashtagSource(SearchSource):
    def __init__(self, config):
        # Exact membership is enforced by the shared hashtag filter, not fuzzy search.
        self.keyword = "#" + config.tag.lstrip("#")
        Source.__init__(self, f"https://www.douyin.com/search/{quote(self.keyword, safe='')}?type=video")


register_source("feed", FeedSource)
register_source("author", AuthorSource)
register_source("search", SearchSource)
register_source("hashtag", HashtagSource)
