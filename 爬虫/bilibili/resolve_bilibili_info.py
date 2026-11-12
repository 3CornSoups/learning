#!/usr/bin/env python3
"""Resolve a small public Bilibili batch to portable yt-dlp info files; do not download media."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from yt_dlp import YoutubeDL
from yt_dlp.extractor.bilibili import BilibiliBaseIE


def prefer_backup_cdns(value):
    if isinstance(value, dict):
        if 'baseUrl' in value or 'base_url' in value:
            backups=value.get('backupUrl') or value.get('backup_url') or []
            if isinstance(backups,str):
                backups=[backups]
            reliable=[]
            for url in backups:
                parsed=urlsplit(url)
                host=(parsed.hostname or '').lower()
                if parsed.scheme == 'https' and host.endswith('.bilivideo.com') and parsed.port in (None,443):
                    reliable.append(url)
            if reliable:
                for key in ('baseUrl','base_url'):
                    if key in value:
                        value[key]=reliable[0]
        for child in value.values():
            prefer_backup_cdns(child)
    elif isinstance(value,list):
        for child in value:
            prefer_backup_cdns(child)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('-i','--input-file',type=Path,required=True)
    p.add_argument('--info-dir',type=Path,required=True)
    p.add_argument('--limit',type=int,default=2)
    args=p.parse_args()
    if args.limit < 1:
        p.error('--limit must be positive')
    urls=[line.strip() for line in args.input_file.read_text(encoding='utf-8-sig').splitlines() if line.strip() and not line.lstrip().startswith('#')][:args.limit]
    if not urls:
        p.error('No video URLs in input file')
    args.info_dir.mkdir(parents=True,exist_ok=True)
    original=BilibiliBaseIE.extract_formats
    def patched(self,play_info):
        prefer_backup_cdns(play_info)
        return original(self,play_info)
    BilibiliBaseIE.extract_formats=patched
    options={'quiet':True,'skip_download':True,'noplaylist':True,'cachedir':False,'socket_timeout':30,'sleep_interval_requests':1,'format':'bestvideo[height<=?1080]+bestaudio/best[height<=?1080]'}
    manifest=[]
    try:
        with YoutubeDL(options) as ydl:
            for url in urls:
                info=ydl.extract_info(url,download=False)
                video_id=info['id']
                if not video_id.replace('_','').isalnum():
                    raise ValueError('Unsafe video ID')
                filename=f'{video_id}.info.json'
                (args.info_dir/filename).write_text(json.dumps(ydl.sanitize_info(info),ensure_ascii=False),encoding='utf-8')
                manifest.append({'id':video_id,'url':url,'file':filename})
                hosts=[urlsplit(f['url']).hostname for f in info.get('requested_formats',[])]
                print(video_id,'metadata only; media hosts:',','.join(hosts),flush=True)
        (args.info_dir/'batch_manifest.json').write_text(json.dumps({'videos':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        BilibiliBaseIE.extract_formats=original
    return 0


if __name__=='__main__':
    raise SystemExit(main())
