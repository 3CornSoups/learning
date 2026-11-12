from urllib.parse import urlsplit

# Additional CDN host observed in a successful HTTPS range response obtained
# directly through Douyin's signed playback entry. Keep it exact, not arbitrary.
EXTRA_HOSTS = {"v5-hl-mly-ov.zjcdn.com"}


def allowed_media_url(value):
    url = urlsplit(value)
    host = url.hostname or ""
    return bool(url.scheme == "https" and not url.username and not url.password and
                (host.endswith(".douyinvod.com") or host.endswith(".douyin.com") or host in EXTRA_HOSTS))
