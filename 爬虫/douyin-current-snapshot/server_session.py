"""Finite detached server-only sampling session with durable cycle evidence."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from douyin_crawler.config import Config
from douyin_crawler.jobs import atomic_json
from douyin_crawler.runtime import run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--cycles',type=int,default=20)
    p.add_argument('--interval',type=int,default=90)
    p.add_argument('--storage-state',type=Path)
    a=p.parse_args()
    if a.cycles<1 or a.interval<1:p.error('Positive cycles and interval required')
    state={'pid':os.getpid(),'ppid':os.getppid(),'started_utc':datetime.now(timezone.utc).isoformat(),'cycles':[],'state':'running'}
    status=a.root/'reports/browser_session.json'
    try:
        for n in range(a.cycles):
            state['current_cycle']=n+1
            state['heartbeat_utc']=datetime.now(timezone.utc).isoformat()
            atomic_json(status,state)
            config=Config(source='feed',limit=1,max_video_mb=30,max_duration=180,max_scrolls=20,login_timeout=1800,
                          browser_channel='chromium',profile_dir=a.root/'server_profile',
                          output_dir=a.root/'downloads/server_browser',state_dir=a.root/'runs/server_browser',
                          storage_state=a.storage_state if n==0 else None).validate()
            code=asyncio.run(run(config))
            state['cycles'].append({'cycle':n+1,'code':code,'ended_utc':datetime.now(timezone.utc).isoformat()})
            atomic_json(status,state)
            if code:
                state['state']='needs_attention'
                return code
            if n+1<a.cycles:time.sleep(a.interval)
        state['state']='completed'
        return 0
    finally:
        state['heartbeat_utc']=datetime.now(timezone.utc).isoformat()
        atomic_json(status,state)


if __name__=='__main__':raise SystemExit(main())
