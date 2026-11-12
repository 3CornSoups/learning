import asyncio
import os
import httpx
import argparse
from pathlib import Path
from f2.apps.douyin.crawler import DouyinCrawler
from f2.apps.douyin.model import UserPost

def load_cookie():
    cookie_path = os.path.join(os.path.dirname(__file__), "cookie.txt")
    if os.path.exists(cookie_path):
        with open(cookie_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

COOKIE = load_cookie()

async def download_video(client, url, filepath):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }
    try:
        async with client.stream("GET", url, headers=headers) as r:
            if r.status_code == 200:
                with open(filepath, "wb") as f:
                    async for chunk in r.aiter_bytes():
                        f.write(chunk)
                print(f"Successfully downloaded: {os.path.basename(filepath)}")
                return True
            else:
                print(f"Failed to download {os.path.basename(filepath)}, status code: {r.status_code}")
    except Exception as e:
        print(f"Error downloading {os.path.basename(filepath)}: {e}")
    return False

async def main():
    parser = argparse.ArgumentParser(description="Download all posts/videos of a Douyin user.")
    parser.add_argument(
        "-u", "--sec-user-id",
        type=str,
        default="MS4wLjABAAAASyrX-xbox2Da_NzeOfYepzLCVJ93KvFvij5PEHzDqaRf3GBuEsU5eMT9NpJoN3O9",
        help="The sec_user_id or user homepage URL (including v.douyin.com share links) of the Douyin user to crawl."
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=str(Path(__file__).parent / "douyin_videos"),
        help="Directory to save downloaded videos."
    )
    args = parser.parse_args()
    
    sec_user_id = args.sec_user_id
    output_dir = args.output_dir

    if not output_dir or not output_dir.strip():
        print("Error: --output-dir (-o) cannot be empty.")
        return

    # Resolve sec_user_id from URL if a URL is provided
    if sec_user_id.startswith("http://") or sec_user_id.startswith("https://") or "douyin.com" in sec_user_id:
        from f2.apps.douyin.utils import SecUserIdFetcher
        print(f"Resolving sec_user_id from URL/Link: {sec_user_id} ...")
        try:
            sec_user_id = await SecUserIdFetcher.get_sec_user_id(sec_user_id)
            print(f"Successfully resolved sec_user_id: {sec_user_id}")
        except Exception as e:
            print(f"Error resolving sec_user_id: {e}")
            return

    os.makedirs(output_dir, exist_ok=True)
    kwargs = {
        "cookie": COOKIE,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            "Referer": f"https://www.douyin.com/user/{sec_user_id}",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    }
    crawler = DouyinCrawler(kwargs)
    
    max_cursor = 0
    has_more = True
    videos_found = []
    
    print("Starting post fetch...")
    while has_more:
        params = UserPost(
            max_cursor=max_cursor,
            count=20,
            sec_user_id=sec_user_id,
            browser_name="Chrome",
            browser_version="143.0.0.0",
            engine_version="143.0.0.0"
        )
        print(f"Fetching posts with max_cursor = {max_cursor}...")
        try:
            res = await crawler.fetch_user_post(params)
            if not res:
                print("Response is empty!")
                break
            
            aweme_list = res.get("aweme_list", [])
            print(f"Found {len(aweme_list)} videos in this batch.")
            if not aweme_list:
                print("Batch is empty. Stopping.")
                break
            
            for item in aweme_list:
                aweme_id = item.get("aweme_id")
                desc = item.get("desc", "").replace("/", "_").replace("\\", "_").strip()
                if not desc:
                    desc = f"video_{aweme_id}"
                
                aweme_type = item.get("aweme_type")
                if aweme_type == 68: # Image Album
                    images = item.get("images", [])
                    img_urls = []
                    for img in images:
                        img_url_list = img.get("url_list", [])
                        if img_url_list:
                            img_urls.append(img_url_list[0])
                    
                    video = item.get("video", {})
                    play_addr = video.get("play_addr", {})
                    music_url_list = play_addr.get("url_list", [])
                    music_url = music_url_list[0] if music_url_list else None
                    
                    videos_found.append({
                        "is_album": True,
                        "aweme_id": aweme_id,
                        "desc": desc,
                        "img_urls": img_urls,
                        "music_url": music_url
                    })
                else: # Normal video
                    video = item.get("video", {})
                    play_addr = video.get("play_addr", {})
                    url_list = play_addr.get("url_list", [])
                    if not url_list:
                        play_addr = video.get("play_addr_h264", {})
                        url_list = play_addr.get("url_list", [])
                    
                    if url_list:
                        videos_found.append({
                            "is_album": False,
                            "aweme_id": aweme_id,
                            "desc": desc,
                            "url": url_list[0]
                        })
            
            has_more = res.get("has_more", False) or res.get("has_more") == 1
            max_cursor = res.get("max_cursor", 0)
            
            # Avoid infinite loop if max_cursor is not updating
            if not aweme_list or max_cursor == 0 or max_cursor is None:
                has_more = False
                
            await asyncio.sleep(2) # be gentle
        except Exception as e:
            print(f"Error fetching batch: {e}")
            break
            
    print(f"Total videos metadata found: {len(videos_found)}")
    
    if not videos_found:
        print("No videos were extracted. Exiting.")
        return
        
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []
        for i, vid in enumerate(videos_found):
            if vid.get("is_album"):
                folder_name = f"{i+1:03d}_[图集]_{vid['desc'][:50]}"
                folder_path = os.path.join(output_dir, folder_name)
                os.makedirs(folder_path, exist_ok=True)
                
                # Download images
                for img_idx, img_url in enumerate(vid["img_urls"]):
                    ext = ".webp"
                    if ".jpeg" in img_url or ".jpg" in img_url:
                        ext = ".jpeg"
                    img_path = os.path.join(folder_path, f"{img_idx+1:03d}{ext}")
                    tasks.append(download_video(client, img_url, img_path))
                    
                # Download music
                if vid["music_url"]:
                    music_path = os.path.join(folder_path, "music.mp3")
                    tasks.append(download_video(client, vid["music_url"], music_path))
            else:
                filename = f"{i+1:03d}_{vid['desc'][:50]}.mp4"
                filepath = os.path.join(output_dir, filename)
                tasks.append(download_video(client, vid["url"], filepath))
            
        # Download concurrently with a concurrency limit
        sem = asyncio.Semaphore(5)
        async def sem_download(task):
            async with sem:
                return await task
        
        await asyncio.gather(*(sem_download(t) for t in tasks))
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
