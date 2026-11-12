#!/usr/bin/env python3
"""服务器视频链接下载：编辑 bilibili_urls.txt 后运行 ./run_batch.sh。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import download_bilibili as bili
from search_random_bilibili import resolve_from_player_api, load_header_cookies

ROOT=Path(__file__).resolve().parent

def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('urls',nargs='*',help='完整B站BV视频链接或BV号')
    p.add_argument('-i','--input-file',type=Path,help='每行一个BV链接或BV号，默认bilibili_urls.txt')
    p.add_argument('--limit',type=bili.positive_int,default=20,help='最多处理前N条，默认20')
    p.add_argument('--height',type=bili.positive_int,default=1080)
    p.add_argument('--max-duration',type=bili.positive_int,default=300,help='最长秒数，默认300')
    p.add_argument('-o','--output-dir',type=Path,default=ROOT/'bilibili_videos')
    p.add_argument('--simulate',action='store_true',help='只检查视频信息，不下载')
    auth=p.add_mutually_exclusive_group()
    auth.add_argument('--cookies',type=Path,help='Netscape格式Cookie文件')
    auth.add_argument('--cookie-header-file',type=Path,help='F12中单行Cookie请求头文件')
    args=p.parse_args(argv)
    urls=[]
    for text in args.urls:
        urls.extend(bili.normalize_sources(text))
    input_file=args.input_file
    if not args.urls and input_file is None:
        input_file=ROOT/'bilibili_urls.txt'
    if input_file is not None:
        for number,line in enumerate(input_file.read_text(encoding='utf-8-sig').splitlines(),1):
            try:
                urls.extend(bili.normalize_sources(line))
            except ValueError as exc:
                raise ValueError(f'{input_file} 第{number}行：{exc}') from exc
    urls=list(dict.fromkeys(urls))[:args.limit]
    if not urls:
        raise ValueError('请先在 bilibili_urls.txt 中每行粘贴一个新视频链接或BV号，再运行 ./run_batch.sh。')
    settings=bili.get_parser().parse_args(['-o',str(args.output_dir),'--height',str(args.height)]+(['--simulate'] if args.simulate else []))
    options=bili.make_options(settings,None if args.simulate else bili.find_ffmpeg(None))
    options['http_chunk_size']=1024*1024
    options['retries']=1
    options['outtmpl']=str(args.output_dir/'by_urls'/'%(title).100B [%(id)s].%(ext)s')
    if args.cookies:
        if not args.cookies.is_file():
            raise ValueError('Cookie文件不存在')
        options['cookiefile']=str(args.cookies.resolve())
    if args.cookie_header_file and not args.cookie_header_file.is_file():
        raise ValueError('Cookie请求头文件不存在')
    if not args.simulate:
        args.output_dir.mkdir(parents=True,exist_ok=True)
    failed=[]
    skipped=[]
    for index,url in enumerate(urls,1):
        print(f'[{index}/{len(urls)}] {url}',flush=True)
        try:
            with YoutubeDL(options) as ydl:
                load_header_cookies(ydl,args.cookie_header_file)
                info=resolve_from_player_api(ydl,url,None,args.height)
                if info.get('duration') is None or info['duration']>args.max_duration:
                    skipped.append(url)
                    print(f'跳过：超过{args.max_duration}秒或时长未知。可用 --max-duration 指定更长的秒数。',flush=True)
                    continue
                if args.simulate:
                    print(json.dumps({'id':info['id'],'title':info['title'],'duration':info['duration']},ensure_ascii=False),flush=True)
                else:
                    ydl.process_ie_result(info,download=True)
        except (DownloadError,ValueError) as exc:
            failed.append(url)
            print(f'该链接未完成：{exc}',file=sys.stderr)
    if args.simulate:
        print('检查完成，没有下载视频。',flush=True)
    else:
        report={'input_count':len(urls),'failed':failed,'skipped':skipped,'output_dir':str((args.output_dir/'by_urls').resolve())}
        (args.output_dir/'urls_run_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)
    return 1 if failed else 0

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError) as exc:
        print(f'错误：{exc}',file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print('已停止；重跑可续传。',file=sys.stderr)
        raise SystemExit(130)
