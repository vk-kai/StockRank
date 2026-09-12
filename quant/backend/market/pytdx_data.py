import json
import time
import threading
import pandas as pd
import numpy as np
from pytdx.hq import TdxHq_API
from pytdx.config.hosts import hq_hosts
from typing import Optional, List, Tuple
import logging
import random
from datetime import datetime, timedelta

from backend.time_utils import now_beijing
from cachetools import TTLCache
import requests

from backend.config import (
    PYTDX_SERVERS,
    PYTDX_CATEGORY,
    PYTDX_SERVER_DISCOVERY_ENABLED,
    PYTDX_SERVER_DISCOVERY_CACHE_TTL,
    PYTDX_SERVER_PROBE_COUNT,
    PYTDX_SERVER_POOL_LIMIT,
)
from backend.paths import PYTDX_HOST_CACHE_PATH, ensure_runtime_storage_ready
from backend.security_service import get_market_code

logger = logging.getLogger(__name__)

_thread_local = threading.local()

# K线柱缓存:TTL 20s 对齐"十几秒级"的分时尾巴新鲜度;TDX 为 TCP 行情协议
# (非 HTTP),每代码每 20 秒一次拉取的频率对通达信服务器是安全的
_cache = TTLCache(maxsize=100, ttl=20)
_failed_server_cooldown = TTLCache(maxsize=64, ttl=180)
_host_pool_cache = TTLCache(maxsize=1, ttl=PYTDX_SERVER_DISCOVERY_CACHE_TTL)
_finance_cache = TTLCache(maxsize=2048, ttl=24 * 60 * 60)


def _server_key(ip: str, port: int) -> str:
    return f"{ip}:{int(port)}"


_host_stats_lock = threading.RLock()
_host_stats_cache: Optional[dict] = None
_host_stats_last_flush_ts = 0.0
_HOST_STATS_FLUSH_SECONDS = 30.0


def _read_host_stats_from_disk() -> dict:
    ensure_runtime_storage_ready()
    if not PYTDX_HOST_CACHE_PATH.exists():
        return {}
    try:
        with PYTDX_HOST_CACHE_PATH.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_host_stats() -> dict:
    """主机评分:内存缓存优先,磁盘只读一次(WS 行情循环每 3 秒都会记录结果,不能次次读写盘)。"""
    global _host_stats_cache
    with _host_stats_lock:
        if _host_stats_cache is None:
            _host_stats_cache = _read_host_stats_from_disk()
        return _host_stats_cache


def _save_host_stats(stats: dict):
    ensure_runtime_storage_ready()
    with PYTDX_HOST_CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def _record_host_result(
    ip: str,
    port: int,
    success: bool,
    latency_ms: Optional[float] = None,
    name: str = "",
    quote_success: Optional[bool] = None,
):
    """记录服务器连接和行情获取结果。

    Args:
        ip: 服务器IP
        port: 服务器端口
        success: 连接是否成功
        latency_ms: 延迟毫秒数
        name: 服务器名称
        quote_success: 行情获取是否成功（None表示未测试行情）

    结果在内存累计,最多每 _HOST_STATS_FLUSH_SECONDS 秒落盘一次(失败立即落盘)。
    """
    global _host_stats_last_flush_ts
    with _host_stats_lock:
        stats = _load_host_stats()
        key = _server_key(ip, port)
        host = stats.get(key, {})
        host.update(
            {
                "ip": ip,
                "port": int(port),
                "name": name or host.get("name", ""),
                "last_checked_at": now_beijing().replace(tzinfo=None).isoformat(timespec="seconds"),
            }
        )
        if success:
            host["success_count"] = int(host.get("success_count", 0)) + 1
            host["last_success_at"] = now_beijing().replace(tzinfo=None).isoformat(timespec="seconds")
            if latency_ms is not None:
                host["last_latency_ms"] = round(float(latency_ms), 2)
        else:
            host["fail_count"] = int(host.get("fail_count", 0)) + 1
            host["last_failed_at"] = now_beijing().replace(tzinfo=None).isoformat(timespec="seconds")

        # 记录行情获取结果
        if quote_success is True:
            host["quote_success_count"] = int(host.get("quote_success_count", 0)) + 1
            host["last_quote_success_at"] = now_beijing().replace(tzinfo=None).isoformat(timespec="seconds")
        elif quote_success is False:
            host["quote_fail_count"] = int(host.get("quote_fail_count", 0)) + 1
            host["last_quote_fail_at"] = now_beijing().replace(tzinfo=None).isoformat(timespec="seconds")

        stats[key] = host
        # 成功结果在内存累计、最多 30 秒落盘一次;失败立即落盘(换服务器评分要尽快生效)
        now_ts = now_beijing().timestamp()
        if (not success) or quote_success is False or now_ts - _host_stats_last_flush_ts >= _HOST_STATS_FLUSH_SECONDS:
            _host_stats_last_flush_ts = now_ts
            try:
                _save_host_stats(stats)
            except Exception as e:
                logger.debug(f"保存pytdx主机评分失败: {e}")


def _build_server_pool() -> List[Tuple[str, int, str]]:
    seen = set()
    servers: List[Tuple[str, int, str]] = []

    for ip, port in PYTDX_SERVERS:
        key = _server_key(ip, port)
        if key in seen:
            continue
        seen.add(key)
        servers.append((ip, int(port), "config"))

    for item in hq_hosts:
        if len(item) >= 3:
            name, ip, port = item[0], item[1], item[2]
        else:
            name, ip, port = "", item[0], item[1]
        key = _server_key(ip, port)
        if key in seen:
            continue
        seen.add(key)
        servers.append((str(ip), int(port), str(name or "pytdx_builtin")))

    return servers


def _server_score(server: Tuple[str, int, str], stats: dict) -> tuple:
    """计算服务器评分，优先选择行情获取成功率高的服务器。

    评分维度（优先级从高到低）：
    1. 行情获取成功率（quote_success_count - quote_fail_count）
    2. 配置文件中的服务器优先
    3. 连接成功率（success_count - fail_count）
    4. 延迟（越低越好）
    5. 最后成功时间（越新越好）
    """
    ip, port, source_name = server
    host = stats.get(_server_key(ip, port), {})
    latency = float(host.get("last_latency_ms", 999999))
    success_count = int(host.get("success_count", 0))
    fail_count = int(host.get("fail_count", 0))
    last_success_at = host.get("last_success_at", "")

    # 行情获取成功率
    quote_success_count = int(host.get("quote_success_count", 0))
    quote_fail_count = int(host.get("quote_fail_count", 0))

    preferred_bonus = 1 if source_name == "config" else 0

    # 行情成功率优先级最高，如果行情获取失败次数过多，直接降低评分
    quote_score = quote_success_count - quote_fail_count * 10  # 失败惩罚更重

    return (quote_score, preferred_bonus, success_count - fail_count, -latency, last_success_at)


def _probe_server(ip: str, port: int) -> Tuple[Optional[float], bool]:
    """探测服务器连接和行情获取能力。

    Returns:
        Tuple[latency_ms, quote_ok]:
        - latency_ms: 连接延迟毫秒数，None表示连接失败
        - quote_ok: 行情获取是否成功
    """
    api = TdxHq_API()
    start = time.perf_counter()
    try:
        if not api.connect(ip, port, time_out=0.7):
            return None, False
        data = api.get_security_count(0)
        if data is None:
            return None, False

        latency_ms = (time.perf_counter() - start) * 1000

        # 测试行情获取能力（使用茅台作为测试股票）
        quote_data = api.get_security_quotes([(1, "600519")])
        quote_ok = quote_data is not None and len(quote_data) > 0

        return latency_ms, quote_ok
    except Exception:
        return None, False
    finally:
        try:
            api.disconnect()
        except Exception:
            pass


def _discover_available_servers() -> List[Tuple[str, int]]:
    if "servers" in _host_pool_cache:
        return _host_pool_cache["servers"]

    servers = _build_server_pool()
    stats = _load_host_stats()
    random.shuffle(servers)
    servers = sorted(servers, key=lambda item: _server_score(item, stats), reverse=True)

    if not PYTDX_SERVER_DISCOVERY_ENABLED:
        result = [(ip, port) for ip, port, _ in servers[:PYTDX_SERVER_POOL_LIMIT]]
        _host_pool_cache["servers"] = result
        return result

    preferred = [server for server in servers if (server[0], server[1]) not in _failed_server_cooldown]
    preferred = preferred[: max(1, int(PYTDX_SERVER_PROBE_COUNT))]

    discovered: List[Tuple[str, int, float]] = []
    for ip, port, name in preferred:
        latency_ms, quote_ok = _probe_server(ip, port)
        if latency_ms is None:
            _record_host_result(ip, port, success=False, name=name, quote_success=False)
            continue
        _record_host_result(ip, port, success=True, latency_ms=latency_ms, name=name, quote_success=quote_ok)
        if quote_ok:
            discovered.append((ip, port, latency_ms))

    discovered.sort(key=lambda item: item[2])
    result = [(ip, port) for ip, port, _ in discovered]

    # 如果没有找到支持行情的服务器，降级使用所有连接成功的服务器
    if len(result) < max(3, min(PYTDX_SERVER_POOL_LIMIT, 6)):
        for ip, port, _ in servers:
            candidate = (ip, port)
            if candidate in result or candidate in _failed_server_cooldown:
                continue
            result.append(candidate)
            if len(result) >= PYTDX_SERVER_POOL_LIMIT:
                break

    if not result:
        result = [(ip, port) for ip, port, _ in servers[:PYTDX_SERVER_POOL_LIMIT]]

    _host_pool_cache["servers"] = result
    return result


def _reset_connection():
    api = getattr(_thread_local, "api", None)
    if api:
        try:
            api.disconnect()
        except Exception:
            pass
    _thread_local.api = None
    _thread_local.connected = False
    _thread_local.current_server = None


def _get_thread_api_state() -> tuple[Optional[TdxHq_API], bool, Optional[Tuple[str, int]]]:
    return (
        getattr(_thread_local, "api", None),
        bool(getattr(_thread_local, "connected", False)),
        getattr(_thread_local, "current_server", None),
    )


def _get_api() -> Optional[TdxHq_API]:
    api, connected, current_server = _get_thread_api_state()
    if connected and api:
        try:
            api.get_security_count(0)
            return api
        except Exception:
            if current_server:
                _failed_server_cooldown[current_server] = True
            _reset_connection()

    api = TdxHq_API()
    _thread_local.api = api
    servers = _discover_available_servers()

    available_servers = [server for server in servers if server not in _failed_server_cooldown]
    if not available_servers:
        _failed_server_cooldown.clear()
        available_servers = servers

    for ip, port in available_servers:
        start = time.perf_counter()
        try:
            if api.connect(ip, port, time_out=1):
                latency_ms = (time.perf_counter() - start) * 1000
                _thread_local.connected = True
                _thread_local.current_server = (ip, port)
                _record_host_result(ip, port, success=True, latency_ms=latency_ms)
                logger.info(f"pytdx连接成功: {ip}:{port}, thread={threading.get_ident()}")
                return api
            _failed_server_cooldown[(ip, port)] = True
            _record_host_result(ip, port, success=False)
        except Exception as e:
            _failed_server_cooldown[(ip, port)] = True
            _record_host_result(ip, port, success=False)
            logger.warning(f"pytdx连接失败 {ip}:{port}: {e}")
            try:
                api.disconnect()
            except Exception:
                pass
            continue
        try:
            api.disconnect()
        except Exception:
            pass

    _reset_connection()
    logger.error("pytdx所有服务器连接失败")
    return None


def reconnect():
    _host_pool_cache.clear()
    _reset_connection()
    return _get_api()


def _normalize_kline_result(result: pd.DataFrame) -> pd.DataFrame:
    if "datetime" in result.columns:
        result = result.drop_duplicates(subset=["datetime"], keep="first")
        result = result.sort_values("datetime").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "vol", "volume"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    if "vol" in result.columns and "volume" not in result.columns:
        result = result.rename(columns={"vol": "volume"})

    return result


def _get_time_col(df: pd.DataFrame) -> Optional[str]:
    if "datetime" in df.columns:
        return "datetime"
    if "date" in df.columns:
        return "date"
    return None


def _get_tdx_bars(
    code: str,
    period: str,
    count: int,
    fetch_method: str,
    cache_prefix: str,
    before_ts: Optional[str | int | float] = None,
) -> pd.DataFrame:
    cache_key = f"{cache_prefix}_{code}_{period}_{count}_{before_ts or ''}"
    if cache_key in _cache:
        return _cache[cache_key]

    api = _get_api()
    if not api:
        return pd.DataFrame()

    market = get_market_code(code)
    category = PYTDX_CATEGORY.get(period)
    if category is None:
        logger.error(f"不支持的K线周期: {period}")
        return pd.DataFrame()

    try:
        fetcher = getattr(api, fetch_method)
        all_data = []
        start = 0
        before_dt = None
        if before_ts not in (None, ""):
            before_dt = pd.to_datetime(before_ts, errors="coerce", utc=True)
            if pd.isna(before_dt):
                before_dt = None
        target_count = max(int(count), 1)

        while True:
            batch = 800
            data = fetcher(category, market, code, start, batch)
            if data is None:
                break

            if isinstance(data, list):
                if len(data) == 0:
                    break
                df = pd.DataFrame(data)
            elif isinstance(data, pd.DataFrame):
                if data.empty:
                    break
                df = data
            else:
                break

            all_data.append(df)
            combined = _normalize_kline_result(pd.concat(all_data, ignore_index=True))
            time_col = _get_time_col(combined)
            if before_dt is not None and time_col is not None:
                combined[time_col] = pd.to_datetime(combined[time_col], errors="coerce", utc=True)
                filtered = combined[combined[time_col] < before_dt].reset_index(drop=True)
                if len(filtered) >= target_count:
                    all_data = [filtered]
                    break
            if len(df) < batch:
                break
            if before_dt is None and len(pd.concat(all_data, ignore_index=True)) >= target_count:
                break
            start += len(df)

        if not all_data:
            return pd.DataFrame()

        result = _normalize_kline_result(pd.concat(all_data, ignore_index=True))
        time_col = _get_time_col(result)
        if before_dt is not None and time_col is not None:
            result[time_col] = pd.to_datetime(result[time_col], errors="coerce", utc=True)
            result = result[result[time_col] < before_dt].reset_index(drop=True)
        _cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning(f"pytdx获取K线失败，准备重连 {code} {period} {fetch_method}: {e}")
        _, _, current_server = _get_thread_api_state()
        if current_server:
            _failed_server_cooldown[current_server] = True
        _reset_connection()
        logger.error(f"pytdx获取K线失败 {code} {period} {fetch_method}: {e}")
        return pd.DataFrame()


def get_kline(code: str, period: str = "daily", count: int = 300, before_ts: Optional[str | int | float] = None) -> pd.DataFrame:
    return _get_tdx_bars(
        code=code,
        period=period,
        count=count,
        fetch_method="get_security_bars",
        cache_prefix="kline",
        before_ts=before_ts,
    )


def get_index_kline(code: str, period: str = "daily", count: int = 300, before_ts: Optional[str | int | float] = None) -> pd.DataFrame:
    return _get_tdx_bars(
        code=code,
        period=period,
        count=count,
        fetch_method="get_index_bars",
        cache_prefix="index_kline",
        before_ts=before_ts,
    )


def _is_fund_code(code: str) -> bool:
    """判断是否为 ETF/LOF/基金代码。

    pytdx get_security_quotes 对基金类证券返回的 price/open/high/low/昨收存在
    确定的 10 倍放大问题（实测 510300/159915/512100/588000 等 12 只 ETF/LOF
    全部恰好 ×10，成交量/成交额不受影响）。据此对基金代码的价格字段统一除以 10
    修正，使 ETF 实时价在详情页/扫描/自选/K线补充等所有调用点都正确。
    """
    code = str(code).strip().zfill(6)
    return code.startswith(("50", "51", "52", "56", "58", "15", "16"))


def get_realtime_quotes(codes: List[str]) -> List[dict]:
    """获取实时行情，支持自动切换服务器重试。

    如果当前服务器返回空数据，会自动标记为行情获取失败并切换服务器重试。
    """
    max_retries = 3

    for attempt in range(max_retries):
        api = _get_api()
        if not api:
            return []

        try:
            params = []
            for code in codes:
                market = get_market_code(code)
                params.append((market, code))

            data = []
            for i in range(0, len(params), 80):
                # TDX 协议单次最多约 80 个代码,超量会被静默截断 → 分块拉取合并
                chunk = api.get_security_quotes(params[i : i + 80])
                if chunk:
                    data.extend(chunk)

            # 检测空数据，标记服务器为行情获取失败
            if data is None or len(data) == 0:
                _, _, current_server = _get_thread_api_state()
                if current_server:
                    ip, port = current_server
                    logger.warning(f"pytdx服务器 {ip}:{port} 返回空行情数据，尝试切换服务器")
                    _record_host_result(ip, port, success=True, quote_success=False)
                    _failed_server_cooldown[current_server] = True
                _reset_connection()

                # 最后一次重试失败则返回空
                if attempt == max_retries - 1:
                    logger.error("pytdx所有服务器行情获取失败")
                    return []
                continue

            # 成功获取数据，记录行情获取成功
            _, _, current_server = _get_thread_api_state()
            if current_server:
                ip, port = current_server
                _record_host_result(ip, port, success=True, quote_success=True)

            results = []
            for item in data:
                code = str(item.get("code", "")).strip()
                # 基金类(ETF/LOF)价格字段整体放大 10 倍，这里除回；成交量/成交额不受影响
                price_div = 10.0 if _is_fund_code(code) else 1.0
                results.append({
                    "code": code,
                    "name": item.get("name", ""),
                    "price": float(item.get("price", 0)) / price_div,
                    "open": float(item.get("open", 0)) / price_div,
                    "high": float(item.get("high", 0)) / price_div,
                    "low": float(item.get("low", 0)) / price_div,
                    "pre_close": float(item.get("last_close", 0)) / price_div,
                    "volume": float(item.get("vol", 0)),
                    "amount": float(item.get("amount", 0)),
                    "bid1": float(item.get("bid1", 0)) / price_div,
                    "ask1": float(item.get("ask1", 0)) / price_div,
                    "bid1_vol": float(item.get("bid_vol1", 0)),
                    "ask1_vol": float(item.get("ask_vol1", 0)),
                })
                if results[-1]["pre_close"] > 0:
                    results[-1]["change_pct"] = round(
                        (results[-1]["price"] - results[-1]["pre_close"]) / results[-1]["pre_close"] * 100, 2
                    )
                    results[-1]["change"] = round(results[-1]["price"] - results[-1]["pre_close"], 3)
                else:
                    results[-1]["change_pct"] = 0
                    results[-1]["change"] = 0

            return results
        except Exception as e:
            logger.warning(f"pytdx实时行情异常，准备重连: {e}")
            _, _, current_server = _get_thread_api_state()
            if current_server:
                _failed_server_cooldown[current_server] = True
            _reset_connection()
            logger.error(f"pytdx获取实时行情失败: {e}")
            return []

    return []


def search_etf(keyword: str, limit: int = 20) -> List[dict]:
    api = _get_api()
    if not api:
        return []

    try:
        results = []
        for market in [0, 1]:
            start = 0
            while True:
                batch = api.get_security_list(market, start, 500)
                if not batch:
                    break
                for item in batch:
                    code = item.get("code", "")
                    name = item.get("name", "")
                    if keyword.lower() in code.lower() or keyword.lower() in name.lower():
                        results.append({"code": code, "name": name, "market": market})
                        if len(results) >= limit:
                            return results
                start += len(batch)
                if len(batch) < 500:
                    break
        return results
    except Exception as e:
        logger.warning(f"pytdx搜索异常，准备重连: {e}")
        _, _, current_server = _get_thread_api_state()
        if current_server:
            _failed_server_cooldown[current_server] = True
        _reset_connection()
        logger.error(f"pytdx搜索ETF失败: {e}")
        return []


def list_all_a_share_candidates() -> List[dict]:
    def is_a_share_code(code: str) -> bool:
        return code.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689", "830", "831", "832", "833", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879"))

    def fetch_market(api: TdxHq_API, market: int) -> list[dict]:
        results: list[dict] = []
        seen_codes: set[str] = set()
        count_info = api.get_security_count(market)
        total = 0 if not count_info else int(count_info[0]) if isinstance(count_info, (list, tuple)) and len(count_info) > 0 else 0
        start = 0
        step_candidates = [500, 200, 100, 50]
        while True:
            batch = None
            for step in step_candidates:
                try:
                    batch = api.get_security_list(market, start, step)
                    if batch:
                        break
                except Exception:
                    batch = None
            if not batch:
                if total > 0 and start < total:
                    start += 50
                    continue
                break
            for item in batch:
                code = str(item.get("code", "")).zfill(6)
                if not code or code in seen_codes or not is_a_share_code(code):
                    continue
                seen_codes.add(code)
                results.append(
                    {
                        "code": code,
                        "name": str(item.get("name", "") or code),
                        "market": market,
                    }
                )
            start += len(batch)
            if len(batch) < step_candidates[-1]:
                break
            if total > 0 and start >= total:
                break
        return results

    for outer in range(3):
        api = _get_api()
        if not api:
            reconnect()
            continue
        try:
            total_results: list[dict] = []
            for m in (0, 1):
                part = fetch_market(api, m)
                total_results.extend(part)
            if total_results:
                return total_results
            reconnect()
        except Exception as e:
            logger.warning(f"pytdx拉取A股股票池异常，准备重连: {e}")
            _, _, current_server = _get_thread_api_state()
            if current_server:
                _failed_server_cooldown[current_server] = True
            _reset_connection()
    try:
        def _tencent_prefix(code: str) -> str:
            code = str(code).strip().zfill(6)
            if code.startswith(("43", "83", "87", "88", "89", "92")):
                return "bj"
            return "sh" if code.startswith(("5", "6", "9")) else "sz"

        def _fetch_tencent(symbols: list[str]) -> str:
            if not symbols:
                return ""
            resp = requests.get(
                "https://qt.gtimg.cn/q=" + ",".join(symbols),
                timeout=8,
                headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            return resp.text or ""

        def _parse_tencent(text: str) -> list[tuple[str, str]]:
            pairs: list[tuple[str, str]] = []
            for line in (text or "").split(";"):
                line = line.strip()
                if not line or '="' not in line or not line.startswith("v_"):
                    continue
                _, payload = line.split('="', 1)
                payload = payload.rstrip('"')
                parts = payload.split("~")
                if len(parts) < 3:
                    continue
                code = str(parts[2] or "").strip().zfill(6)
                name = str(parts[1] or code).strip()
                if code:
                    pairs.append((code, name))
            return pairs

        ranges: list[tuple[int, int]] = []
        ranges.extend([(0, 10000), (2, 1000), (3, 1000), (300, 2000), (301, 2000)])
        ranges.extend([(600, 4000), (601, 2000), (603, 2000), (605, 1000), (688, 2000), (689, 1000)])
        codes: list[str] = []
        for prefix, span in ranges:
            base = prefix * 1000 if prefix >= 100 else prefix * 10000
            for i in range(span):
                code = str(base + i).zfill(6)
                if is_a_share_code(code):
                    codes.append(code)
        seen: set[str] = set()
        results: list[dict] = []
        chunk = 200
        for i in range(0, len(codes), chunk):
            part = codes[i:i + chunk]
            symbols = [f"{_tencent_prefix(code)}{code}" for code in part]
            text = _fetch_tencent(symbols)
            for code, name in _parse_tencent(text):
                if code in seen:
                    continue
                seen.add(code)
                results.append({"code": code, "name": name or code, "market": get_market_code(code)})
        return results
    except Exception as e:
        logger.warning(f"基于腾讯行情扫描股票池失败: {e}")
        return []


def get_minute_kline(code: str, minute_period: int = 1, count: int = 500) -> pd.DataFrame:
    period_map = {1: "1min", 5: "5min", 15: "15min", 30: "30min", 60: "60min"}
    period = period_map.get(minute_period, "1min")
    return get_kline(code, period, count)


def disconnect():
    _reset_connection()


def get_finance_info(code: str) -> dict:
    code = str(code).strip().zfill(6)
    cache_key = f"finance_{code}"
    if cache_key in _finance_cache:
        return _finance_cache[cache_key]

    api = _get_api()
    if not api:
        return {}

    market = get_market_code(code)
    try:
        result = api.get_finance_info(market, code)
        normalized = dict(result) if result else {}
        _finance_cache[cache_key] = normalized
        return normalized
    except Exception as e:
        logger.warning(f"pytdx获取财务信息异常，准备重连: {e}")
        _, _, current_server = _get_thread_api_state()
        if current_server:
            _failed_server_cooldown[current_server] = True
        _reset_connection()
        logger.error(f"pytdx获取财务信息失败 {code}: {e}")
        return {}
