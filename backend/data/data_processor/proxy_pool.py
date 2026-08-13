"""同花顺验证式代理池 —— 粘性使用 + 冷却复用 + 持久化。

背景:服务器机房IP会被同花顺在Nginx层封禁(403 Nginx forbidden),刷cookie无效。
同花顺对代理IP的封禁往往是**短期**的,所以本模块的策略:

1. **攒代理**:每次从代理源拉 THS_PROXY_FETCH_COUNT(20)个候选,逐个验证,循环拉取
   直到攒够 THS_PROXY_TARGET_COUNT(2)个可用代理(1个主用 + 1个备用)。
2. **粘性使用**:一直用当前主用代理,直到它不能用(被同花顺封)。
3. **冷却复用**:被"封"的代理不丢弃,存进**本地冷却池**(带时间戳持久化),过
   THS_PROXY_COOLDOWN_SECONDS(10分钟)冷却期后重新验证可再次复用——因为同花顺的封禁
   常是临时的。
4. **切换备用**:主用被封 → 进冷却池 → 立即切到备用代理 → 再去攒新的备用。

验证标准(关键修复):只有真正请求同花顺能拿到板块表格(`m-table`)的代理才算可用。
旧的 load_proxy_pool 拿到IP后完全不验证,导致 proxy.scdn.io 返回的路由器/设备页等
垃圾IP全部入池。

线程安全:持锁只做缓存二次确认 + refreshing 标志读写,网络 I/O 在锁外执行。
"""
import json
import os
import random
import threading
import time

import requests

from core.config import (
    THS_PROXY_ENABLED, THS_PROXY_VERIFY_URL,
    THS_PROXY_TARGET_COUNT, THS_PROXY_COOLDOWN_SECONDS,
    PROXY_SOURCES, PROXY_POOL_DIR, PROXY_POOL_FILE, PROXY_COOLDOWN_FILE,
)
from ._common import error_logger, system_logger


# ────────────────── 运行时状态 ──────────────────
# 可用代理池: [{'url','verified_at'}] —— 主用是 [0],其余备用
_available = []
# 冷却池(被封的): [{'url','blocked_at'}] —— 持久化,过冷却期重新验证后可回 _available
_cooldown = []

_lock = threading.Lock()        # 保护 _available / _cooldown / _refreshing
_refreshing = False             # 是否正在攒代理(避免并发重复攒)

# 验证超时(秒):用 (connect, read) 元组,connect 短——死代理在连接阶段就快速失败,
# 不会卡满 read 超时。实测垃圾代理多在 connect 上超时(5s 级),短连接超时能把单次
# 验证压到 ~3s,避免攒一轮 20 个要等 90s+ 阻塞采集。
_VERIFY_TIMEOUT = (3, 5)
# 单次 _refresh 最多验证多少个候选(每个最坏 ~5s,20 个上限 ~100s 封顶,不无限验证)
_MAX_VERIFY_PER_REFRESH = 20

# 拒绝名单:这些 body marker 说明代理返回的是设备/认证/同样被封的页面,不是真同花顺
_REJECT_MARKERS = (
    'nginx forbidden', 'chameleon',          # 同样被封 / 反爬挑战
    '<title>login</title>', 'router', 'modem', 'teltonika', 'mikrotik',
    'tp-link', 'wifi', 'loginpassword', 'administrator',   # 路由器/设备管理页
)


# ────────────────── 持久化 ──────────────────

def _ensure_dir():
    try:
        os.makedirs(PROXY_POOL_DIR, exist_ok=True)
    except Exception:
        pass


def _load_persisted():
    """启动时从磁盘加载可用池和冷却池(冷却池是重点:被封的代理下次重启还能复用)。"""
    global _available, _cooldown
    try:
        if os.path.exists(PROXY_POOL_FILE):
            with open(PROXY_POOL_FILE, 'r', encoding='utf-8') as f:
                _available = [p for p in json.load(f) if isinstance(p, dict) and p.get('url')]
    except Exception as e:
        error_logger.warning(f"加载可用代理池失败: {e}")
    try:
        if os.path.exists(PROXY_COOLDOWN_FILE):
            with open(PROXY_COOLDOWN_FILE, 'r', encoding='utf-8') as f:
                _cooldown = [p for p in json.load(f) if isinstance(p, dict) and p.get('url')]
    except Exception as e:
        error_logger.warning(f"加载冷却代理池失败: {e}")
    if _available or _cooldown:
        system_logger.info(f"代理池持久化加载:可用 {len(_available)} 个,冷却 {len(_cooldown)} 个")


def _save_persisted():
    """把当前可用池+冷却池写盘。持锁状态下调用。"""
    _ensure_dir()
    try:
        with open(PROXY_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(_available, f, ensure_ascii=False)
    except Exception as e:
        error_logger.warning(f"保存可用代理池失败: {e}")
    try:
        with open(PROXY_COOLDOWN_FILE, 'w', encoding='utf-8') as f:
            json.dump(_cooldown, f, ensure_ascii=False)
    except Exception as e:
        error_logger.warning(f"保存冷却代理池失败: {e}")


_load_persisted()


# ────────────────── 公开 API ──────────────────

def get_verified_proxy():
    """返回当前主用代理 URL(粘性:一直返回同一个,直到它不能用),或 None。

    主用是 _available[0]。池空或低于目标时**异步**触发后台攒代理(不阻塞采集)——
    因为攒代理要拉取并逐个验证,免费源下可能耗时数十秒;同步阻塞会让采集线程卡死。
    本次无可用代理时返回 None(调用方回退直连),后台攒到后下一轮窗口即可用上代理。
    保证本地始终追求 1个在用 + 1个备选。线程安全,永不抛异常。
    """
    if not THS_PROXY_ENABLED:
        return None

    global _refreshing

    with _lock:
        if _available:
            primary = _available[0]['url']
            # 低于目标数:异步补到 1主+1备,但本次仍立即返回主用(不阻塞采集)
            need_topup = len(_available) < THS_PROXY_TARGET_COUNT and not _refreshing
            if need_topup:
                _refreshing = True
                _spawn_topup()
            return primary
        # 池空:异步攒,不阻塞(同步等待会让采集卡数十秒)。已有线程在攒则直接返回 None。
        if _refreshing:
            return None
        _refreshing = True
        _spawn_topup()
        return None


def _spawn_topup():
    """起后台线程补充代理到目标数(异步,不阻塞调用方)。"""
    def _run():
        try:
            _refresh()
        except Exception as e:
            error_logger.error(f"代理池后台补充异常: {e}")
        finally:
            with _lock:
                global _refreshing
                _refreshing = False
    t = threading.Thread(target=_run, name='proxy-topup', daemon=True)
    t.start()


def mark_bad(proxy_url):
    """主用代理被同花顺封了(403/超时):移入冷却池,切换到下一个备用,并补足备用。

    冷却池持久化,过 THS_PROXY_COOLDOWN_SECONDS 后可重新验证复用。
    切换后若可用数低于目标,异步触发补充,保证始终有1主+1备。
    """
    if not proxy_url:
        return
    global _refreshing
    need_topup = False
    with _lock:
        before = len(_available)
        _available[:] = [p for p in _available if p['url'] != proxy_url]
        if len(_available) == before:
            return   # 本就不在可用池里,无需处理
        # 进冷却池(去重,记录封禁时刻)
        _cooldown[:] = [p for p in _cooldown if p['url'] != proxy_url]
        _cooldown.append({'url': proxy_url, 'blocked_at': time.time()})
        _save_persisted()
        nxt = _available[0]['url'] if _available else None
        # 可用数低于目标 → 需补充
        need_topup = len(_available) < THS_PROXY_TARGET_COUNT and not _refreshing
        if need_topup:
            _refreshing = True
    if nxt:
        system_logger.info(f"代理 {proxy_url} 被封,移入冷却池,切换到备用 {nxt}")
    else:
        system_logger.info(f"代理 {proxy_url} 被封,移入冷却池,无备用代理(同步触发重新攒)")
    # 切换后低于目标 → 异步补充(不阻塞本次调用)
    if need_topup:
        _spawn_topup()


def pool_status():
    """诊断用:当前池状态(供健康检查/诊断脚本)。"""
    with _lock:
        return {
            'enabled': THS_PROXY_ENABLED,
            'available': [p['url'] for p in _available],
            'available_count': len(_available),
            'cooldown': [{'url': p['url'], 'blocked_at': p['blocked_at']} for p in _cooldown],
            'cooldown_count': len(_cooldown),
            'sources': [s.get('name') for s in PROXY_SOURCES if s.get('enabled')],
        }


# ────────────────── 内部:攒代理 ──────────────────

def _refresh():
    """攒够可用代理:先回收冷却池里到期的,不够再从源拉取+验证。

    目标 THS_PROXY_TARGET_COUNT 个。本次最多验证 _MAX_VERIFY_PER_REFRESH 个候选,
    保证单次刷新有界(最坏~100s),不无限验证免费源的垃圾IP。
    """
    now = time.time()

    # 1) 先尝试回收冷却池里到期的代理(过冷却期且重新验证通过的可复用)
    _reclaim_cooldown(now)

    with _lock:
        if len(_available) >= THS_PROXY_TARGET_COUNT:
            return   # 已够,无需拉取

    # 2) 从源拉取候选 + 验证,直到攒够或达到本次验证上限(_MAX_VERIFY_PER_REFRESH)。
    # 不无限重试:免费源大量垃圾,验证上限保证单次刷新有界(最坏~100s),不拖死采集。
    tried = set()
    fetched_any = False
    verified_count = 0
    with _lock:
        if len(_available) >= THS_PROXY_TARGET_COUNT:
            return
    candidates = _gather_candidates()
    fresh = [c for c in candidates if c not in tried]
    fetched_any = bool(fresh)
    for c in fresh:
        if verified_count >= _MAX_VERIFY_PER_REFRESH:
            break   # 本次刷新验证上限到了,剩下的下次再验
        with _lock:
            if len(_available) >= THS_PROXY_TARGET_COUNT:
                break
        tried.add(c)
        verified_count += 1
        if _verify_against_ths(c):
            with _lock:
                # 再次确认未超目标(并发下可能已被加)
                if len([p for p in _available if p['url'] != c]) < THS_PROXY_TARGET_COUNT:
                    _available[:] = [p for p in _available if p['url'] != c]
                    _available.append({'url': c, 'verified_at': now})
                    _save_persisted()
                    system_logger.info(
                        f"验证通过新代理 {c}(可用池 {len(_available)}/{THS_PROXY_TARGET_COUNT})")

    with _lock:
        if not _available:
            lvl = system_logger.warning if fetched_any else system_logger.info
            lvl(f"代理池刷新完成:未攒到可用代理(已试 {len(tried)} 个候选)")
        else:
            system_logger.info(f"代理池就绪:可用 {len(_available)} 个(主用 {_available[0]['url']})")


def _reclaim_cooldown(now):
    """回收冷却池里过冷却期的代理:重新验证,通过则回可用池,否则继续冷却。"""
    with _lock:
        expired = [p for p in _cooldown if (now - p.get('blocked_at', 0)) >= THS_PROXY_COOLDOWN_SECONDS]
    if not expired:
        return
    for p in expired:
        url = p['url']
        if _verify_against_ths(url):
            with _lock:
                _cooldown[:] = [c for c in _cooldown if c['url'] != url]
                if not any(a['url'] == url for a in _available):
                    _available.append({'url': url, 'verified_at': now})
                _save_persisted()
            system_logger.info(f"冷却代理 {url} 过期且重新验证通过,已回可用池")
        else:
            # 还是不行:刷新 blocked_at,继续冷却(避免反复验证同一个坏代理)
            with _lock:
                for c in _cooldown:
                    if c['url'] == url:
                        c['blocked_at'] = now
                _save_persisted()


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
        except Exception as e:
            error_logger.warning(f"代理源 [{source.get('name')}] 获取失败: {e}")
    return candidates


def _fetch_candidates(source):
    """按 source['kind'] 分发,解析成统一的候选列表。"""
    kind = source.get('kind')
    if kind == 'static':
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


def _verify_against_ths(proxy_url):
    """关键验证:通过该代理请求同花顺板块页,只有真正返回板块表的才算可用。

    拒绝三类垃圾:① 连不上/超时 ② 路由器等设备页(恰好200但不是同花顺)
    ③ 同样被同花顺封的代理IP(Nginx forbidden / chameleon 挑战)。
    接受标准:status==200 且 body 含 `m-table`——这正是 parse_ths_sector_html
    定位板块表所依赖的 DOM 契约(ths_client.py:252-258)。
    """
    proxies = {'http': proxy_url, 'https': proxy_url}
    try:
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
        return False

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
    return 'm-table' in lowered
