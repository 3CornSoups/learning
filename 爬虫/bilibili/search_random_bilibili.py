#!/usr/bin/env python3
"""Search Bilibili, sample a small random batch, and download or export metadata only."""
from __future__ import annotations
import argparse
import html
import math
from http.cookiejar import Cookie
from http.cookies import SimpleCookie
import json
from pathlib import Path
import random
import re
import sys
import time
from yt_dlp import YoutubeDL
from yt_dlp.extractor.bilibili import BilibiliBaseIE, BiliBiliIE
from yt_dlp.utils import DownloadError, ExtractorError
import download_bilibili as bili
from resolve_bilibili_info import prefer_backup_cdns
from crawl_statistics import CrawlStatistics
from parallel_download import download_selected

ROOT=Path(__file__).resolve().parent

def load_header_cookies(ydl,path):
    if not path:
        return
    text=path.read_text(encoding='utf-8-sig').strip()
    if text.lower().startswith('cookie:'):
        text=text.split(':',1)[1].strip()
    if '\n' in text or '\r' in text:
        raise ValueError('Cookie header file must contain only the Cookie value on one line')
    parsed=SimpleCookie()
    parsed.load(text)
    if not parsed:
        raise ValueError('No cookies found in header file')
    for name,morsel in parsed.items():
        ydl.cookiejar.set_cookie(Cookie(0,name,morsel.value,None,False,'.bilibili.com',True,True,'/',True,True,None,True,None,None,{},False))
    print('Loaded Bilibili cookies from file (values hidden).',flush=True)

def archived_ids(path):
    if not path.is_file():
        return set()
    return {line.split(maxsplit=1)[-1].lower() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()}


def resolve_from_player_api(ydl,url,preferred_title,height):
    match=re.search(r'/video/(BV[0-9A-Za-z]{10})',url)
    if not match:
        raise ValueError('API mode requires a BV video URL')
    bvid=match.group(1)
    ie=BiliBiliIE(ydl)
    headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/','Origin':'https://www.bilibili.com'}
    response=ie._download_json('https://api.bilibili.com/x/player/pagelist',bvid,query={'bvid':bvid,'jsonp':'jsonp'},headers=headers)
    if response.get('code')!=0 or not response.get('data'):
        raise ValueError('No publicly accessible video page information')
    page=response['data'][0]
    playback=ie._download_playinfo(bvid,page['cid'],headers=headers,query={'try_look':1,'fourk':1,'fnver':0})
    prefer_backup_cdns(playback)
    duration=(playback.get('timelength') or 0)/1000 or page.get('duration')
    info={'id':bvid,'title':preferred_title or page.get('part') or bvid,'duration':duration,'formats':ie.extract_formats(playback),'webpage_url':url,'extractor':'BiliBili','extractor_key':'BiliBili','http_headers':{**headers,'Range':'bytes=0-'}}
    return ydl.process_ie_result(info,download=False)


class SearchVerificationRequired(RuntimeError):
    pass


def fetch_live_search(ydl,keyword,pool_size,stats=None):
    ie=BiliBiliIE(ydl)
    rows=[]
    for page in range(1,(pool_size+19)//20+1):
        if stats:
            stats.inc('search_pages_requested')
        query={'search_type':'video','keyword':keyword,'page':page,'page_size':20,'order':'totalrank'}
        try:
            response=ie._download_json('https://api.bilibili.com/x/web-interface/wbi/search/type',keyword,query=ie._sign_wbi(query,keyword),headers={'User-Agent':'Mozilla/5.0','Referer':'https://search.bilibili.com/','Origin':'https://search.bilibili.com'})
        except ExtractorError as exc:
            raise SearchVerificationRequired('实时搜索请求未能通过。无Cookie时，请在浏览器搜索新关键词并导出TXT，用 --candidates-file 指定；不会自动使用旧清单。') from exc
        data=response.get('data') or {}
        if data.get('v_voucher') or response.get('code') in (-352,-412,-401):
            raise SearchVerificationRequired('B站要求验证，匿名实时搜索被拦截。请在浏览器搜索后导出TXT，并加 --candidates-file 文件名.txt；程序没有使用任何固定关键词缓存。')
        if response.get('code') != 0:
            raise ValueError(f'搜索接口返回错误码：{response.get("code")}')
        batch=data.get('result') or []
        if stats:
            stats.inc('search_pages_succeeded')
            stats.inc('source_rows',len(batch))
        if not batch:
            break
        for item in batch:
            bvid=item.get('bvid')
            url=f'https://www.bilibili.com/video/{bvid}/' if bvid else item.get('arcurl')
            if not url:
                continue
            duration=item.get('duration')
            if isinstance(duration,str) and re.fullmatch(r'\d+(?::\d+){1,2}',duration):
                seconds=0
                for part in duration.split(':'):
                    seconds=seconds*60+int(part)
                duration=seconds
            elif not isinstance(duration,(int,float)):
                duration=None
            rows.append({'url':url,'title':html.unescape(re.sub(r'<[^>]*>','',item.get('title') or '')),'duration':duration})
            if len(rows)>=pool_size:
                return rows
        time.sleep(1)
    return rows


def read_candidate_file(path,keyword,pool_size,stats=None):
    text=path.read_text(encoding='utf-8-sig')
    if path.suffix.lower()=='.json':
        snapshot=json.loads(text)
        if snapshot.get('keyword') and snapshot['keyword'] != keyword:
            raise ValueError('候选文件里的关键词与本次输入不一致')
        if stats:
            stats.inc('source_rows',len(snapshot['candidates']))
        return snapshot['candidates'][:pool_size]
    rows=[]
    for number,line in enumerate(text.splitlines(),1):
        try:
            rows.extend({'url':url} for url in bili.normalize_sources(line))
        except ValueError as exc:
            raise ValueError(f'候选TXT第{number}行：{exc}') from exc
    if stats:
        stats.inc('source_rows',len(rows))
    return rows[:pool_size]

def build_parser():
    p=argparse.ArgumentParser(description='按关键词随机抓取B站视频，并统计条数和各阶段耗时。')
    p.add_argument('keyword',nargs='?')
    p.add_argument('--pool-size',type=bili.positive_int,default=100)
    p.add_argument('--candidates-file',type=Path)
    p.add_argument('--api-mode',action='store_true')
    p.add_argument('--count',type=bili.positive_int,default=20)
    p.add_argument('--workers',type=bili.positive_int,default=5,help='同时下载视频数，默认5，最大5；搜索与解析仍按顺序执行')
    p.add_argument('--seed',type=int)
    p.add_argument('--max-duration',type=bili.positive_int,default=300,help='单视频最大秒数，默认300（5分钟）')
    p.add_argument('--max-checks',type=bili.positive_int)
    p.add_argument('--title-contains')
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--search-only',action='store_true')
    mode.add_argument('--resolve-only',action='store_true')
    p.add_argument('--height',type=bili.positive_int,default=1080)
    p.add_argument('--info-dir',type=Path,default=ROOT/'work'/'search_resolved')
    p.add_argument('-o','--output-dir',type=Path,default=ROOT/'bilibili_videos')
    p.add_argument('--archive-file',type=Path)
    p.add_argument('--reports-dir',type=Path,default=ROOT/'reports')
    auth=p.add_mutually_exclusive_group()
    auth.add_argument('--cookies',type=Path)
    auth.add_argument('--cookie-header-file',type=Path)
    return p

def _run(args,stats):
    archive=args.archive_file or args.output_dir/'downloaded.txt'
    seen=archived_ids(archive)
    common={'quiet':True,'cachedir':False,'socket_timeout':20,'sleep_interval_requests':1,'retries':1}
    if args.cookies:
        if not args.cookies.is_file():
            raise ValueError('Cookie文件不存在')
        common['cookiefile']=str(args.cookies.resolve())
    if args.cookie_header_file and not args.cookie_header_file.is_file():
        raise ValueError('Cookie请求头文件不存在')
    with stats.phase('source_s'):
        if args.candidates_file:
            rows=read_candidate_file(args.candidates_file,args.keyword,args.pool_size,stats=stats)
        else:
            with YoutubeDL({**common,'extract_flat':True,'skip_download':True}) as ydl:
                load_header_cookies(ydl,args.cookie_header_file)
                rows=fetch_live_search(ydl,args.keyword,args.pool_size,stats=stats)
    stats.counts['loaded_rows']=len(rows)
    args.info_dir.mkdir(parents=True,exist_ok=True)
    if args.search_only:
        (args.info_dir/'search_candidates.json').write_text(json.dumps({'keyword':args.keyword,'candidates':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        stats.status='search_only'
        return 0
    selected=[]
    with stats.phase('selection_s'):
        candidates=[]
        unique=set()
        for row in rows:
            url=row.get('url') or row.get('webpage_url') or ''
            match=re.search(r'/video/(BV[0-9A-Za-z]{10}|av\d+)',url,re.I)
            if not match:
                stats.inc('invalid_rows')
                continue
            key=match.group(1).lower()
            if key in unique:
                stats.inc('duplicate_rows')
                continue
            unique.add(key)
            if key in seen or f'{key}_p1' in seen:
                stats.inc('archive_skipped_source')
                stats.record(url=url,id=match.group(1),status='already_downloaded')
                continue
            candidates.append({**row,'url':url,'id':match.group(1)})
        stats.counts['unique_rows']=len(unique)
        stats.counts['eligible_candidates']=len(candidates)
        rng=random.Random(args.seed) if args.seed is not None else random.SystemRandom()
        rng.shuffle(candidates)
        original=BilibiliBaseIE.extract_formats
        def patched(self,play_info):
            prefer_backup_cdns(play_info)
            return original(self,play_info)
        BilibiliBaseIE.extract_formats=patched
        try:
            with YoutubeDL({**common,'noplaylist':True,'skip_download':True,'format':f'bestvideo[height<=?{args.height}]+bestaudio/best[height<=?{args.height}]'}) as ydl:
                load_header_cookies(ydl,args.cookie_header_file)
                for candidate in candidates[:(args.max_checks or args.pool_size)]:
                    if len(selected)>=args.count:
                        break
                    stats.inc('checked_candidates')
                    url=candidate['url']
                    row=stats.record(url=url,id=candidate['id'],title=candidate.get('title') or '',status='checking')
                    duration=candidate.get('duration')
                    if isinstance(duration,(int,float)) and math.isfinite(duration) and duration>args.max_duration:
                        stats.inc('too_long_source')
                        row.update(status='too_long_search',duration_seconds=duration)
                        continue
                    stats.inc('metadata_checked')
                    started=stats.clock()
                    try:
                        info=resolve_from_player_api(ydl,url,candidate.get('title'),args.height) if args.api_mode else ydl.extract_info(url,download=False)
                    except (DownloadError,ExtractorError,ValueError) as exc:
                        stats.inc('metadata_failed')
                        row['status']='metadata_failed'
                        if any(marker in str(exc) for marker in ['HTTP Error 412','(352)','(401)']):
                            raise SearchVerificationRequired('播放信息接口要求验证，本次停止继续请求。') from exc
                        continue
                    finally:
                        elapsed=max(0.0,stats.clock()-started)
                        stats.times['metadata_s']+=elapsed
                        row['metadata_seconds']=round(elapsed,6)
                    stats.inc('metadata_success')
                    video_id=info['id']
                    duration=info.get('duration')
                    row.update(id=video_id,title=info.get('title',''),duration_seconds=duration if isinstance(duration,(int,float)) and math.isfinite(duration) else None)
                    if args.title_contains and args.title_contains not in info.get('title',''):
                        stats.inc('title_skipped')
                        row['status']='title_filtered'
                        continue
                    if video_id.lower() in seen:
                        stats.inc('archive_skipped_metadata')
                        row['status']='already_downloaded'
                        continue
                    if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0:
                        stats.inc('unknown_duration')
                        row['status']='unknown_duration'
                        continue
                    if duration>args.max_duration:
                        stats.inc('too_long_metadata')
                        row['status']='too_long_metadata'
                        continue
                    if not re.fullmatch(r'[0-9A-Za-z_\-]+',video_id):
                        raise ValueError('Invalid video ID')
                    filename=f'{video_id}.info.json'
                    (args.info_dir/filename).write_text(json.dumps(ydl.sanitize_info(info),ensure_ascii=False),encoding='utf-8')
                    row.update(status='selected',file=filename)
                    selected.append(row)
                    stats.inc('selected_count')
                    print('SELECTED',json.dumps({k:row[k] for k in ['id','title','duration_seconds']},ensure_ascii=False),flush=True)
                    time.sleep(1)
        finally:
            BilibiliBaseIE.extract_formats=original
    manifest={'keyword':args.keyword,'candidate_count':stats.counts['eligible_candidates'],'videos':[{'id':r['id'],'url':r['url'],'file':r['file'],'title':r['title'],'duration':r['duration_seconds']} for r in selected]}
    (args.info_dir/'batch_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.resolve_only:
        stats.status='resolved_only' if selected else 'no_eligible_videos'
        return 0 if selected else 1
    if not selected:
        stats.status='no_new_candidates' if stats.counts['archive_skipped_source'] and not stats.counts['checked_candidates'] else 'no_eligible_videos'
        return 0 if stats.status=='no_new_candidates' else 1
    download_args=bili.get_parser().parse_args(['-o',str(args.output_dir),'--height',str(args.height)])
    options=bili.make_options(download_args,bili.find_ffmpeg(None))
    options.update(retries=1,http_chunk_size=1024*1024,download_archive=str(archive))
    if args.cookies:
        options['cookiefile']=str(args.cookies.resolve())
    safe_keyword=re.sub(r'[\\/:*?"<>|]','_',args.keyword)[:40]
    options['outtmpl']=str(args.output_dir/f'search_{safe_keyword}'/'%(title).100B [%(id)s].%(ext)s')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    with stats.phase('download_stage_s'):
        download_selected(selected,args,options,stats,YoutubeDL,load_header_cookies)
    failed=[r['id'] for r in selected if r['status']=='download_failed']
    (args.info_dir/'run_report.json').write_text(json.dumps({'keyword':args.keyword,'target_count':args.count,'selected':selected,'failed':failed,'statistics_run_id':stats.run_id},ensure_ascii=False,indent=2),encoding='utf-8')
    stats.status='partial' if failed or stats.counts['download_success']<args.count else 'completed'
    return 1 if failed else 0

def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    p=build_parser()
    args=p.parse_args(argv)
    if not args.keyword:
        if not sys.stdin.isatty():
            p.error('请在命令后填写关键词，或在交互终端运行后输入')
        args.keyword=input('请输入B站搜索关键词：').strip()
    args.keyword=args.keyword.strip()
    if not args.keyword:
        p.error('关键词不能为空')
    if args.pool_size>200 or args.count>args.pool_size:
        p.error('pool-size must be at most 200 and count must not exceed pool-size')
    if args.workers>5:
        p.error('workers must be between 1 and 5')
    stats=CrawlStatistics(args.reports_dir)
    stats.config={'keyword':args.keyword,'target_count':args.count,'pool_size':args.pool_size,'max_duration':args.max_duration,'max_checks':args.max_checks or args.pool_size,'height':args.height,'workers':args.workers,'source':'candidate_file' if args.candidates_file else 'live_search','mode':'search_only' if args.search_only else 'resolve_only' if args.resolve_only else 'download'}
    try:
        return _run(args,stats)
    except SearchVerificationRequired as exc:
        stats.status='blocked'
        stats.error=str(exc)
        print(f'Error: {exc}',file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        stats.status='interrupted'
        stats.error='用户中断任务'
        print('已停止，统计报告将保留。',file=sys.stderr)
        return 130
    except (ValueError,OSError,DownloadError,ExtractorError) as exc:
        stats.status='failed'
        stats.error=f'{type(exc).__name__}：任务未完成，请查看终端错误。'
        print(f'Error: {exc}',file=sys.stderr)
        return 1
    except Exception as exc:
        stats.status='failed'
        stats.error=f'未处理的错误类型：{type(exc).__name__}'
        raise
    finally:
        stats.finish()

if __name__=='__main__':
    raise SystemExit(main())
