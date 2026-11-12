"""Browser-owned authentication and playback resolution, shared by every source."""
import time
from urllib.parse import urlsplit
from playwright.async_api import Error as PlaywrightError


async def logged_in(context, page):
    if any(c["name"] == "LOGIN_STATUS" and c["value"] == "1"
           for c in await context.cookies("https://www.douyin.com/")):
        return True
    try:
        return await page.evaluate("() => localStorage.getItem('HasUserLogin') === '1'")
    except PlaywrightError as exc:
        if "Execution context was destroyed" in str(exc):
            return False
        raise


async def wait_login(context, page, timeout):
    deadline = time.monotonic() + timeout
    while not await logged_in(context, page):
        if time.monotonic() >= deadline:
            raise RuntimeError("Login timed out; please log in manually in the dedicated browser")
        await page.wait_for_timeout(1000)
    print("LOGIN_CONFIRMED", flush=True)


async def wait_verification(page, timeout):
    """Only wait for the user; never solve, hide or bypass site verification."""
    async def required():
        title = await page.title()
        if "验证码" in title or "安全验证" in title:
            return True
        for selector in ("#captcha_container", ".captcha_verify_container"):
            node = page.locator(selector)
            if await node.count() and await node.first.is_visible():
                return True
        return False
    if not await required():
        return
    print("HUMAN_VERIFICATION_REQUIRED: please complete verification in the dedicated Edge window", flush=True)
    deadline = time.monotonic() + timeout
    while await required():
        if time.monotonic() >= deadline:
            raise RuntimeError("Manual verification timeout; no alternative route was attempted")
        await page.wait_for_timeout(1000)
    print("MANUAL_VERIFICATION_CLEARED", flush=True)
    await page.wait_for_timeout(4000)


async def resolve_playback(context, video):
    raw = video.raw
    address = raw["video"].get("play_addr", {})
    urls = address.get("url_list", [])
    if not urls and raw["video"].get("playAddr"):
        return raw
    entry = next((url for url in urls if urlsplit(url).hostname == "www.douyin.com"
                  and urlsplit(url).path == "/aweme/v1/play/"), None)
    if entry:
        response = await context.request.get(entry, headers={"Range": "bytes=0-65535", "Referer": "https://www.douyin.com/"}, timeout=30000)
        try:
            if response.status != 206:
                raise RuntimeError(f"Playback resolution HTTP {response.status}")
            if (await response.body())[4:8] != b"ftyp":
                raise ValueError("Playback entry did not return MP4")
            if video.size_bytes and not response.headers.get("content-range", "").endswith(f"/{video.size_bytes}"):
                raise ValueError("Playback size differs from source metadata")
            url = response.url
        finally:
            await response.dispose()
    elif urls:
        url = urls[0]
    else:
        raise ValueError("Video has no main playback address")
    return {"awemeId": video.id, "desc": video.description,
            "video": {"playAddr": [{"src": url}], "playAddrSize": video.size_bytes,
                      "playAddrFileHash": address.get("file_hash"), "duration": video.duration_ms}}
