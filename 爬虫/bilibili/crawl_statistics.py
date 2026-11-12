"""Per-run counters, monotonic timers and JSON/Markdown crawler reports."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time

TZ=timezone(timedelta(hours=8))
COUNT_LABELS={
 'source_rows':'来源读取条数（搜索返回/文件全部记录）','loaded_rows':'进入候选池条数（受pool-size限制）',
 'search_pages_requested':'搜索请求页数','search_pages_succeeded':'正常搜索页数','unique_rows':'有效去重视频数',
 'duplicate_rows':'重复记录','invalid_rows':'无效链接','archive_skipped_source':'候选阶段已下载跳过',
 'eligible_candidates':'随机排序候选数','checked_candidates':'实际检查候选数','metadata_checked':'实际解析视频信息数',
 'metadata_success':'解析成功','metadata_failed':'解析失败','too_long_source':'搜索信息已超时长跳过',
 'too_long_metadata':'解析后超时长跳过','unknown_duration':'时长未知跳过','title_skipped':'标题过滤跳过',
 'archive_skipped_metadata':'解析后已下载跳过','selected_count':'最终选中数','download_attempts':'调用下载器条数',
 'download_success':'新下载并完成处理','download_failed':'下载失败','download_skipped_archive':'下载阶段历史记录跳过',
 'download_skipped_existing':'下载阶段已有文件跳过'}
TIME_LABELS={'source_s':'搜索/读取清单耗时','selection_s':'筛选与解析总耗时（含等待）',
 'metadata_s':'其中：解析请求耗时','download_stage_s':'下载阶段总耗时（含等待/重试/合并）',
 'merge_s':'其中：合并耗时','total_s':'整个任务耗时'}

class CrawlStatistics:
    def __init__(self,reports_dir,clock=None):
        self.clock=clock or time.perf_counter
        self.started_clock=self.clock()
        now=datetime.now(TZ)
        self.run_id=now.strftime('%Y%m%d_%H%M%S_%f')
        self.reports_dir=Path(reports_dir)
        self.started_at=now.isoformat(timespec='seconds')
        self.counts={key:0 for key in COUNT_LABELS}
        self.times={key:0.0 for key in TIME_LABELS}
        self.config={}
        self.records=[]
        self.status='running'
        self.error=None
        self.completed_bytes=0
        self.lock=threading.Lock()
        self.active_download_calls=0
        self.peak_active_download_calls=0
    def inc(self,key,value=1):
        with self.lock:
            self.counts[key]=self.counts.get(key,0)+value
    def add_time(self,key,value):
        with self.lock:
            self.times[key]=self.times.get(key,0)+value
    def add_completed_bytes(self,value):
        with self.lock:
            self.completed_bytes+=value
    def download_call_started(self):
        with self.lock:
            self.active_download_calls+=1
            self.peak_active_download_calls=max(self.peak_active_download_calls,self.active_download_calls)
    def download_call_finished(self):
        with self.lock:
            self.active_download_calls-=1
    @contextmanager
    def phase(self,name):
        start=self.clock()
        try:
            yield
        finally:
            self.add_time(name,max(0.0,self.clock()-start))
    def record(self,**fields):
        row={'url':fields.pop('url',''),'id':fields.pop('id',''),'status':fields.pop('status','pending')}
        row.update(fields)
        self.records.append(row)
        return row
    def finish(self):
        self.times['total_s']=max(0.0,self.clock()-self.started_clock)
        directory=self.reports_dir/self.run_id
        directory.mkdir(parents=True,exist_ok=True)
        successful=[r for r in self.records if r.get('status')=='downloaded']
        attempts=[r for r in self.records if 'download_seconds' in r]
        last_attempt=max(attempts,key=lambda r:r.get('download_finished_task_seconds',0)) if attempts else None
        data={'schema_version':1,'run_id':self.run_id,'started_at':self.started_at,
              'finished_at':datetime.now(TZ).isoformat(timespec='seconds'),'status':self.status,'error':self.error,
              'configuration':self.config,'counts':self.counts,
              'timings_seconds':{k:round(v,6) for k,v in self.times.items()},
              'completed_file_bytes':self.completed_bytes,'completed_file_mb':round(self.completed_bytes/1024/1024,3),
              'average_successful_download_seconds':round(sum(r['download_seconds'] for r in successful)/len(successful),6) if successful else None,
              'last_download_seconds':last_attempt['download_seconds'] if last_attempt else None,
              'peak_active_download_calls':self.peak_active_download_calls,
              'videos':self.records,'report_json':str(directory/'report.json'),'report_markdown':str(directory/'report.md')}
        lines=['# B站抓取性能报告','',f'- 任务：`{self.run_id}`',f'- 状态：`{self.status}`',f'- 关键词：{self.config.get("keyword","")}',
               f'- 开始：{self.started_at}',f'- 结束：{data["finished_at"]}',f'- 单视频时长上限：{self.config.get("max_duration",300)} 秒',
               f'- 下载并发上限：{self.config.get("workers",1)}；观察到的同时下载调用峰值：{self.peak_active_download_calls}','',
               '## 数量统计','','| 指标 | 条数 |','| --- | ---: |']
        lines.extend(f'| {label} | {self.counts.get(key,0)} |' for key,label in COUNT_LABELS.items())
        lines+=['','## 时间统计','','| 阶段 | 秒 |','| --- | ---: |']
        lines.extend(f'| {label} | {self.times.get(key,0):.3f} |' for key,label in TIME_LABELS.items())
        lines+=[f'| 最后一次下载调用 | {data["last_download_seconds"] if attempts else "未执行"} |',
                f'| 成功视频平均下载耗时 | {data["average_successful_download_seconds"] if successful else "无成功下载"} |','',
                f'完成视频文件体积：{data["completed_file_mb"]} MiB。该数值是完成文件大小，不是网络流量统计。','',
                '下载阶段是墙钟时间，包含等待、重试和FFmpeg合并。并发时单条下载耗时与合并累计耗时可以重叠，不应相加为总耗时。',
                '读取数不等于实际解析数，实际解析数不等于下载成功数。已有文件和历史记录不计入新下载成功。','',
                '## 单条记录','','| 视频ID | 状态 | 视频秒数 | 解析秒数 | 下载秒数 | 合并秒数 | 文件MiB |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
        for row in self.records:
            values=[row.get('id',''),row.get('status',''),row.get('duration_seconds',''),row.get('metadata_seconds',''),row.get('download_seconds',''),row.get('merge_seconds',''),round(row.get('file_bytes',0)/1024/1024,3)]
            lines.append('| '+' | '.join(str(x).replace('|','\\|').replace('\n',' ') for x in values)+' |')
        if self.error:
            lines+=['','## 错误','',self.error]
        json_text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
        md_text='\n'.join(lines)+'\n'
        for path,text in [(directory/'report.json',json_text),(directory/'report.md',md_text),(self.reports_dir/'latest.json',json_text),(self.reports_dir/'latest.md',md_text)]:
            temp=path.with_name(path.name+'.'+self.run_id+'.tmp')
            temp.write_text(text,encoding='utf-8')
            temp.replace(path)
        print('\n===== 抓取统计 =====',flush=True)
        print(f'状态：{self.status}；读取 {self.counts["source_rows"]} 条，候选池 {self.counts["loaded_rows"]} 条，实际检查 {self.counts["checked_candidates"]} 条，解析 {self.counts["metadata_checked"]} 条',flush=True)
        print(f'超过时长跳过 {self.counts["too_long_source"]+self.counts["too_long_metadata"]} 条；时长未知 {self.counts["unknown_duration"]} 条；新下载成功 {self.counts["download_success"]} 条；下载失败 {self.counts["download_failed"]} 条',flush=True)
        print(f'搜索/读取 {self.times["source_s"]:.3f}s；筛选解析 {self.times["selection_s"]:.3f}s；下载阶段 {self.times["download_stage_s"]:.3f}s（合并 {self.times["merge_s"]:.3f}s）；总耗时 {self.times["total_s"]:.3f}s',flush=True)
        print(f'完整报告：{directory / "report.md"}',flush=True)
        return data

class DownloadObservation:
    def __init__(self,stats):
        self.stats=stats
        self.had_transfer=False
        self.files=[]
        self.merge_seconds=0.0
        self.merging={}
    def progress(self,event):
        if event.get('status')=='downloading':
            self.had_transfer=True
    def post(self,filename):
        path=Path(filename)
        if path.is_file() and path.stat().st_size>0:
            self.files.append(path)
    def postprocessor(self,event):
        name=event.get('postprocessor','')
        if 'Merger' not in name:
            return
        key=(name,(event.get('info_dict') or {}).get('id'))
        if event.get('status')=='started':
            self.merging[key]=self.stats.clock()
        elif event.get('status')=='finished' and key in self.merging:
            self.merge_seconds+=max(0.0,self.stats.clock()-self.merging.pop(key))
    def close(self):
        now=self.stats.clock()
        self.merge_seconds+=sum(max(0.0,now-start) for start in self.merging.values())
        self.merging.clear()
        self.stats.add_time('merge_s',self.merge_seconds)
        return sum(p.stat().st_size for p in set(self.files) if p.is_file())
