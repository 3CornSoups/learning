#!/usr/bin/env python3
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
from f2.apps.douyin.handler import DouyinHandler
from download_douyin import COOKIE

def parse_args():
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
    url = url.strip()
    if not url:
        return None
        
    parsed = urllib.parse.urlparse(url)
    
    # Pattern 1: modal_id in query params
    query = urllib.parse.parse_qs(parsed.query)
    if 'modal_id' in query:
        return query['modal_id'][0]
        
    # Pattern 2: /video/aweme_id or /note/aweme_id in path
    match = re.search(r'/(?:video|note)/(\d+)', parsed.path)
    if match:
        return match.group(1)
        
    # Pattern 3: Share short links or others (can extract raw digits if present)
    if url.isdigit():
        return url
        
    return None

def sanitize_filename(name):
    """Sanitize description/nickname to be safe for filenames."""
    # Replace invalid filename characters with underscore
    sanitized = re.sub(r'[\\/*?:"<>| \t\n\r#]', '_', name)
    return sanitized[:80]

async def download_file(client, url, filepath):
    """Download a file with retry, headers, and progress-optimized chunk size."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }
    
    tmp_filepath = filepath.with_suffix(filepath.suffix + ".tmp")
    
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
    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        print(f"[Warning] Could not extract video ID from URL: {url}")
        return False
        
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
                    
    async with semaphore:
        try:
            res = await handler.fetch_one_video(aweme_id)
            if not res or not res.nickname:
                print(f"[Error] Failed to fetch metadata for ID: {aweme_id}")
                return False
                
            nickname = sanitize_filename(res.nickname)
            desc = sanitize_filename(res.desc or "untitled")
            
            video_addrs = getattr(res, "video_play_addr", None)
            
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
    
    kwargs = {
        'cookie': COOKIE,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Referer': 'https://www.douyin.com/'
        }
    }
    
    handler = DouyinHandler(kwargs)
    handler.enable_bark = False
    semaphore = asyncio.Semaphore(args.concurrency)
    
    # Increase network connection limits and pool sizes for high-performance downloading
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    async with httpx.AsyncClient(limits=limits, verify=False) as client:
        tasks = [process_url(semaphore, client, url, handler, output_dir) for url in urls]
        
        print(f"Starting downloads with concurrency = {args.concurrency}...")
        results = []
        for fut in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Downloading"):
            res = await fut
            results.append(res)
            
    success_count = sum(1 for r in results if r)
    print("\n==========================================")
    print("Download completed!")
    print(f"Total URLs loaded: {len(urls)}")
    print(f"Successfully downloaded: {success_count}")
    print(f"Failed: {len(urls) - success_count}")
    print(f"Output files saved to: {output_dir.resolve()}")
    print("==========================================")

if __name__ == "__main__":
    asyncio.run(main())
