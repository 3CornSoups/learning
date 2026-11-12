"""Help, doctor, cookie-check and dry-run never contact Douyin."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import os
from pathlib import Path
import shutil
import sys

from .support import ROOT, input_ids, read_cookie


def path(value):
    p = Path(value).expanduser()
    return (ROOT / p).resolve() if not p.is_absolute() else p.resolve()


def output_path(value):
    p = path(value)
    return p


def dependencies():
    checks = {'python_3_12': sys.version_info[:2] == (3, 12)}
    for name, wanted in [('f2', '0.0.1.7'), ('httpx', '0.27.2'), ('tqdm', '4.70.1')]:
        try:
            actual = version(name)
        except PackageNotFoundError:
            actual = 'missing'
        checks[name] = actual == wanted
    manifest = json.loads((ROOT / 'vendor/SOURCE.json').read_text(encoding='utf-8'))
    for name, expected in manifest['sha256'].items():
        checks['vendor_' + name] = hashlib.sha256((ROOT / 'vendor' / name).read_bytes()).hexdigest() == expected
    return checks


def parser():
    p = argparse.ArgumentParser(description='抖音服务器下载入口（离线自检 / Cookie / URL 批量下载）')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('doctor', 'cookie-check'):
        s = sub.add_parser(name, help='离线环境自检' if name == 'doctor' else '离线检查 Cookie 文件格式')
        s.add_argument('--cookie-file', default='auth/cookie.txt')
        if name == 'doctor':
            s.add_argument('--no-cookie', action='store_true')
    s = sub.add_parser('import-cookie', help='导入单行 Cookie 请求头；不回显内容')
    s.add_argument('--from-file', required=True)
    s.add_argument('--cookie-file', default='auth/cookie.txt')
    s.add_argument('--replace', action='store_true')
    s = sub.add_parser('download', help='下载 URL 清单；默认 5 文件并发、单连接')
    s.add_argument('-i', '--input-file', required=True)
    s.add_argument('-o', '--output-dir', default='downloads')
    s.add_argument('--cookie-file', default='auth/cookie.txt')
    s.add_argument('-c', '--concurrency', type=int, default=5)
    s.add_argument('--limit', type=int)
    s.add_argument('--segments', type=int, choices=[1, 2, 4], default=1)
    s.add_argument('--range-connections', type=int, default=12)
    s.add_argument('--verify', choices=['basic', 'ffprobe'], default='basic')
    s.add_argument('--report')
    s.add_argument('--dry-run', action='store_true', help='仅解析清单；无需 Cookie、F2，无网络、无输出文件')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    running_backend = False
    try:
        if args.command == 'import-cookie':
            text, values = read_cookie(path(args.from_file))
            dest = output_path(args.cookie_file)
            if dest.exists() and not args.replace:
                raise ValueError('目标 Cookie 已存在；确认更新时使用 --replace')
            dest.parent.mkdir(parents=True, exist_ok=True)
            temporary = dest.with_name(dest.name + f'.{os.getpid()}.tmp')
            try:
                with temporary.open('x', encoding='utf-8') as stream:
                    os.chmod(temporary, 0o600)
                    stream.write(text + '\n')
                temporary.replace(dest)
            finally:
                temporary.unlink(missing_ok=True)
            print(f'Cookie 已导入；字段数 {len(values)}，未输出任何字段值')
            return 0
        if args.command in ('doctor', 'cookie-check'):
            checks = dependencies() if args.command == 'doctor' else {}
            if not getattr(args, 'no_cookie', False):
                _, values = read_cookie(path(args.cookie_file))
                checks['cookie_format'] = True
                print(f'Cookie 格式通过，字段数 {len(values)}；有效期及接口可用性需实际请求确认')
            if args.command == 'doctor':
                print('ffprobe（可选）: ' + ('available' if shutil.which('ffprobe') else 'missing'))
            print(json.dumps(checks, ensure_ascii=False, indent=2))
            return 0 if all(checks.values()) else 2
        if args.limit is not None and args.limit <= 0:
            raise ValueError('--limit 必须大于 0')
        if not 1 <= args.concurrency <= 16 or not 1 <= args.range_connections <= 32:
            raise ValueError('文件并发范围 1–16，分段总连接范围 1–32')
        ids = input_ids(path(args.input_file), args.limit)
        if args.dry_run:
            print(json.dumps({'mode': 'dry-run', 'count': len(ids), 'ids': ids,
                              'concurrency': args.concurrency, 'segments': args.segments}, indent=2))
            return 0
        if not all(dependencies().values()):
            print('环境或原脚本校验未通过；请先执行 doctor --no-cookie', file=sys.stderr)
            return 2
        cookie, _ = read_cookie(path(args.cookie_file))
        if args.verify == 'ffprobe' and not shutil.which('ffprobe'):
            raise ValueError('未安装 ffprobe；请安装后使用此模式，或使用 --verify basic')
        output = output_path(args.output_dir)
        if output == ROOT or ROOT.is_relative_to(output):
            raise ValueError('输出需要独立子目录，不能指向项目根目录或它的上级')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        report_path = output_path(args.report or f'reports/{stamp}-{os.getpid()}.json')
        if report_path.exists() or report_path in (path(args.cookie_file), path(args.input_file)):
            raise ValueError('报告路径已存在或与输入/Cookie 冲突；请使用新的报告文件名')
        output_path(str(ROOT))
        os.chdir(ROOT)
        temporary = ROOT / '.cache/tmp'
        temporary.mkdir(parents=True, exist_ok=True)
        os.environ.update(TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
        import tempfile
        tempfile.tempdir = str(temporary)
        from .workflow import execute
        running_backend = True
        report = asyncio.run(execute(ids, cookie, output, report_path, args.concurrency,
                                     args.verify, args.segments, args.range_connections))
        print(json.dumps({k: report[k] for k in ('state', 'downloaded', 'skipped', 'failed',
              'elapsed_seconds', 'new_bytes', 'batch_MBps')}, ensure_ascii=False, indent=2))
        print(f'报告：{report_path}')
        return 1 if report['failed'] or report['pending_ids'] else 0
    except KeyboardInterrupt:
        print('任务已中断；检查 reports 中的 interrupted 报告后重试', file=sys.stderr)
        return 130
    except (ValueError, OSError) as exc:
        if running_backend:
            print(f'运行错误：{type(exc).__name__}；检查输出目录锁和任务报告', file=sys.stderr)
            return 1
        print(f'配置/本地文件错误：{exc}', file=sys.stderr)
        return 2
    except Exception as exc:
        print(f'运行异常：{type(exc).__name__}；请检查 doctor 和排障文档', file=sys.stderr)
        return 1
