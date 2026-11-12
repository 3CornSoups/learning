# 本脚本按“账号主页”获取作品：先分页收集作品信息，再并发下载文件。
# asyncio 管理异步任务；httpx 负责网络请求；f2 封装抖音接口与数据格式。
import asyncio
import os
import httpx
import argparse
from pathlib import Path
from f2.apps.douyin.crawler import DouyinCrawler
from f2.apps.douyin.model import UserPost

def load_cookie():
    # __file__ 是当前脚本路径；Cookie 与脚本放在同一目录的 cookie.txt。
    # Cookie 相当于登录凭据，不应提交或分享。文件不存在时返回空字符串。
    cookie_path = os.path.join(os.path.dirname(__file__), "cookie.txt")
    if os.path.exists(cookie_path):
        with open(cookie_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

# 导入本模块时就会读取 Cookie；另一个按链接下载的脚本也从这里导入它。
COOKIE = load_cookie()

async def download_video(client, url, filepath):
    # async 表示此函数可以等待网络操作时让出控制权，供其他下载继续运行。
    # client 是复用的 HTTP 客户端；url 是媒体地址；filepath 是本地保存路径。
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }
    try:
        # 流式请求不必一次把整个视频读入内存，而是逐块接收并写入文件。
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
    # argparse 将命令行参数转为程序变量；这里分别接收账号和输出目录。
    # 不传 -u 时会使用代码内置的账号，并不是试运行模式。
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
    
    # sec_user_id 是抖音用户的标识，不是单个视频的 ID。
    sec_user_id = args.sec_user_id
    output_dir = args.output_dir

    if not output_dir or not output_dir.strip():
        print("Error: --output-dir (-o) cannot be empty.")
        return

    # 输入是主页或分享链接时，调用 f2 将链接解析为账号标识。
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

    # 创建输出目录，然后把 Cookie 和请求头交给 f2 的爬取器。
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
    
    # cursor 是分页游标：接口用它标识下一页；has_more 表示是否继续翻页。
    # videos_found 先暂存已解析的作品信息，之后统一安排下载。
    max_cursor = 0
    has_more = True
    videos_found = []
    
    print("Starting post fetch...")
    while has_more:
        # 每次请求一批作品；count=20 是期望每页数量，不保证返回恰好 20 条。
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
            
            # 接口结果是字典；get 的第二个参数为空值时的默认结果。
            aweme_list = res.get("aweme_list", [])
            print(f"Found {len(aweme_list)} videos in this batch.")
            if not aweme_list:
                print("Batch is empty. Stopping.")
                break
            
            # 遍历本页作品：取作品 ID 和描述，并替换描述中的路径分隔符。
            for item in aweme_list:
                aweme_id = item.get("aweme_id")
                desc = item.get("desc", "").replace("/", "_").replace("\\", "_").strip()
                if not desc:
                    desc = f"video_{aweme_id}"
                
                # 代码将类型 68 视为图集；其他类型尝试按普通视频处理。
                aweme_type = item.get("aweme_type")
                if aweme_type == 68: # Image Album
                    images = item.get("images", [])
                    img_urls = []
                    for img in images:
                        img_url_list = img.get("url_list", [])
                        if img_url_list:
                            img_urls.append(img_url_list[0])
                    
                    # 原代码把该字段的地址记作 music_url；其是否始终为音乐需结合接口实测。
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
                    # 首选播放地址缺失时，尝试备用 H.264 播放地址。
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
            
            # 根据接口返回决定继续与否，并使用新游标请求下一页。
            has_more = res.get("has_more", False) or res.get("has_more") == 1
            max_cursor = res.get("max_cursor", 0)
            
            # 仅在游标为空或为 0 时停下；代码没有比较“新旧游标是否相等”。
            # Avoid infinite loop if max_cursor is not updating
            if not aweme_list or max_cursor == 0 or max_cursor is None:
                has_more = False
                
            # 每页间隔两秒；这是异步等待，不会占住线程忙等。
            await asyncio.sleep(2) # be gentle
        except Exception as e:
            print(f"Error fetching batch: {e}")
            break
            
    print(f"Total videos metadata found: {len(videos_found)}")
    
    if not videos_found:
        print("No videos were extracted. Exiting.")
        return
        
    # 所有元数据收集完成后创建下载任务；这里一个任务对应一个媒体文件。
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []
        for i, vid in enumerate(videos_found):
            # 图集建立单独文件夹，逐张创建图片下载任务，并在有地址时下载音乐。
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
                # 普通视频保存为一个 MP4 文件；文件名来自序号和作品描述。
                filename = f"{i+1:03d}_{vid['desc'][:50]}.mp4"
                filepath = os.path.join(output_dir, filename)
                tasks.append(download_video(client, vid["url"], filepath))
            
        # Semaphore(5) 限制同一时刻进入下载函数的任务数，gather 等待所有任务结束。
        # Download concurrently with a concurrency limit
        sem = asyncio.Semaphore(5)
        async def sem_download(task):
            async with sem:
                return await task
        
        await asyncio.gather(*(sem_download(t) for t in tasks))
    print("Done!")

# 直接运行本文件时启动事件循环；被另一个脚本 import 时不会执行 main。
if __name__ == "__main__":
    asyncio.run(main())
