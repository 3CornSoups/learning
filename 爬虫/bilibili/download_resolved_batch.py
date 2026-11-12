#!/usr/bin/env python3
"""Download a small resolved batch entirely on this server."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import download_bilibili as bili

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--info-dir',type=Path,default=ROOT/'work'/'resolved')
    parser.add_argument('-o','--output-dir',type=Path,default=ROOT/'bilibili_videos')
    parser.add_argument('--limit',type=bili.positive_int,default=2)
    parser.add_argument('--height',type=bili.positive_int,default=1080)
    args=parser.parse_args()
    info_dir=args.info_dir.resolve()
    manifest=json.loads((info_dir/'batch_manifest.json').read_text(encoding='utf-8'))
    entries=manifest['videos'][:args.limit]
    if not entries:
        raise ValueError('No resolved videos in manifest')
    common=bili.get_parser().parse_args(['-o',str(args.output_dir),'--height',str(args.height),'--limit',str(args.limit)])
    options=bili.make_options(common,bili.find_ffmpeg(None))
    options['socket_timeout']=20
    options['retries']=1
    args.output_dir.mkdir(parents=True,exist_ok=True)
    failures=[]
    for index,entry in enumerate(entries,1):
        info_file=(info_dir/entry['file']).resolve()
        if info_file.parent != info_dir or not info_file.is_file():
            raise ValueError('Invalid metadata file path')
        print(f'[{index}/{len(entries)}] {entry["id"]}',flush=True)
        try:
            with YoutubeDL(options) as ydl:
                code=ydl.download_with_info_file(str(info_file))
            if code:
                failures.append(entry['id'])
        except DownloadError:
            failures.append(entry['id'])
    report={'processed':len(entries),'failed':failures,'output_dir':str(args.output_dir.resolve())}
    (args.output_dir/'resolved_run_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 1 if failures else 0

if __name__=='__main__':
    raise SystemExit(main())
