#!/usr/bin/env python3
# 本脚本逐行读取作品链接，提取作品 ID，再查元数据并下载视频或图集。
# 与 download_douyin.py 的区别：这里以“作品清单”为输入，不按账号翻页。
import os
import re
import sys
import json
import httpx
import asyncio
import urllib.parse
import argparse
from pathlib import Path
from tqdm import tqdm
# f2 提供获取单条作品详情的接口；COOKIE 在导入 download_douyin 时读取。
from f2.apps.douyin.handler import DouyinHandler
from download_douyin import COOKIE

def parse_args():
    # -i 指向每行一个作品链接的文本；-o 指定保存目录；-c 控制并发数。
    parser = argparse.ArgumentParser(description="Batch download Douyin videos or image notes from a list of URLs in a txt file.")
    parser.add_argument(
        "-i", "--input-file",
        type=str,
        default=str(Path(__file__).parent / "抖音.txt"),
        help="Path to the txt file containing Douyin URLs"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="./douyin_videos",
        help="Directory to save downloaded videos"
    )
    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent downloads"
    )
    return parser.parse_args()

def extract_aweme_id(url):
    """Extract aweme_id from various Douyin URL patterns."""
    # 先去掉首尾空白，空字符串无法得到作品 ID。
    url = url.strip()
    if not url:
        return None
        
    # 将 URL 分成路径、查询参数等部分，分别尝试识别作品 ID。
    parsed = urllib.parse.urlparse(url)
    
    # Pattern 1: modal_id in query params
    query = urllib.parse.parse_qs(parsed.query)
    if 'modal_id' in query:
        return query['modal_id'][0]
        
    # Pattern 2: /video/aweme_id or /note/aweme_id in path
    match = re.search(r'/(?:video|note)/(\d+)', parsed.path)
    if match:
        return match.group(1)
        
    # 这里只接受整行都是数字的 ID；并不会解析 v.douyin.com 短链接跳转。
    # Pattern 3: Share short links or others (can extract raw digits if present)
    if url.isdigit():
        return url
        
    return None

def sanitize_filename(name):
    """Sanitize description/nickname to be safe for filenames."""
    # 替换常见非法字符并截断到 80 字符；避免作品描述被当成路径或特殊字符。
    # Replace invalid filename characters with underscore
    sanitized = re.sub(r'[\\/*?:"<>| \t\n\r#]', '_', name)
    return sanitized[:80]

async def download_file(client, url, filepath):
    """Download a file with retry, headers, and progress-optimized chunk size."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }
    
    # 先写入 .tmp 文件，下载成功后再改成目标名，减少把半成品当完成品的风险。
    tmp_filepath = filepath.with_suffix(filepath.suffix + ".tmp")
    
    # 最多尝试三次；网络异常时删除临时文件并等待一秒。
    # HTTP 错误分支本身不会执行这里异常分支中的清理。
    for attempt in range(3):
        try:
            async with client.stream("GET", url, headers=headers, timeout=60.0) as response:
                if response.status_code == 200:
                    with open(tmp_filepath, "wb") as f:
                        # Use 256KB chunks to drastically reduce Python async context switching overhead
                        async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
                    
                    if tmp_filepath.exists():
                        tmp_filepath.rename(filepath)
                    return True
                # 遇到重定向时更新地址，下一轮尝试使用新地址。
                elif response.status_code in (301, 302):
                    redirect_url = response.headers.get("Location")
                    if redirect_url:
                        url = redirect_url
                        continue
                else:
                    print(f"    [Attempt {attempt+1}] HTTP {response.status_code} for URL: {url[:60]}...")
        except Exception as e:
            print(f"    [Attempt {attempt+1}] Error: {e} for URL: {url[:60]}...")
            if tmp_filepath.exists():
                try:
                    tmp_filepath.unlink()
                except Exception:
                    pass
            await asyncio.sleep(1.0)
            
    return False

async def process_url(semaphore, client, url, handler, output_dir_path):
    """Fetch video metadata and download, with checkpoint resume skipping."""
    # 没有解析到作品 ID 就无法查询详情，当前链接记录为失败。
    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        print(f"[Warning] Could not extract video ID from URL: {url}")
        return False
        
    # 用输出文件名前缀判断是否已下载；这是跳过已有文件，不是字节级断点续传。
    # 图集只要目录非空就会跳过，无法证明每张图片都已下载成功。
    # Checkpoint check: skip already downloaded files/folders immediately
    if output_dir_path.exists():
        for p in output_dir_path.iterdir():
            if p.is_file() and p.name.startswith(f"{aweme_id}_") and p.name.endswith(".mp4"):
                print(f"  [Skipped] Video already downloaded: {p.name}")
                return True
            elif p.is_dir() and p.name.startswith(f"{aweme_id}_"):
                if any(p.iterdir()):
                    print(f"  [Skipped] Image note already downloaded: {p.name}")
                    return True
                    
    # 信号量限制同时处理的作品数；图集内部仍可能并发下载多个文件。
    async with semaphore:
        try:
            res = await handler.fetch_one_video(aweme_id)
            if not res or not res.nickname:
                print(f"[Error] Failed to fetch metadata for ID: {aweme_id}")
                return False
                
            # 处理作者名和描述，生成相对安全的文件名。
            nickname = sanitize_filename(res.nickname)
            desc = sanitize_filename(res.desc or "untitled")
            
            video_addrs = getattr(res, "video_play_addr", None)
            
            # 有视频播放地址时优先下载视频；第一个地址失败再依次尝试备用地址。
            if video_addrs and isinstance(video_addrs, list) and len(video_addrs) > 0:
                # Video type
                video_url = video_addrs[0]
                filename = f"{aweme_id}_{nickname}_{desc}.mp4"
                filepath = output_dir_path / filename
                
                print(f"Downloading Video: {filename}")
                success = await download_file(client, video_url, filepath)
                if success:
                    print(f"  [Success] Saved to {filename}")
                    return True
                else:
                    for fallback_url in video_addrs[1:]:
                        success = await download_file(client, fallback_url, filepath)
                        if success:
                            print(f"  [Success-Fallback] Saved to {filename}")
                            return True
                    print(f"  [Failed] Could not download video for ID: {aweme_id}")
                    return False
            else:
                # 没有视频地址时尝试识别图集；图片和可选音乐放进独立目录。
                # Image Note/Slide Show type
                images = getattr(res, "images", None)
                if images and isinstance(images, list):
                    note_dir = output_dir_path / f"{aweme_id}_{nickname}_{desc}"
                    note_dir.mkdir(parents=True, exist_ok=True)
                    
                    print(f"Downloading Image Note: {note_dir.name} ({len(images)} images)")
                    
                    img_tasks = []
                    for idx, img_url in enumerate(images, 1):
                        img_path = note_dir / f"image_{idx:03d}.jpg"
                        img_tasks.append(download_file(client, img_url, img_path))
                        
                    music_url = getattr(res, "music_play_url", None)
                    if music_url:
                        music_path = note_dir / "music.mp3"
                        img_tasks.append(download_file(client, music_url, music_path))
                        
                    # gather 等待所有图集下载完成；原代码只要求至少一项成功。
                    # 因此返回成功不保证图集完整，需要额外核查。
                    results = await asyncio.gather(*img_tasks)
                    if any(results):
                        print(f"  [Success] Saved image note to {note_dir.name}")
                        return True
                        
                print(f"  [Failed] Unsupported or empty work type for ID: {aweme_id}")
                return False
                
        except Exception as e:
            print(f"[ERROR] Failed processing ID {aweme_id}: {e}")
            return False

async def main():
    # 检查参数与路径，读取文本中的非空行作为待处理链接。
    args = parse_args()
    if not args.output_dir or not args.output_dir.strip():
        print("Error: --output-dir (-o) cannot be empty.")
        sys.exit(1)
        
    input_file = Path(args.input_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not input_file.exists():
        print(f"Error: Input URL file not found at {input_file.resolve()}")
        sys.exit(1)
        
    with open(input_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]
        
    print(f"Loaded {len(urls)} URLs from {input_file.name}")
    
    # 把 Cookie 和请求头传给 f2；这些参数用于查询作品详情。
    kwargs = {
        'cookie': COOKIE,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Referer': 'https://www.douyin.com/'
        }
    }
    
    # 创建详情查询器、并发控制器与 HTTP 连接池。
    handler = DouyinHandler(kwargs)
    handler.enable_bark = False
    semaphore = asyncio.Semaphore(args.concurrency)
    
    # Increase network connection limits and pool sizes for high-performance downloading
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    # 原代码设置 verify=False，会跳过 HTTPS 证书校验；此处仅说明，未修改行为。
    async with httpx.AsyncClient(limits=limits, verify=False) as client:
        tasks = [process_url(semaphore, client, url, handler, output_dir) for url in urls]
        
        print(f"Starting downloads with concurrency = {args.concurrency}...")
        results = []
        # as_completed 按任务完成顺序返回结果；tqdm 显示进度。
        for fut in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Downloading"):
            res = await fut
            results.append(res)
            
    # 汇总成功/失败数量；已存在而被跳过的项目也计入成功。
    success_count = sum(1 for r in results if r)
    print("\n==========================================")
    print("Download completed!")
    print(f"Total URLs loaded: {len(urls)}")
    print(f"Successfully downloaded: {success_count}")
    print(f"Failed: {len(urls) - success_count}")
    print(f"Output files saved to: {output_dir.resolve()}")
    print("==========================================")

# 仅直接执行脚本时运行主函数；导入该模块不会自动开始下载。
if __name__ == "__main__":
    asyncio.run(main())
