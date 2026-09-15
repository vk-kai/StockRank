import asyncio
from copy import deepcopy
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional
import logging
import re
import pandas as pd
from cachetools import TTLCache
import requests
import threading
from urllib.parse import urlsplit

from backend import auth_service
from backend.config import ALL_PERIODS, MINUTE_PERIODS, MARKET_MAP_PUSH_URL, MARKET_MAP_PAGE_URL
from backend.auto_scan import (
    get_scan_scope_candidates,
    get_scan_status,
    mark_signal_alerts_read,
    run_scan_if_needed,
    update_scan_settings,
)
from backend.history_download_service import get_history_download_status, start_history_download
from backend import db
from backend.kline_service import get_security_kline, is_market_session_now, is_realtime_sensitive_period
from backend.kline_parquet import get_kline_parquet
from backend.market import akshare_data, intraday_series, pytdx_data
from backend.market.aggregator import (
    kline_to_chart_data, calculate_ma, calculate_macd, calculate_boll
)
from backend.backtest.strategies import list_backtest_strategies
from backend.live_scan.strategies import list_strategies
from backend.signal_diagnosis import diagnose_signal_bar
from backend.security_service import (
    add_watchlist_security,
    get_market_code,
    get_search_candidates,
    get_watchlist_security,
    list_watchlist_securities,
    remove_watchlist_security,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market"])
_kline_response_cache = TTLCache(maxsize=256, ttl=45)


def _normalize_search_code(code: object) -> str:
    raw = str(code or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 6:
        return digits
    return raw


def _build_market_map_push_payload(run: dict, signals: list[dict]) -> dict:
    deduped: dict[str, dict] = {}
    for signal in signals:
        code = _normalize_search_code(signal.get("code"))
        if not code:
            continue
        if code in deduped:
            continue
        deduped[code] = {
            "code": code.zfill(6),
            "name": str(signal.get("name") or code).strip() or code.zfill(6),
        }
    stocks = list(deduped.values())
    return {
        "source": "quant-scan",
        "run_id": int(run.get("id") or 0),
        "pushed_at": run.get("finished_at") or run.get("started_at") or "",
        "stocks": stocks,
    }


def _push_scan_run_to_market_map(payload: dict) -> dict:
    # 大盘云图接收端已无需鉴权，直接推送
    try:
        response = requests.post(
            MARKET_MAP_PUSH_URL,
            json=payload,
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("请求大盘云图推送接口失败 url=%s payload=%s", MARKET_MAP_PUSH_URL, payload)
        raise

    response_text = response.text[:1000]
    if not response.ok:
        logger.error(
            "大盘云图推送接口返回非200 status=%s url=%s body=%s payload=%s",
            response.status_code,
            MARKET_MAP_PUSH_URL,
            response_text,
            payload,
        )
        raise RuntimeError(f"大盘云图接口异常：HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        logger.error(
            "大盘云图推送接口返回非JSON url=%s body=%s payload=%s",
            MARKET_MAP_PUSH_URL,
            response_text,
            payload,
        )
        raise RuntimeError("大盘云图返回了无效响应")

    if not isinstance(data, dict):
        logger.error("大盘云图推送接口返回了非对象响应 url=%s data=%s payload=%s", MARKET_MAP_PUSH_URL, data, payload)
        raise RuntimeError("大盘云图返回了无效响应")
    if not data.get("success"):
        logger.error("大盘云图推送接口返回失败 url=%s data=%s payload=%s", MARKET_MAP_PUSH_URL, data, payload)
        raise RuntimeError(data.get("message") or data.get("error") or "推送到大盘云图失败")
    return data


def _resolve_security_name(code: str) -> str:
    for etf in get_search_candidates():
        if etf["code"] == code and etf.get("name") and etf["name"] != code:
            return etf["name"]

    try:
        quotes = pytdx_data.get_realtime_quotes([code])
        if quotes:
            quote_name = str(quotes[0].get("name") or "").strip()
            if quote_name and quote_name != code:
                return quote_name
    except Exception as e:
        logger.warning(f"pytdx实时行情补名称失败 {code}: {e}")

    try:
        pytdx_matches = pytdx_data.search_etf(code, 10)
        exact = next((item for item in pytdx_matches if item.get("code") == code and item.get("name") and item["name"] != code), None)
        if exact:
            return exact["name"]
    except Exception as e:
        logger.warning(f"pytdx搜索补名称失败 {code}: {e}")

    try:
        stock_name = akshare_data.get_stock_name_by_code(code)
        if stock_name and stock_name != code:
            return stock_name
    except Exception as e:
        logger.warning(f"股票名录补名称失败 {code}: {e}")

    try:
        detail = akshare_data.get_cached_etf_detail(code) or akshare_data.get_etf_detail(code, timeout=2)
        if detail and detail.get("name") and detail["name"] != code:
            return detail["name"]
    except Exception as e:
        logger.warning(f"AkShare补名称失败 {code}: {e}")

    try:
        ak_matches = akshare_data.search_etf_akshare(code, 10)
        exact = next((item for item in ak_matches if item.get("code") == code and item.get("name") and item["name"] != code), None)
        if exact:
            return exact["name"]
    except Exception as e:
        logger.warning(f"AkShare搜索补名称失败 {code}: {e}")

    return code


def _resolve_security_detail(code: str, name_hint: str = "") -> Optional[dict]:
    if _is_major_index_request(code, name_hint):
        index_quotes = akshare_data.get_major_index_quotes([code])
    else:
        index_quotes = []

    if index_quotes:
        index_quote = index_quotes[0]
        return {
            "code": index_quote["code"],
            "name": index_quote["name"],
            "price": index_quote.get("price", 0) or 0,
            "change_pct": index_quote.get("change_pct", 0) or 0,
            "change": index_quote.get("change", 0) or 0,
            "volume": 0,
            "amount": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "prev_close": 0,
            "turnover_rate": None,
            "total_mv": None,
            "circ_mv": None,
            "market": index_quote.get("market", get_market_code(code)),
        }

    if not _is_major_index_request(code, name_hint):
        stock_detail = akshare_data.get_stock_spot_detail(code)
        if stock_detail:
            return stock_detail

    cached_detail = akshare_data.get_cached_etf_detail(code)
    if cached_detail:
        return cached_detail

    etf_detail = akshare_data.get_etf_detail(code, timeout=3)
    if etf_detail:
        return etf_detail

    stock_name = akshare_data.get_stock_name_by_code(code)
    if stock_name:
        return {
            "code": code,
            "name": stock_name,
            "price": 0,
            "change_pct": 0,
            "change": 0,
            "volume": 0,
            "amount": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "prev_close": 0,
            "turnover_rate": None,
            "total_mv": None,
            "circ_mv": None,
            "market": get_market_code(code),
        }

    return None


def _is_major_index_request(code: str, name_hint: str = "") -> bool:
    normalized_code = str(code).zfill(6)
    normalized_name = str(name_hint or "").strip()
    if normalized_name:
        matched = next(
            (
                item
                for item in akshare_data.MAJOR_INDEXES
                if item["code"] == normalized_code and item["name"] == normalized_name
            ),
            None,
        )
        if matched is not None:
            return True

    watch_item = get_watchlist_security(code)
    if not watch_item:
        return False
    return any(
        item["code"] == normalized_code
        and (
            watch_item.get("name") == item["name"]
            or int(watch_item.get("market", -1)) == int(item["market"])
        )
        for item in akshare_data.MAJOR_INDEXES
    )


def _get_realtime_quote_for_code(code: str, name_hint: str = "") -> Optional[dict]:
    if _is_major_index_request(code, name_hint):
        index_quotes = akshare_data.get_major_index_quotes([code])
        if index_quotes:
            return index_quotes[0]

    quotes = pytdx_data.get_realtime_quotes([code])
    if quotes:
        return quotes[0]

    index_quotes = akshare_data.get_major_index_quotes([code])
    if index_quotes:
        return index_quotes[0]

    return None


def _get_native_kline(code: str, period: str, count: int, name_hint: str = "") -> pd.DataFrame:
    if _is_major_index_request(code, name_hint):
        return pytdx_data.get_index_kline(code, period, count)
    return pytdx_data.get_kline(code, period, count)


def _get_latest_session_minute_data(code: str, count: int, name_hint: str = "") -> pd.DataFrame:
    # 逻辑抽到 market/intraday_series.py(套利背离监控共用),此处保留 index 判定后委托
    return intraday_series.get_latest_session_minutes(
        code, count, is_index=_is_major_index_request(code, name_hint)
    )


def _get_kline_cache_key(code: str, period: str, count: int, security_kind: str, before_ts: str = "") -> str:
    return f"{security_kind}|{code}|{period}|{int(count)}|{before_ts}"


def _direct_minute_period(period: str) -> Optional[str]:
    return {
        "1": "1min",
        "5": "5min",
        "15": "15min",
        "30": "30min",
        "60": "60min",
        "120": "120min",
    }.get(period)


def _get_cached_kline_response(code: str, period: str, count: int, security_kind: str, before_ts: str = ""):
    if security_kind == "security" and is_realtime_sensitive_period(period) and is_market_session_now() and not before_ts:
        return None
    cached = _kline_response_cache.get(_get_kline_cache_key(code, period, count, security_kind, before_ts))
    if cached is None:
        return None
    return deepcopy(cached)


def _set_cached_kline_response(code: str, period: str, count: int, security_kind: str, response: dict, before_ts: str = "") -> dict:
    if response.get("success") and response.get("data"):
        _kline_response_cache[_get_kline_cache_key(code, period, count, security_kind, before_ts)] = deepcopy(response)
    return response


def _build_detail_from_quote(code: str, quote: dict, cached_detail: Optional[dict] = None) -> dict:
    detail = cached_detail.copy() if cached_detail else {}
    quote_name = quote.get("name") or detail.get("name", code)
    detail.update({
        "code": code,
        "name": quote_name,
        "price": quote.get("price", detail.get("price", 0)),
        "change_pct": quote.get("change_pct", detail.get("change_pct", 0)),
        "change": quote.get("change", detail.get("change", 0)),
        "volume": quote.get("volume", detail.get("volume", 0)),
        "amount": quote.get("amount", detail.get("amount", 0)),
        "open": quote.get("open", detail.get("open", 0)),
        "high": quote.get("high", detail.get("high", 0)),
        "low": quote.get("low", detail.get("low", 0)),
        "prev_close": quote.get("pre_close", detail.get("prev_close", 0)),
    })
    detail.setdefault("iopv", None)
    detail.setdefault("premium_rate", None)
    detail.setdefault("turnover_rate", None)
    detail.setdefault("total_mv", None)
    detail.setdefault("circ_mv", None)
    return detail


def _calc_hfq_factor(code: str, raw_pre_close: float) -> float:
    """把「不复权 raw 实时价」换算到「本地K线口径(前复权 qfq)」的缩放因子。

    本地日线/周月线基准是前复权(qfq)，pytdx 实时报价是不复权(raw)。qfq 最新价
    ==真实价，因子日常≈1；除权除息当日有微小偏差(≈股息率)，次日历史同步后自愈。
    这里复用 kline_service.py 的对齐方法：用本地昨收 / 实时 raw 昨收得到因子，
    调用方把 raw 价 ×factor 即可换算到本地口径。
    取不到本地昨收时返回 1.0（退化为直接比较，不强行修正）。
    因子合理区间 [0.85,1.15]（qfq 基线下因子≈1）：源昨收异常（除权日未调整昨收/
    错标的）会让因子飙到 3~5 或缩到 0.2~0.5，直接乘会算出离谱收益，此时返回 1.0
    （raw≈qfq 直接比较，误差仅股息级）。
    """
    if raw_pre_close <= 0:
        return 1.0
    try:
        df = get_kline_parquet(code, "daily", limit=2)
    except Exception:
        return 1.0
    if df is None or df.empty or "close" not in df.columns:
        return 1.0
    try:
        closes = [float(v) for v in df["close"].tolist() if v is not None]
    except Exception:
        return 1.0
    closes = [c for c in closes if c > 0]
    if not closes:
        return 1.0
    last_local_close = closes[-1]
    factor = last_local_close / raw_pre_close
    if not (0.85 <= factor <= 1.15):
        logger.error(
            f"[口径因子] {code} 因子异常返回1.0: 本地昨收{last_local_close}/源昨收{raw_pre_close}"
            f"=因子{factor:.3f}超[0.85,1.15](疑似除权日未调整昨收或错标的)"
        )
        return 1.0
    return factor


@router.get("/watchlist")
def get_watchlist(request: Request):
    user = auth_service.get_current_user_from_request(request)
    owner_username = auth_service.get_visible_owner_username(user)
    try:
        watchlist = list_watchlist_securities(owner_username)
        codes = [item["code"] for item in watchlist]
        quotes = pytdx_data.get_realtime_quotes(codes)
        index_quotes = akshare_data.get_major_index_quotes(codes)

        quote_map = {q["code"]: q for q in quotes}
        quote_map.update({q["code"]: q for q in index_quotes})

        tracked_by_code: dict[str, list] = {}
        for t in db.list_tracked_signals(owner_username):
            tracked_by_code.setdefault(t["code"], []).append(t)

        result = []
        for item in watchlist:
            q = quote_map.get(item["code"], {})
            tracked_list = tracked_by_code.get(item["code"], [])
            tracked_signal_count = len(tracked_list)
            tracked_return_pct = None
            if tracked_signal_count > 0:
                buy_signals = [t for t in tracked_list if t["direction"] == "buy"]
                base_signal = buy_signals[0] if buy_signals else tracked_list[0]
                base_price = base_signal["signal_price"]
                current_price = q.get("price", 0)
                if base_price > 0 and current_price > 0:
                    # base_price 是本地K线口径(前复权 qfq)，current_price 是不复权(raw)实时价，
                    # 口径差异需对齐（与 kline_service 对齐做法一致）。qfq 基线下因子≈1，
                    # 因子异常时 _calc_hfq_factor 内部已兜底返回 1.0（raw≈qfq 直接比）。
                    raw_pre_close = float(q.get("pre_close") or 0)
                    qfq_factor = _calc_hfq_factor(item["code"], raw_pre_close)
                    current_price_hfq = current_price * qfq_factor
                    tracked_return_pct = round((current_price_hfq - base_price) / base_price * 100, 2)
            result.append({
                "code": item["code"],
                "name": item["name"],
                "market": item["market"],
                "t0": item.get("t0", False),
                "price": q.get("price", 0),
                "change_pct": q.get("change_pct", 0),
                "change": q.get("change", 0),
                "volume": q.get("volume", 0),
                "amount": q.get("amount", 0),
                "tracked_signal_count": tracked_signal_count,
                "tracked_return_pct": tracked_return_pct,
            })
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"获取自选列表失败: {e}")
        return {"success": False, "data": list_watchlist_securities(owner_username), "message": str(e)}


@router.get("/etf-list")
def get_etf_list(request: Request):
    return get_watchlist(request)


@router.post("/watchlist/add")
def add_watchlist_item(
    request: Request,
    code: str = Query(..., description="证券代码"),
    name: str = Query("", description="名称"),
    market: Optional[int] = Query(None, description="市场代码"),
):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能修改自选列表，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    code = code.strip()
    owner_username = auth_service.get_visible_owner_username(user)
    result = add_watchlist_security(code, name=name.strip(), market=market, t0=None, owner_username=owner_username)
    return result


@router.post("/etf/add")
def add_etf(
    request: Request,
    code: str = Query(..., description="证券代码"),
    name: str = Query("", description="名称"),
    market: Optional[int] = Query(None, description="市场代码"),
):
    return add_watchlist_item(request=request, code=code, name=name, market=market)


@router.post("/watchlist/remove")
def remove_watchlist_item(
    request: Request,
    code: str = Query(..., description="证券代码"),
):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能修改自选列表，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    owner_username = auth_service.get_visible_owner_username(user)
    result = remove_watchlist_security(code, owner_username=owner_username)
    return result


@router.post("/etf/remove")
def remove_etf(
    request: Request,
    code: str = Query(..., description="证券代码"),
):
    return remove_watchlist_item(request=request, code=code)


@router.get("/security/search")
def search_security(
    keyword: str = Query(..., description="搜索证券关键词"),
    limit: int = Query(20, description="返回数量"),
):
    try:
        results = []
        keyword_lower = keyword.lower().strip()
        existing_codes = set()

        local_results = db.search_stock_pool(keyword, limit=limit, kline_downloaded_only=False)
        for item in local_results:
            code = _normalize_search_code(item.get("code"))
            if not code or code in existing_codes:
                continue
            results.append({
                "code": code,
                "name": item.get("name", code),
                "market": item.get("market", 1),
                "price": item.get("price", 0),
                "change_pct": item.get("change_pct", 0),
            })
            existing_codes.add(code)
            if len(results) >= limit:
                return {"success": True, "data": results}

        # 本地数据库已有全部股票池数据，仅当本地无结果时才走远程搜索
        if not results:
            try:
                pytdx_results = pytdx_data.search_etf(keyword, limit)
                for item in pytdx_results:
                    code = _normalize_search_code(item.get("code"))
                    if not code or code in existing_codes:
                        continue
                    results.append({
                        "code": code,
                        "name": item.get("name", code),
                        "market": item.get("market", 1),
                    })
                    existing_codes.add(code)
                    if len(results) >= limit:
                        break
            except Exception as e:
                logger.warning(f"pytdx搜索证券失败: {e}")

        if not results:
            try:
                stock_results = akshare_data.search_stock_code_name(keyword, limit)
                for item in stock_results:
                    code = _normalize_search_code(item.get("code"))
                    if not code or code in existing_codes:
                        continue
                    results.append({**item, "code": code})
                    existing_codes.add(code)
                    if len(results) >= limit:
                        break
            except Exception as e:
                logger.warning(f"AkShare搜索A股名称失败: {e}")

        if not results:
            try:
                akshare_results = akshare_data.search_etf_akshare(keyword, limit)
                for r in akshare_results:
                    code = _normalize_search_code(r.get("code"))
                    if code not in existing_codes:
                        results.append({**r, "code": code})
                        existing_codes.add(code)
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.warning(f"AkShare搜索失败: {e}")
        
        return {"success": True, "data": results}
    except Exception as e:
        logger.error(f"搜索证券失败: {e}")
        return {"success": False, "data": [], "message": str(e)}


@router.get("/etf/search")
def search_etf(
    keyword: str = Query(..., description="搜索证券关键词"),
    limit: int = Query(20, description="返回数量"),
):
    return search_security(keyword=keyword, limit=limit)


@router.get("/security/detail")
def security_detail(
    code: str = Query(..., description="证券代码"),
    name: str = Query("", description="证券名称提示"),
    include_margin: bool = Query(False, description="是否包含融资信息"),
):
    try:
        cached_detail = _resolve_security_detail(code, name)
        quote = _get_realtime_quote_for_code(code, name)
        if quote:
            detail = _build_detail_from_quote(code, quote, cached_detail)
            if include_margin and not _is_major_index_request(code, name):
                detail["margin_profile"] = akshare_data.get_margin_profile(code, 30)
            return {"success": True, "data": detail}

        detail = cached_detail
        if detail:
            if include_margin and not _is_major_index_request(code, name):
                detail["margin_profile"] = akshare_data.get_margin_profile(code, 30)
            return {"success": True, "data": detail}
        return {"success": False, "message": "未找到标的信息"}
    except Exception as e:
        logger.error(f"获取标的详情失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/etf/detail")
def etf_detail(
    code: str = Query(..., description="证券代码"),
    name: str = Query("", description="证券名称提示"),
    include_margin: bool = Query(False, description="是否包含融资信息"),
):
    return security_detail(code=code, name=name, include_margin=include_margin)


@router.get("/kline")
def get_kline(
    code: str = Query(..., description="证券代码"),
    name: str = Query("", description="证券名称提示"),
    period: str = Query("daily", description="K线周期"),
    count: int = Query(300, description="K线数量"),
    before_ts: str = Query("", description="向前分页游标，返回早于该时间的K线"),
):
    if period not in ALL_PERIODS:
        return {"success": False, "message": f"不支持的周期: {period}"}

    try:
        security_kind = "index" if _is_major_index_request(code, name) else "security"
        cursor = before_ts.strip()
        cached = _get_cached_kline_response(code, period, count, security_kind, cursor)
        if cached is not None:
            return cached

        if period in MINUTE_PERIODS:
            if period == "intraday":
                df = _get_latest_session_minute_data(code, count, name)
                page = {
                    "data": df.tail(int(count)).reset_index(drop=True) if df is not None and not df.empty else pd.DataFrame(),
                    "has_more": False,
                    "next_before_ts": None,
                    "source": "pytdx",
                }
            else:
                direct_period = _direct_minute_period(period)
                if direct_period is None:
                    return {"success": False, "message": f"分钟周期 {period} 暂无原生接口支持"}
                page = get_security_kline(code, direct_period, count, security_kind, before_ts=cursor)

            df = page.get("data") if isinstance(page, dict) else pd.DataFrame()
            if df is not None and not df.empty:
                chart_data = kline_to_chart_data(df, period)
                ma_data = calculate_ma(df)
                macd_data = calculate_macd(df)
                boll_data = calculate_boll(df)

                return _set_cached_kline_response(code, period, count, security_kind, {
                    "success": True,
                    "data": chart_data,
                    "indicators": {
                        "ma": ma_data,
                        "macd": macd_data,
                        "boll": boll_data,
                    },
                    "has_more": bool(page.get("has_more")),
                    "next_before_ts": page.get("next_before_ts"),
                    "source": page.get("source"),
                }, cursor)
            else:
                return {"success": False, "message": "获取分钟K线数据失败"}

        else:
            page = get_security_kline(code, period, count, security_kind, before_ts=cursor)
            df = page.get("data") if isinstance(page, dict) else pd.DataFrame()

            if df is not None and not df.empty:
                chart_data = kline_to_chart_data(df, period)
                ma_data = calculate_ma(df)
                macd_data = calculate_macd(df)
                boll_data = calculate_boll(df)

                return _set_cached_kline_response(code, period, count, security_kind, {
                    "success": True,
                    "data": chart_data,
                    "indicators": {
                        "ma": ma_data,
                        "macd": macd_data,
                        "boll": boll_data,
                    },
                    "has_more": bool(page.get("has_more")),
                    "next_before_ts": page.get("next_before_ts"),
                    "source": page.get("source"),
                }, cursor)
            else:
                return {"success": False, "message": "获取日K线数据失败"}

    except Exception as e:
        logger.error(f"获取K线失败 {code} {period}: {e}")
        return {"success": False, "message": str(e)}


@router.get("/realtime")
def get_realtime(code: str = Query(..., description="证券代码")):
    try:
        quote = _get_realtime_quote_for_code(code)
        if quote:
            return {"success": True, "data": quote}
        return {"success": False, "message": "获取实时行情失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/strategies")
def get_strategies(request: Request):
    user = auth_service.get_current_user_from_request(request)
    return {"success": True, "data": auth_service.filter_strategy_options(list_backtest_strategies(), user)}


@router.get("/scan-strategies")
def get_scan_strategies(request: Request):
    user = auth_service.get_current_user_from_request(request)
    return {"success": True, "data": auth_service.filter_strategy_options(list_strategies(), user)}


@router.get("/index/quotes")
def get_major_index_quotes():
    return {"success": True, "data": akshare_data.get_major_index_quotes(["000001"])}


@router.get("/scan/status")
def scan_status(request: Request):
    user = auth_service.get_current_user_from_request(request)
    return {"success": True, "data": get_scan_status(user)}


@router.get("/signal-diagnosis")
def get_signal_diagnosis(
    request: Request,
    source: str = Query(..., description="诊断场景: backtest 或 scan"),
    code: str = Query(..., description="证券代码"),
    name: str = Query("", description="证券名称"),
    period: str = Query(..., description="图表周期"),
    strategy_name: str = Query(..., description="策略名称"),
    target_timestamp: int = Query(..., description="双击K线时间戳"),
    range_start: Optional[str] = Query(None, description="回测范围开始时间"),
    range_end: Optional[str] = Query(None, description="回测范围结束时间"),
):
    try:
        user = auth_service.get_current_user_from_request(request)
        try:
            auth_service.require_operable_user(user, "临时账号不能使用信号诊断，请先开通 VIP 后再操作")
        except auth_service.StrategyAccessDenied as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        access = auth_service.get_strategy_access(strategy_name, user)
        if not access["allowed"]:
            raise HTTPException(status_code=int(access["status_code"]), detail=str(access["message"]))
        data = diagnose_signal_bar(
            source=source,
            code=code,
            name=name,
            period=period,
            strategy_name=strategy_name,
            target_timestamp=target_timestamp,
            range_start=range_start,
            range_end=range_end,
        )
        return {"success": True, "data": data}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("信号诊断失败 %s %s %s: %s", source, code, strategy_name, exc)
        return {"success": False, "message": str(exc)}


@router.post("/scan/settings")
def save_scan_settings(
    request: Request,
    enabled: Optional[bool] = Query(None, description="是否开启自动扫描"),
    strategy_name: Optional[str] = Query(None, description="策略名称"),
    interval_minutes: Optional[int] = Query(None, description="扫描间隔"),
    scan_scope_type: Optional[str] = Query(None, description="扫描范围: all 或 selected"),
    scan_scope_codes: str = Query("", description="逗号分隔的扫描股票代码"),
    scan_focus_codes: str = Query("", description="逗号分隔的特别关注股票代码"),
    scan_period: Optional[str] = Query(None, description="扫描K线周期"),
    auto_download_enabled: Optional[bool] = Query(None, description="是否开启自动下载"),
    auto_download_hour: Optional[int] = Query(None, description="自动下载时间（小时）"),
    kline_force_refresh: Optional[bool] = Query(None, description="是否强制覆盖本地K线"),
):
    interval = 30 if interval_minutes is None else max(30, interval_minutes)
    selected_codes = [item.strip() for item in scan_scope_codes.split(",") if item.strip()]
    focus_codes = [item.strip() for item in scan_focus_codes.split(",") if item.strip()]
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能修改扫描设置，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    try:
        data = update_scan_settings(
            enabled=enabled,
            strategy_name=strategy_name,
            interval_minutes=interval,
            scan_scope_type=scan_scope_type,
            scan_scope_codes=selected_codes,
            scan_focus_codes=focus_codes,
            scan_period=scan_period,
            auto_download_enabled=auto_download_enabled,
            auto_download_hour=auto_download_hour,
            kline_force_refresh=kline_force_refresh,
            current_user=user,
        )
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return {"success": True, "data": data}


@router.post("/scan/run")
async def run_scan_now(request: Request):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能启动扫描，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    settings = db.get_scan_settings()
    access = auth_service.get_strategy_access(str(settings.get("strategy_name") or ""), user)
    if not access["allowed"]:
        raise HTTPException(status_code=int(access["status_code"]), detail=str(access["message"]))

    def _run():
        try:
            run_scan_if_needed(True, current_user=user)
        except Exception:
            pass

    import threading
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"success": True, "data": {"status": get_scan_status(user)}}


@router.get("/scan/candidates")
def scan_candidates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    keyword: str = Query("", description="代码或名称模糊搜索"),
):
    return {
        "success": True,
        "data": get_scan_scope_candidates(page=page, page_size=page_size, keyword=keyword),
    }


@router.post("/scan/read")
def mark_scan_read(
    request: Request,
    ids: str = Query("", description="逗号分隔的信号ID"),
):
    signal_ids = [int(item) for item in ids.split(",") if item.strip().isdigit()]
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能修改扫描结果，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    for signal in db.list_scan_signals_by_ids(signal_ids):
        if not auth_service.can_access_owner(signal.get("owner_username"), user):
            raise HTTPException(status_code=403, detail="无权删除该扫描结果")
        access = auth_service.get_strategy_access(str(signal.get("strategy_name") or ""), user)
        if not access["allowed"]:
            raise HTTPException(status_code=int(access["status_code"]), detail=str(access["message"]))
    mark_signal_alerts_read(signal_ids)
    return {"success": True, "data": {"ids": signal_ids}}


@router.delete("/scan/runs/{run_id}")
def delete_scan_run_api(request: Request, run_id: int):
    run = db.get_scan_run(run_id)
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能删除扫描结果，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    if run:
        if not auth_service.can_access_owner(run.get("owner_username"), user):
            raise HTTPException(status_code=403, detail="无权删除该扫描结果")
        access = auth_service.get_strategy_access(str(run.get("strategy_name") or ""), user)
        if not access["allowed"]:
            raise HTTPException(status_code=int(access["status_code"]), detail=str(access["message"]))
    result = db.delete_scan_run(run_id)
    return {
        "success": bool(result.get("deleted")),
        "data": result,
        "message": result.get("message") or "",
    }


@router.post("/scan/runs/{run_id}/push-to-market-map")
def push_scan_run_to_market_map(request: Request, run_id: int):
    run = db.get_scan_run(run_id)
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能推送扫描结果，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    if not run:
        return {"success": False, "message": "扫描结果不存在"}
    if not auth_service.can_access_owner(run.get("owner_username"), user):
        raise HTTPException(status_code=403, detail="无权推送该扫描结果")
    access = auth_service.get_strategy_access(str(run.get("strategy_name") or ""), user)
    if not access["allowed"]:
        raise HTTPException(status_code=int(access["status_code"]), detail=str(access["message"]))

    owner_username = auth_service.get_visible_owner_username(user)
    signals = db.list_scan_signals_by_run(run_id, owner_username)
    payload = _build_market_map_push_payload(run, signals)
    if not payload["stocks"]:
        return {"success": False, "message": "本轮扫描暂无可推送的股票"}

    try:
        push_result = _push_scan_run_to_market_map(payload)
    except requests.RequestException as exc:
        logger.exception("推送扫描结果到大盘云图失败 run_id=%s url=%s payload=%s", run_id, MARKET_MAP_PUSH_URL, payload)
        return {"success": False, "message": "推送到大盘云图失败，请稍后重试"}
    except Exception as exc:
        logger.exception("推送扫描结果到大盘云图异常 run_id=%s url=%s payload=%s", run_id, MARKET_MAP_PUSH_URL, payload)
        return {"success": False, "message": str(exc) or "推送到大盘云图失败"}

    return {
        "success": True,
        "message": "已推送到大盘云图",
        "data": {
            "run_id": int(run_id),
            "pushed_count": len(payload["stocks"]),
            "market_map_url": MARKET_MAP_PAGE_URL,
            "remote": push_result.get("data") if isinstance(push_result, dict) else None,
        },
    }


@router.get("/scan/feed")
def scan_feed(
    after_id: int = Query(0, ge=0, description="水位线:只返回 id 大于该值的信号"),
    limit: int = Query(50, ge=1, le=100),
):
    """给 StockRank 消息总线用的免鉴权增量投递口:返回 id > after_id 的扫描信号(id 升序)。

    拉取侧(quant_signal_bridge)用水位线自行去重,本端点无副作用、不打标记;
    max_id 供首跑初始化水位线(跳过历史存量,不回放旧信号)。
    """
    signals, max_id = db.list_scan_signals_after(int(after_id), limit=limit)
    return {"success": True, "data": signals, "count": len(signals), "max_id": max_id}


@router.post("/scan/track")
def track_scan_signal(
    request: Request,
    signal_id: int = Query(..., description="扫描信号ID"),
):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能跟踪扫描信号，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    owner_username = auth_service.get_visible_owner_username(user)
    result = db.track_signal(signal_id, owner_username)
    if not result.get("success"):
        return result
    track_data = result["data"]
    added_to_watchlist = False
    existing = get_watchlist_security(track_data["code"], owner_username)
    if not existing:
        add_res = add_watchlist_security(track_data["code"], name=track_data.get("name", ""), owner_username=owner_username)
        added_to_watchlist = add_res.get("success", False)
    track_data["added_to_watchlist"] = added_to_watchlist
    return {"success": True, "data": track_data}


@router.post("/scan/untrack")
def untrack_scan_signal(
    request: Request,
    tracked_id: int = Query(..., description="跟踪记录ID"),
    remove_from_watchlist: bool = Query(False, description="是否同时从自选股移除"),
):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能取消跟踪，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    owner_username = auth_service.get_visible_owner_username(user)
    tracked_items = db.list_tracked_signals(owner_username)
    tracked = next((item for item in tracked_items if int(item.get("id") or 0) == int(tracked_id)), None)
    if not tracked:
        return {"success": False, "message": "跟踪记录不存在"}

    quote = _get_realtime_quote_for_code(tracked["code"], tracked.get("name") or "")
    exit_price = float((quote or {}).get("price") or 0)
    if exit_price <= 0:
        return {"success": False, "message": "当前无法获取实时价格，暂时不能结算，请稍后重试"}

    # signal_price 是本地K线口径(前复权 qfq)，而实时 exit_price 是不复权(raw)，需统一口径：
    # 把 raw exit_price 换算到 qfq（因子≈1，异常时 _calc_hfq_factor 内部兜底返回 1.0）。
    raw_pre_close = float((quote or {}).get("pre_close") or 0)
    qfq_factor = _calc_hfq_factor(tracked["code"], raw_pre_close)
    exit_price = round(exit_price * qfq_factor, 4)

    removed_from_watchlist = False
    if remove_from_watchlist:
        remove_watchlist_security(tracked["code"], owner_username=owner_username)
        removed_from_watchlist = True

    removed = db.untrack_signal(
        tracked_id,
        exit_price=exit_price,
        owner_username=owner_username,
        removed_from_watchlist=removed_from_watchlist,
    )
    if not removed:
        return {"success": False, "message": "跟踪记录不存在"}
    return {
        "success": True,
        "data": {
            "code": removed["code"],
            "name": removed["name"],
            "removed_from_watchlist": removed_from_watchlist,
            "settlement": {
                "tracked_id": removed["id"],
                "signal_id": removed["signal_id"],
                "direction": removed["direction"],
                "signal_price": removed["signal_price"],
                "signal_time": removed["signal_time"],
                "exit_price": removed["exit_price"],
                "exit_time": removed["exit_time"],
                "return_pct": removed["return_pct"],
                "strategy_name": removed["strategy_name"],
                "period": removed["period"],
                "reason": removed["reason"],
                "tracked_at": removed["tracked_at"],
            },
        },
    }


@router.get("/tracked-signals")
def get_tracked_signals(
    request: Request,
    code: str = Query("", description="按股票代码筛选"),
):
    user = auth_service.get_current_user_from_request(request)
    owner_username = auth_service.get_visible_owner_username(user)
    code = code.strip()
    if code:
        data = db.get_tracked_signals_by_code(code, owner_username)
    else:
        data = db.list_tracked_signals(owner_username)
    return {"success": True, "data": data}


@router.get("/settled-signals")
def get_settled_signals(
    request: Request,
    code: str = Query("", description="按股票代码筛选"),
):
    """历史跟踪记录：已结算归档的跟踪记录，按结束日期倒序。"""
    user = auth_service.get_current_user_from_request(request)
    owner_username = auth_service.get_visible_owner_username(user)
    code = code.strip()
    data = db.list_settled_signals(code=code or None, owner_username=owner_username)
    return {"success": True, "data": data}


@router.get("/history-download/status")
def history_download_status():
    return {"success": True, "data": get_history_download_status()}


@router.post("/history-download/start")
def start_history_download_api(
    request: Request,
    periods: str = Query("", description="逗号分隔的K线周期"),
    force_refresh: bool = Query(False, description="是否强制刷新已缓存数据"),
    codes: str = Query("", description="逗号分隔的指定股票代码"),
    time_span: str = Query("1m", description="时间跨度：1m/3m/6m/1y/2y/3y"),
):
    user = auth_service.get_current_user_from_request(request)
    if not auth_service.is_vk_user(user):
        raise HTTPException(status_code=403, detail="目前只有管理员能下载 K 线数据")
    selected_periods = [item.strip() for item in periods.split(",") if item.strip()]
    selected_codes = [item.strip() for item in codes.split(",") if item.strip()]
    _kline_response_cache.clear()
    result = start_history_download(selected_periods, force_refresh=force_refresh, codes=selected_codes, time_span=time_span)
    return result
