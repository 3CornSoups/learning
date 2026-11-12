#!/usr/bin/env python3
"""Convert local-browser report/manifest IDs to the server's plain URL list."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from douyin_server.support import video_id


def convert(source):
    data = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    rows = data.get('selected') if 'selected' in data else data.get('tasks')
    if not isinstance(rows, list):
        raise ValueError('只接受含 selected 或 tasks 列表的本地浏览器报告/任务清单')
    ids = list(dict.fromkeys(video_id(str(row['id'])) for row in rows))
    if not ids:
        raise ValueError('清单中没有作品 ID')
    return ids


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('destination', type=Path)
    args = p.parse_args()
    try:
        ids = convert(args.source)
        # Exclusive write: do not overwrite another person's task file.
        with args.destination.open('x', encoding='utf-8') as stream:
            stream.write(''.join('https://www.douyin.com/video/' + i + '\n' for i in ids))
        print(f'导出 {len(ids)} 个唯一作品 ID')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'转换失败：{type(exc).__name__}；检查输入格式和目标文件是否已存在', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
