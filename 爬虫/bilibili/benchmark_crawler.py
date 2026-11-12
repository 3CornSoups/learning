#!/usr/bin/env python3
"""运行真实抓取并保存条数、时长过滤、解析及下载耗时报告。"""
import sys
from search_random_bilibili import main
if __name__=='__main__':
    args=sys.argv[1:]
    if '--api-mode' not in args:
        args=['--api-mode',*args]
    raise SystemExit(main(args))
