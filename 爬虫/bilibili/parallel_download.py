"""Download independent videos using isolated yt-dlp workers."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import threading
from yt_dlp.utils import DownloadError, ExtractorError
from crawl_statistics import DownloadObservation


def download_selected(selected,args,options,stats,downloader_factory,cookie_loader):
    stop=threading.Event()

    def download_one(row):
        if stop.is_set():
            row['status']='cancelled'
            return
        observer=DownloadObservation(stats)
        per_options={**options,'progress_hooks':[observer.progress],
                     'postprocessor_hooks':[observer.postprocessor],'post_hooks':[observer.post]}
        # Load Netscape cookies read-only rather than letting five downloaders
        # overwrite one cookie file when they exit. Header cookies are isolated too.
        per_options.pop('cookiefile',None)
        if args.workers>1:
            per_options.update(quiet=True,noprogress=True)
        started=stats.clock()
        called=False
        try:
            with downloader_factory(per_options) as ydl:
                if args.cookies:
                    ydl.cookiejar.load(str(args.cookies.resolve()))
                cookie_loader(ydl,args.cookie_header_file)
                saved_info=json.loads((args.info_dir/row['file']).read_text(encoding='utf-8'))
                if ydl.in_download_archive(saved_info):
                    stats.inc('download_skipped_archive')
                    row['status']='already_downloaded_at_download'
                    return
                stats.inc('download_attempts')
                row['download_started_task_seconds']=round(max(0.0,stats.clock()-stats.started_clock),6)
                called=True
                stats.download_call_started()
                print(f'DOWNLOAD_START {row["id"]}',flush=True)
                code=ydl.download_with_info_file(str(args.info_dir/row['file']))
            completed_files=[str(p) for p in observer.files if p.is_file()]
            if code or not completed_files:
                stats.inc('download_failed')
                row['status']='download_failed'
            elif not observer.had_transfer:
                stats.inc('download_skipped_existing')
                row['status']='existing_file'
                row['output_files']=completed_files
            else:
                stats.inc('download_success')
                row['status']='downloaded'
                row['output_files']=completed_files
        except KeyboardInterrupt:
            row['status']='interrupted'
            raise
        except (DownloadError,ExtractorError,OSError,ValueError):
            stats.inc('download_failed')
            row['status']='download_failed'
        finally:
            if called:
                row['download_seconds']=round(max(0.0,stats.clock()-started),6)
                row['download_finished_task_seconds']=round(max(0.0,stats.clock()-stats.started_clock),6)
                stats.download_call_finished()
            file_bytes=observer.close()
            row['merge_seconds']=round(observer.merge_seconds,6)
            if row.get('status')=='downloaded':
                row['file_bytes']=file_bytes
                stats.add_completed_bytes(file_bytes)
            print(f'DOWNLOAD_DONE {row["id"]} {row["status"]} {row.get("download_seconds",0):.3f}s',flush=True)

    if args.workers==1:
        for row in selected:
            download_one(row)
        return
    executor=ThreadPoolExecutor(max_workers=args.workers,thread_name_prefix='bili-download')
    futures=[]
    try:
        futures=[executor.submit(download_one,row) for row in selected]
        for future in as_completed(futures):
            future.result()
    except BaseException:
        stop.set()
        for future in futures:
            future.cancel()
        raise
    finally:
        # Do not save the report while active workers can still modify its rows.
        executor.shutdown(wait=True,cancel_futures=True)
