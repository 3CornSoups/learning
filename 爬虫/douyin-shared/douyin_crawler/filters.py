"""A filter factory receives JSON options and returns Video -> reason | None."""
import re

RULES = {}


def register_filter(name, factory):
    if name in RULES:
        raise ValueError(f"Filter already registered: {name}")
    RULES[name] = factory


def contains_factory(options):
    words = options.get("words") or [options.get("value", "")]
    if not isinstance(words, list) or not words or any(not isinstance(word, str) or not word.strip() for word in words):
        raise ValueError("title_contains needs nonempty words")
    mode = options.get("match", "all")
    if mode not in ("all", "any"):
        raise ValueError("title_contains.match must be all or any")
    words = [word.casefold() for word in words]

    def rule(video):
        text = f"{video.title}\n{video.description}".casefold()
        matched = (all if mode == "all" else any)(word in text for word in words)
        return None if matched else "title_contains"
    return rule


def hashtag_factory(options):
    value = options.get("value", "").strip().lstrip("#").casefold()
    if not value:
        raise ValueError("hashtag filter needs a nonempty value")
    return lambda video: None if value in video.hashtags else "hashtag"


def regex_factory(options):
    value = options.get("pattern")
    if not isinstance(value, str) or not value:
        raise ValueError("title_regex needs a nonempty pattern")
    try:
        pattern = re.compile(value, re.I)
    except re.error as exc:
        raise ValueError(f"Invalid title_regex: {exc}") from exc
    return lambda video: None if pattern.search(f"{video.title}\n{video.description}") else "title_regex"


register_filter("title_contains", contains_factory)
register_filter("hashtag", hashtag_factory)
register_filter("title_regex", regex_factory)


class Filters:
    def __init__(self, config):
        self.config = config
        specs = list(config.rules)
        if config.title_contains:
            specs.append({"type": "title_contains", "words": config.title_contains})
        if config.tag:
            specs.append({"type": "hashtag", "value": config.tag})
        self.rules = []
        for spec in specs:
            kind = spec.get("type")
            if kind not in RULES:
                raise ValueError(f"Unknown filter: {kind}")
            self.rules.append(RULES[kind](spec))

    def reject(self, video):
        raw = video.raw
        if raw.get("is_ads") or raw.get("isAds") or raw.get("images"):
            return "advertisement_or_album"
        status = raw.get("status") or {}
        if raw.get("isPrivate") or raw.get("isFriendLimit") or status.get("is_private") or status.get("private_status", 0):
            return "non_public"
        if self.config.max_duration and video.duration_ms > self.config.max_duration * 1000:
            return "duration_limit"
        if self.config.max_video_mb and video.size_bytes > self.config.max_video_mb * 1_000_000:
            return "size_limit"
        for rule in self.rules:
            reason = rule(video)
            if reason:
                return reason
        return None
