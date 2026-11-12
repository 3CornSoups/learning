#!/usr/bin/env python3
"""下载B站视频：视频链接/BV号、文本列表、UP主和多P。"""
from __future__ import annotations
import argparse
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
URL_RE = re.compile(r"https?://[^\s<>\"'，。；！？、（）【】]+", re.I)
ID_RE = re.compile(r"(?:BV[0-9A-Za-z]{10}|av\d+)", re.I)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须是大于0的整数")
    return number


def get_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("urls", nargs="*", help="B站链接、分享文字或BV/av号")
    p.add_argument("-i", "--input-file", type=Path, help="UTF-8文本，每行一个链接，支持#注释")
    p.add_argument("-o", "--output-dir", type=Path, default=ROOT / "bilibili_videos", help="保存目录，默认脚本旁的bilibili_videos")
    p.add_argument("--up", help="UP主UID或空间主页，默认最新2条投稿")
    p.add_argument("--limit", type=positive_int, default=2, help="最多处理前N条输入/列表记录，默认2条")
    p.add_argument("--all-parts", action="store_true", help="下载全部分P；默认指定的P，未指定时P1")
    p.add_argument("--height", type=positive_int, default=1080, help="分辨率上限，默认1080，实际受账号权限限制")
    auth = p.add_mutually_exclusive_group()
    auth.add_argument("--cookies", type=Path, help="Netscape格式cookies.txt，不是Cookie请求头")
    auth.add_argument("--browser", choices=("edge", "chrome", "firefox", "brave", "chromium"), help="显式读取浏览器登录状态")
    p.add_argument("--ffmpeg-location", type=Path, help="FFmpeg可执行文件或所在目录")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--simulate", action="store_true", help="只解析，不下载")
    mode.add_argument("--list-formats", action="store_true", help="只列出可用格式，不下载")
    return p


def normalize_sources(text: str) -> list[str]:
    text = text.strip()
    if not text or text.startswith("#"):
        return []
    matches = URL_RE.findall(text)
    if not matches:
        candidate = text.split("#", 1)[0].strip()
        if not ID_RE.fullmatch(candidate):
            raise ValueError(f"未识别到B站链接或BV/av号：{text}")
        candidate = "BV" + candidate[2:] if candidate[:2].lower() == "bv" else candidate.lower()
        return [f"https://www.bilibili.com/video/{candidate}"]
    sources = []
    for match in matches:
        url = match.rstrip(").,;!?]}）】。，；！？")
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.username or parsed.password or not (
            host == "bilibili.com" or host.endswith(".bilibili.com") or host == "b23.tv"
        ):
            raise ValueError(f"仅支持bilibili.com或b23.tv链接：{url}")
        sources.append(url)
    return sources


def collect_sources(args: argparse.Namespace) -> list[str]:
    sources = []
    for text in args.urls:
        sources.extend(normalize_sources(text))
    input_file = args.input_file
    if not args.urls and not args.up and input_file is None:
        input_file = ROOT / "bilibili_urls.txt"
    if input_file is not None:
        for line_no, line in enumerate(input_file.read_text(encoding="utf-8-sig").splitlines(), 1):
            try:
                sources.extend(normalize_sources(line))
            except ValueError as exc:
                raise ValueError(f"{input_file} 第{line_no}行：{exc}") from exc
    if args.up:
        if args.up.isdigit():
            uid = args.up
        else:
            parsed = urlsplit(args.up)
            uid = parsed.path.strip("/").split("/")[0]
            if parsed.scheme not in ("http", "https") or parsed.hostname != "space.bilibili.com" or not uid.isdigit():
                raise ValueError("--up需要数字UID或https://space.bilibili.com/数字UID")
        sources.append(f"https://space.bilibili.com/{uid}/video")
    if args.all_parts:
        expanded = []
        for url in sources:
            parsed = urlsplit(url)
            if parsed.hostname in ("www.bilibili.com", "bilibili.com", "m.bilibili.com") and parsed.path.startswith("/video/"):
                query = urlencode([(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "p"])
                url = urlunsplit(parsed._replace(query=query))
            expanded.append(url)
        sources = expanded
    return list(dict.fromkeys(sources))


def find_ffmpeg(location: Path | None) -> str:
    if location:
        exe = location / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg") if location.is_dir() else location
        if not exe.is_file():
            raise ValueError(f"找不到FFmpeg：{exe}")
        return str(exe.resolve())
    installed = shutil.which("ffmpeg")
    if installed:
        return installed
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise ValueError("未找到FFmpeg，请安装requirements.txt中的依赖或指定--ffmpeg-location。") from exc


def make_options(args: argparse.Namespace, ffmpeg: str | None) -> dict:
    output = args.output_dir.expanduser().resolve()
    cap = f"[height<=?{args.height}]"
    opts = {
        "format": f"bestvideo{cap}+bestaudio/best{cap}",
        "merge_output_format": "mp4",
        "outtmpl": str(output / "%(uploader).50B" / "%(title).100B [%(id)s].%(ext)s"),
        "windowsfilenames": True,
        "continuedl": True,
        "overwrites": False,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 2,
        "socket_timeout": 30,
        "sleep_interval": 2,
        "max_sleep_interval": 4,
        "sleep_interval_requests": 1,
        "noplaylist": not args.all_parts,
        "ignoreerrors": False,
        "simulate": args.simulate or args.list_formats,
        "listformats": args.list_formats,
        # Avoid writing caches into the user profile.
        "cachedir": False,
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if not opts["simulate"]:
        opts["download_archive"] = str(output / "downloaded.txt")
        opts["writeinfojson"] = True
    if args.cookies:
        if not args.cookies.is_file():
            raise ValueError(f"Cookie文件不存在：{args.cookies}")
        opts["cookiefile"] = str(args.cookies.resolve())
    if args.browser:
        opts["cookiesfrombrowser"] = (args.browser,)
    return opts


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = get_parser().parse_args(argv)
    try:
        urls = collect_sources(args)
        if args.limit:
            urls = urls[:args.limit]
        if not urls:
            raise ValueError("没有视频链接，请传入URL或在bilibili_urls.txt中每行填一个链接。")
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
        except ImportError:
            raise ValueError("缺少依赖，请运行：python -m pip install -U -r requirements.txt") from None
        ffmpeg = None if args.simulate or args.list_formats else find_ffmpeg(args.ffmpeg_location)
        base_opts = make_options(args, ffmpeg)
        output = args.output_dir.expanduser().resolve()
        if not base_opts["simulate"]:
            output.mkdir(parents=True, exist_ok=True)
        failures = []
        for index, url in enumerate(urls, 1):
            print(f"\n[{index}/{len(urls)}] {url}", flush=True)
            opts = dict(base_opts)
            is_space = urlsplit(url).hostname == "space.bilibili.com"
            opts["playlistend"] = args.limit
            if is_space:
                opts["noplaylist"] = False
            try:
                with YoutubeDL(opts) as downloader:
                    status = downloader.download([url])
                if status:
                    failures.append(url)
            except DownloadError as exc:
                failures.append(url)
                error_text = str(exc)
                if "Could not copy Chrome cookie database" in error_text:
                    print("浏览器Cookie数据库无法读取。请保存浏览器内容后完全退出浏览器，或改用 --cookies 指定Netscape格式文件。", file=sys.stderr)
                elif is_space and any(code in error_text for code in ("(352)", "(412)", "(401)")):
                    print("UP主投稿接口拒绝请求。可在浏览器打开投稿页，用本目录的“导出本页视频链接.html”导出TXT，再通过 -i 批量下载。", file=sys.stderr)
                    saved_list = ROOT / f"up_{urlsplit(url).path.strip('/').split('/')[0]}_latest20.txt"
                    if saved_list.is_file():
                        print(f"已有本地链接快照（不会自动更新）：{saved_list}，可使用 -i 指定此文件。", file=sys.stderr)
                print("该链接失败，继续后续链接。", file=sys.stderr)
            if index < len(urls):
                time.sleep(2)
        if failures:
            if not base_opts["simulate"]:
                failed_file = output / "failed_urls.txt"
                failed_file.write_text("\n".join(failures) + "\n", encoding="utf-8")
                print(f"{len(failures)}个输入链接未完成，重试列表：{failed_file}", file=sys.stderr)
            else:
                print(f"{len(failures)}个输入链接解析失败。", file=sys.stderr)
            return 1
        print("\n解析完成。" if base_opts["simulate"] else f"\n下载完成（已下载条目会跳过）：{output}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已停止，再次运行相同命令可续传未完成的文件。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())