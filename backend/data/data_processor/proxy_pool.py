"""同花顺验证式代理池。

背景:服务器机房IP会被同花顺在Nginx层封禁(403 Nginx forbidden),刷cookie无效。
本模块维护一个**经过同花顺实测验证可用**的代理池:从各代理源取候选 IP,
逐个请求同花顺板块页,只有真正能拿到板块表格(`m-table`)的代理才入池。

核心修复:旧的 `ths_client.load_proxy_pool()` 拿到 IP 后**完全不验证**,
导致 proxy.scdn.io 返回的路由器管理页等垃圾IP全部入池(实测全是垃圾)。

线程安全:复用 ths_client cookie 刷新的双重检查锁模式——持锁只做缓存二次确认 +
refreshing 标志读写,网络 I/O 在锁外执行,避免采集线程被慢刷新串行卡死。
本模块的 `_refresh_lock` 与 ths_client 的 `_ths_cookie_lock` 互相独立、不交叉持锁。
"""
import random
import threading
import time

import requests

from core.config import (
    THS_PROXY_ENABLED, THS_PROXY_VERIFY_URL, THS_PROXY_CACHE_TTL, PROXY_SOURCES,
)
from ._common import error_logger, system_logger


# 验证后的代理: [{'url': 'http://1.2.3.4:8080', 'verified_at': ts, 'source': 'name'}]
_verified = []
_refresh_lock = threading.Lock()
_refreshing = False
_last_refresh_ts = 0.0

# 候选数量上限,避免某次刷新验证太多代理拖慢采集
_MAX_CANDIDATES = 12
# 池容量上限
_MAX_POOL = 8
# 单次验证硬超时(秒):垃圾代理通常很慢,必须快速失败
_VERIFY_TIMEOUT = 8

# 拒绝名单:这些 body marker 说明代理返回的是设备/认证/同样被封的页面,不是真同花顺
_REJECT_MARKERS = (
    'nginx forbidden', 'chameleon',           # 同样被封 / 反爬挑战
    '<title>login</title>', 'router', 'modem', 'teltonika', 'mikrotik',
    'tp-link', 'wifi', 'loginpassword', 'administrator',   # 路由器/设备管理页
)


def get_verified_proxy():
    """返回一个可用的代理 URL(如 'http://1.2.3.4:8080'),或 None。

    缓存命中走快路;否则触发一次刷新(取候选→验证→缓存)。线程安全,永不抛异常。
    """
    if not THS_PROXY_ENABLED:
        return None

    global _refreshing, _last_refresh_ts

    now = time.time()
    with _refresh_lock:
        if _verified and (now - _last_refresh_ts) < THS_PROXY_CACHE_TTL:
            return random.choice(_verified)['url']   # 缓存命中
        if _refreshing:
            # 已有线程在刷新:不阻塞排队,尽量返回缓存(哪怕过期),刷新完成后下次即新值
            return _verified[-1]['url'] if _verified else None
        _refreshing = True

    # 网络 I/O 在锁外执行,避免卡住其它调用方
    try:
        candidates = _gather_candidates()
        verified = []
        for c in _dedup(candidates)[:_MAX_CANDIDATES]:
            if _verify_against_ths(c):
                verified.append({'url': c, 'verified_at': time.time()})
                if len(verified) >= _MAX_POOL:
                    break
        random.shuffle(verified)
        with _refresh_lock:
            _verified.clear()
            _verified.extend(verified)
            _last_refresh_ts = time.time()
        if verified:
            system_logger.info(
                f"代理池刷新完成:验证通过 {len(verified)} 个 "
                f"(候选 {len(candidates)} 个,来源 {len(PROXY_SOURCES)} 个)")
        else:
            system_logger.warning(
                f"代理池刷新完成:无可用代理(候选 {len(candidates)} 个均验证失败)")
        return verified[0]['url'] if verified else None
    except Exception as e:
        error_logger.error(f"代理池刷新异常: {e}")
        return None
    finally:
        with _refresh_lock:
            _refreshing = False


def mark_bad(proxy_url):
    """真实请求中该代理 403/超时,从池中移除,下次 get_verified_proxy 不再返回它。"""
    if not proxy_url:
        return
    with _refresh_lock:
        before = len(_verified)
        _verified[:] = [p for p in _verified if p['url'] != proxy_url]
        if len(_verified) != before:
            system_logger.info(f"代理 {proxy_url} 标记为不可用,已从池中移除")


def pool_status():
    """诊断用:当前池状态。"""
    with _refresh_lock:
        return {
            'enabled': THS_PROXY_ENABLED,
            'verified_count': len(_verified),
            'proxies': [p['url'] for p in _verified],
            'sources': [s.get('name') for s in PROXY_SOURCES if s.get('enabled')],
            'last_refresh': _last_refresh_ts,
            'cache_ttl': THS_PROXY_CACHE_TTL,
        }


# ────────────────── 内部实现 ──────────────────

def _gather_candidates():
    """从所有启用的代理源收集候选 IP:PORT / URL 列表。单源失败不影响其它源。"""
    candidates = []
    for source in PROXY_SOURCES:
        if not source.get('enabled'):
            continue
        try:
            got = _fetch_candidates(source)
            if got:
                candidates.extend(got)
                system_logger.info(f"代理源 [{source.get('name')}] 返回 {len(got)} 个候选")
        except Exception as e:
            error_logger.warning(f"代理源 [{source.get('name')}] 获取失败: {e}")
    return candidates


def _fetch_candidates(source):
    """按 source['kind'] 分发,解析成统一的候选列表。"""
    kind = source.get('kind')
    if kind == 'static':
        # 付费/自建代理:直接是完整 URL 列表(支持 user:pass@)
        return [str(p).strip() for p in source.get('proxies', []) if str(p).strip()]

    url = source['url']
    if kind == 'scdn':
        resp = requests.get(url, params=source.get('params', {}), timeout=10, verify=False)
        data = resp.json()
        raw = (data.get('data') or {}).get('proxies') or []
        return [_ensure_scheme(p) for p in raw if p]
    if kind == 'jhao':
        resp = requests.get(url, timeout=10, verify=False)
        try:
            data = resp.json()
            raw = data.get('proxy') if isinstance(data, dict) else None
            if not raw:
                raw = data
        except ValueError:
            raw = resp.text.strip()
        if not raw:
            return []
        # jhao 一次返回一个;也可能返回多个逗号分隔
        items = [p.strip() for p in str(raw).split(',') if p.strip()]
        return [_ensure_scheme(p) for p in items]

    error_logger.warning(f"未知代理源 kind={kind} (source={source.get('name')}),跳过")
    return []


def _ensure_scheme(proxy):
    """给裸 ip:port 补全协议前缀(优先 http,验证用 http 代理即可转发 https)。"""
    proxy = str(proxy).strip()
    if not proxy:
        return proxy
    if '://' not in proxy:
        return f'http://{proxy}'
    return proxy


def _dedup(items):
    seen = set()
    out = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _verify_against_ths(proxy_url):
    """关键验证:通过该代理请求同花顺板块页,只有真正返回板块表的才算可用。

    拒绝三类垃圾:① 连不上/超时 ② 路由器等设备页(恰好200但不是同花顺)
    ③ 同样被同花顺封的代理IP(Nginx forbidden / chameleon 挑战)。
    接受标准:status==200 且 body 含 `m-table`——这正是 parse_ths_sector_html
    定位板块表所依赖的 DOM 契约(ths_client.py:252-258)。
    """
    proxies = {'http': proxy_url, 'https': proxy_url}
    try:
        # 延迟导入避免循环依赖(proxy_pool 在 ths_client 之前被 import 时也安全)
        from .ths_client import normalize_ths_sector_headers
        resp = requests.get(
            THS_PROXY_VERIFY_URL,
            headers=normalize_ths_sector_headers(),
            proxies=proxies,
            timeout=_VERIFY_TIMEOUT,
            verify=False,
            allow_redirects=True,
        )
    except Exception:
        return False   # 连接/超时/SSL → 不可用

    if resp.status_code != 200:
        return False

    # GBK 解码(同花顺是 GBK),照搬 fetch_sector_page 的解码逻辑,避免乱码漏判
    try:
        ctype = resp.headers.get('Content-Type', '').lower()
        if 'gbk' in ctype or 'gb2312' in ctype:
            resp.encoding = 'GBK'
        elif resp.encoding == 'ISO-8859-1':
            resp.encoding = 'GBK'
        else:
            resp.encoding = resp.apparent_encoding or 'GBK'
    except Exception:
        resp.encoding = 'GBK'

    body = (resp.text or '')
    lowered = body.lower()

    if any(m in lowered for m in _REJECT_MARKERS):
        return False
    # 真正的同花顺板块表才有 m-table;这是强正向信号
    return 'm-table' in lowered
