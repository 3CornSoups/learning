"""F2 integration seam. The vendored original scripts remain byte-identical."""
import importlib.util
import json
import sys

from .support import ROOT

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
_installed_cookie = None


def apply_compat(cookie):
    global _installed_cookie
    if _installed_cookie is not None:
        if _installed_cookie != cookie:
            raise RuntimeError('同一进程不能切换 Cookie；请启动新任务')
        return
    from f2.apps.douyin.crawler import DouyinCrawler
    from f2.apps.douyin.model import PostDetail
    import f2.apps.douyin.handler as handler_module
    values = dict(p.strip().split('=', 1) for p in cookie.split(';') if '=' in p)
    uid = values.get('UIFID') or values.get('UIFID_TEMP', '')
    fingerprint = values.get('s_v_web_id', '')
    old_init = DouyinCrawler.__init__

    def current_init(self, kwargs):
        return old_init(self, {**kwargs, 'headers': {**kwargs.get('headers', {}),
                            'uifid': uid, 'x-tt-argus': '1'}})

    class CurrentDetail(PostDetail):
        uifid: str = uid
        verifyFp: str = fingerprint
        fp: str = fingerprint

    DouyinCrawler.__init__ = current_init
    handler_module.PostDetail = CurrentDetail
    _installed_cookie = cookie


def load_original():
    for name in ('download_douyin', 'download_by_urls'):
        path = ROOT / 'vendor' / (name + '.py')
        existing = sys.modules.get(name)
        if existing and getattr(existing, '__file__', None) == str(path):
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules['download_by_urls']


def make_backend(cookie):
    apply_compat(cookie)
    original = load_original()
    handler = original.DouyinHandler({'cookie': cookie, 'headers': {
        'User-Agent': UA, 'Referer': 'https://www.douyin.com/'}})
    handler.enable_bark = False
    return original, handler


def digest_candidates(node):
    if isinstance(node, dict):
        if node.get('file_hash'):
            yield {'md5': node['file_hash'], 'size': node.get('data_size')}
        for child in node.values():
            yield from digest_candidates(child)
    elif isinstance(node, list):
        for child in node:
            yield from digest_candidates(child)


def response_evidence(body, status):
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    work = data.get('aweme_detail') or {}
    work = work if isinstance(work, dict) else {}
    return {'status': status, 'has_detail': bool(work),
            'argus_rejection': b'ArgusSecurityPlugin' in body,
            'missing_uifid': b'Uifid Not Found' in body,
            'hashes': list(digest_candidates(work.get('video', {})))}
