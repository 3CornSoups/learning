"""Local input, output and integrity helpers; no platform dependencies."""
from contextlib import AbstractContextManager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit, parse_qs
from .asset_refs import verify_link

ROOT = Path(__file__).resolve().parents[1]


class ValidationError(ValueError):
    """Only local, credential-free messages may use this exception."""
    pass


def video_id(value):
    value = value.strip()
    if re.fullmatch(r'\d{15,20}', value):
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('www.douyin.com', 'douyin.com'):
        raise ValueError('需要完整 douyin.com 作品链接或作品 ID；短链接请先在浏览器展开')
    candidate = (parse_qs(parsed.query).get('modal_id') or [''])[0]
    match = re.fullmatch(r'/(?:video|note)/(\d+)/?', parsed.path)
    if match:
        candidate = match[1]
    if not re.fullmatch(r'\d{15,20}', candidate):
        raise ValueError('链接中没有有效作品 ID')
    return candidate


def input_ids(path, limit=None):
    result = []
    seen = set()
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        try:
            work_id = video_id(line)
        except ValueError as exc:
            raise ValueError(f'输入文件第 {number} 行：{exc}') from None
        if work_id not in seen:
            result.append(work_id)
            seen.add(work_id)
        if limit and len(result) >= limit:
            break
    if not result:
        raise ValueError('输入文件没有可处理的作品')
    return result


def read_cookie(path):
    text = Path(path).read_text(encoding='utf-8-sig').strip()
    if text.lower().startswith('cookie:'):
        text = text.split(':', 1)[1].strip()
    if not text or any(char in text for char in ('\n', '\r', '\t', '\0')):
        raise ValueError('Cookie 应为 UTF-8 单行请求头值，不能是 JSON、HAR 或 Netscape 表格')
    values = {}
    for part in text.split(';'):
        if not part.strip():
            continue
        if '=' not in part:
            raise ValueError('Cookie 字段格式错误；只保存 Request Headers 中 Cookie 的完整值')
        name, value = part.strip().split('=', 1)
        if not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", name):
            raise ValueError('Cookie 名称格式错误')
        values[name] = value
    if len(values) < 5:
        raise ValueError('Cookie 字段过少，可能只复制了单个字段')
    if not (values.get('UIFID') or values.get('UIFID_TEMP')):
        raise ValueError('当前 F2 适配需要同一会话中的 UIFID 或 UIFID_TEMP')
    return text, values


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def inspect_file(path, candidates=(), ffprobe=False, expected_md5=None):
    path = Path(path)
    if path.is_symlink():
        try:
            verify_link(path)
        except (ValueError, OSError, KeyError) as exc:
            raise ValidationError('媒体链接未登记、目标失效或内容改变') from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise ValidationError('文件不存在或为空')
    with path.open('rb') as stream:
        if stream.read(8)[4:8] != b'ftyp':
            raise ValidationError('文件不是预期 MP4，可能保存了验证页面或错误响应')
        stream.seek(0)
        digest = hashlib.md5()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    md5 = digest.hexdigest()
    size = path.stat().st_size
    if expected_md5 and md5 != expected_md5:
        raise ValidationError('文件散列与上次成功记录不同；请保留现场并使用新输出目录')
    source_verified = None
    if candidates:
        source_verified = any(c['md5'] == md5 and (not c.get('size') or c['size'] == size) for c in candidates)
        if not source_verified:
            raise ValidationError('文件大小或 MD5 与本次接口返回的媒体版本不匹配')
    result = {'file': str(path.resolve()), 'bytes': size, 'md5': md5,
              'source_hash_verified': source_verified, 'verification': 'header+md5'}
    if ffprobe:
        try:
            process = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                'stream=codec_type,codec_name:format=duration,size', '-of', 'json', str(path)],
                capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValidationError(f'ffprobe 无法运行：{type(exc).__name__}') from None
        try:
            probe = json.loads(process.stdout)
        except ValueError:
            raise ValidationError('ffprobe 没有返回有效媒体信息') from None
        if process.returncode or not any(s.get('codec_type') == 'video' for s in probe.get('streams', [])):
            raise ValidationError('ffprobe 校验失败或没有视频轨道')
        result.update(verification='header+md5+ffprobe', media=probe)
    return result


class OutputLock(AbstractContextManager):
    """One process per output directory. OS lock is released on process exit."""
    def __init__(self, output):
        self.path = Path(output) / '.douyin.lock'

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        if self.stream.seek(0, 2) == 0:
            self.stream.write(b' ')
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError('该输出目录已有任务运行；请使用另一个目录，不要删除锁文件') from None
        return self

    def __exit__(self, *args):
        try:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_UN)
        finally:
            self.stream.close()
