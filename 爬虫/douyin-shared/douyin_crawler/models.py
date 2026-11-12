from dataclasses import dataclass, field
import re


def first_text(*values):
    return next((value for value in values if isinstance(value, str) and value.strip()), "")


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    description: str
    author_id: str
    hashtags: frozenset[str]
    duration_ms: int
    size_bytes: int
    raw: dict = field(repr=False, compare=False)

    @classmethod
    def from_raw(cls, raw):
        work_id = str(raw.get("aweme_id", raw.get("awemeId", "")))
        if not work_id.isdigit() or not isinstance(raw.get("video"), dict):
            raise ValueError("Not a video work")
        video = raw["video"]
        author = raw.get("author") or raw.get("authorInfo") or {}
        description = first_text(raw.get("desc"), raw.get("caption"))
        title = first_text(raw.get("item_title"), raw.get("itemTitle"), description)
        tags = set()
        for item in raw.get("text_extra", raw.get("textExtra", [])) or []:
            tag = first_text(item.get("hashtag_name"), item.get("hashtagName"))
            if tag:
                tags.add(tag.lstrip("#").casefold())
        # Structured hashtag metadata is authoritative when it is present.
        if not tags:
            tags.update(tag.casefold() for tag in re.findall(r"#([^#\s]+)", description))
        address = video.get("play_addr") or {}
        return cls(work_id, title, description,
                   first_text(author.get("sec_uid"), author.get("secUid")),
                   frozenset(tags), int(video.get("duration") or 0),
                   int(address.get("data_size") or video.get("playAddrSize") or video.get("dataSize") or 0), raw)

    def summary(self):
        return {"id": self.id, "title": self.title, "author_id": self.author_id,
                "hashtags": sorted(self.hashtags), "duration_ms": self.duration_ms,
                "size_bytes": self.size_bytes}


def find_videos(payload):
    pending = [payload]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if (item.get("aweme_id") or item.get("awemeId")) and isinstance(item.get("video"), dict):
                yield Video.from_raw(item)
            else:
                pending.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            pending.extend(reversed(item))
