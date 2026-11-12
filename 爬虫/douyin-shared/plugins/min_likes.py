"""Working example: enable with --plugin plugins.min_likes and a JSON rule."""
from douyin_crawler.filters import register_filter


def minimum_likes(options):
    threshold = int(options["value"])
    if threshold < 0:
        raise ValueError("min_likes.value must be nonnegative")

    def rule(video):
        statistics = video.raw.get("statistics") or video.raw.get("stats") or {}
        likes = statistics.get("digg_count", statistics.get("diggCount", 0))
        return None if likes >= threshold else "min_likes"
    return rule


def register():
    register_filter("min_likes", minimum_likes)
