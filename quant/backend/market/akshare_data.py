import akshare as ak
import io
import math
import pandas as pd
import requests
import threading
from datetime import datetime, timedelta
from typing import Optional, List
import logging
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from cachetools import TTLCache

from backend import db
from backend.market import pytdx_data
from backend.security_service import get_market_code
from backend.security_service import ensure_runtime_db_ready
from backend.config import (
    INDUSTRY_SOURCE_PRIORITY,
    MARKET_INDEX_SOURCE_PRIORITY,
    MARKET_SPOT_SOURCE_PRIORITY,
    STOCK_NAME_SOURCE_PRIORITY,
)
from backend.system_utils import get_optimal_worker_count
from backend.time_utils import now_beijing

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=get_optimal_worker_count("io", max_limit=12))

_cache = TTLCache(maxsize=100, ttl=60)
# 腾讯单点行情微缓存:盘中日K实时补充每 5~15 秒就会来取一次,10s 缓存把该接口
# 压到每代码 ≤6 次/分钟,防高频被风控(该接口无公开配额,保守为上)
_tencent_quote_cache = TTLCache(maxsize=256, ttl=10)
_spot_cache_df = None
_spot_cache_at = None
_spot_cache_ttl = 300
_stock_spot_cache_df = None
_stock_spot_cache_at = None
_stock_spot_cache_ttl = 300
_stock_spot_retry_blocked_until = None
_index_spot_retry_blocked_until = None
_etf_hist_retry_blocked_until = None
_fund_name_cache_df = None
_fund_name_cache_at = None
_fund_name_cache_ttl = 3600
_stock_name_cache_df = None
_stock_name_cache_at = None
_stock_name_cache_ttl = 3600
_pytdx_stock_name_map = None
_pytdx_stock_name_at = None
_pytdx_stock_name_ttl = 3600
_industry_cache_map = None
_industry_cache_at = None
_industry_cache_ttl = 21600
_index_spot_cache_df = None
_index_spot_cache_at = None
_index_spot_cache_ttl = 60
_etf_spot_refresh_lock = threading.Lock()
_fund_name_refresh_lock = threading.Lock()
_stock_spot_refresh_lock = threading.Lock()
_index_spot_refresh_lock = threading.Lock()
_stock_name_refresh_lock = threading.Lock()
_industry_map_refresh_lock = threading.Lock()

MAJOR_INDEXES = [
    {"code": "000001", "name": "上证指数", "market": 1},
    {"code": "399001", "name": "深证成指", "market": 0},
    {"code": "399006", "name": "创业板指", "market": 0},
    {"code": "000300", "name": "沪深300", "market": 1},
    {"code": "000905", "name": "中证500", "market": 1},
    {"code": "000852", "name": "中证1000", "market": 1},
]


def _get_market_prefix(code: str) -> str:
    code = str(code).strip().zfill(6)
    return "sh" if code.startswith(("5", "6", "9")) else "sz"


def _get_tencent_prefix(code: str) -> str:
    code = str(code).strip().zfill(6)
    if code.startswith(("43", "83", "87", "88", "89", "92")):
        return "bj"
    return "sh" if code.startswith(("5", "6", "9")) else "sz"


def _is_margin_supported_security(code: str) -> bool:
    code = str(code).strip().zfill(6)
    return code.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689"))


def _fetch_etf_spot_df(timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(ak.fund_etf_spot_em)
    return future.result(timeout=timeout)


def _fetch_fund_name_df(timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(ak.fund_name_em)
    return future.result(timeout=timeout)


def _fetch_stock_name_df(timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(_call_akshare_silently, ak.stock_info_a_code_name)
    return future.result(timeout=timeout)


def _call_akshare_silently(func, *args, **kwargs):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


def _fetch_stock_spot_df(timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(_call_akshare_silently, ak.stock_zh_a_spot)
    return future.result(timeout=timeout)


def _fetch_stock_spot_sina_df(timeout: int = 15) -> pd.DataFrame:
    try:
        future = _executor.submit(_call_akshare_silently, ak.stock_zh_a_spot)
        return future.result(timeout=timeout)
    except Exception as exc:
        if not _is_transient_upstream_error(exc):
            raise
        logger.warning(f"AkShare新浪A股现货失败，尝试直接请求新浪接口: {exc}")
        try:
            return _fetch_stock_spot_sina_direct_df(timeout=timeout)
        except Exception as direct_exc:
            logger.warning(f"直接请求新浪A股现货失败，回退腾讯现货源: {direct_exc}")
            return _fetch_stock_spot_tencent_df(timeout=max(timeout, 20))


def _fetch_stock_spot_sina_direct_df(timeout: int = 15) -> pd.DataFrame:
    count_response = requests.get(
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeStockCount",
        params={"node": "hs_a"},
        timeout=timeout,
        headers={"Referer": "http://vip.stock.finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"},
    )
    count_response.raise_for_status()
    count_response.encoding = "gbk"
    try:
        total_count = int(str(count_response.json()).strip().strip('"'))
    except Exception:
        total_count = 0

    page_size = 80
    max_pages = max(1, math.ceil(total_count / page_size)) if total_count > 0 else 80
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        response = requests.get(
            "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData",
            params={
                "page": str(page),
                "num": str(page_size),
                "sort": "symbol",
                "asc": "1",
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "page",
            },
            timeout=timeout,
            headers={"Referer": "http://vip.stock.finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        response.encoding = "gbk"
        page_rows = response.json()
        if not page_rows:
            break
        for item in page_rows:
            rows.append(
                {
                    "代码": item.get("code"),
                    "名称": item.get("name"),
                    "最新价": item.get("trade"),
                    "涨跌额": item.get("pricechange"),
                    "涨跌幅": item.get("changepercent"),
                    "买入": item.get("buy"),
                    "卖出": item.get("sell"),
                    "昨收": item.get("settlement"),
                    "今开": item.get("open"),
                    "最高": item.get("high"),
                    "最低": item.get("low"),
                    "成交量": item.get("volume"),
                    "成交额": item.get("amount"),
                    "时间戳": item.get("ticktime"),
                    "turnoverratio": item.get("turnoverratio"),
                    "mktcap": item.get("mktcap"),
                    "nmc": item.get("nmc"),
                    "symbol": item.get("symbol"),
                }
            )
    return pd.DataFrame(rows)


def _fetch_index_spot_sina_df(timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(_call_akshare_silently, ak.stock_zh_index_spot_sina)
    return future.result(timeout=timeout)


def _fetch_tencent_quote_text(symbols: list[str], timeout: int = 10) -> str:
    if not symbols:
        return ""
    response = requests.get(
        "https://qt.gtimg.cn/q=" + ",".join(symbols),
        timeout=timeout,
        headers={
            "Referer": "https://gu.qq.com/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()
    response.encoding = "gbk"
    return response.text or ""


def _parse_tencent_quote_text(text: str) -> list[dict]:
    rows: list[dict] = []
    for line in (text or "").split(";"):
        line = line.strip()
        if not line or '="' not in line or not line.startswith("v_"):
            continue
        symbol, payload = line.split('="', 1)
        payload = payload.rstrip('"')
        parts = payload.split("~")
        if len(parts) < 46:
            continue
        code = str(parts[2] or "").strip().zfill(6)
        if not code:
            continue
        summary_parts = str(parts[35] or "").split("/")
        amount = _safe_float(summary_parts[2], nullable=True) if len(summary_parts) >= 3 else None
        total_mv = _safe_float(parts[44], nullable=True)
        circ_mv = _safe_float(parts[45], nullable=True)
        rows.append(
            {
                "代码": code,
                "名称": str(parts[1] or code).strip(),
                "最新价": _safe_float(parts[3], nullable=True),
                "昨收": _safe_float(parts[4], nullable=True),
                "今开": _safe_float(parts[5], nullable=True),
                "成交量": _safe_float(parts[36], nullable=True),
                "成交额": amount,
                "涨跌额": _safe_float(parts[31], nullable=True),
                "涨跌幅": _safe_float(parts[32], nullable=True),
                "最高": _safe_float(parts[33], nullable=True),
                "最低": _safe_float(parts[34], nullable=True),
                "换手率": _safe_float(parts[38], nullable=True),
                "市盈率-动态": _safe_float(parts[39], nullable=True),
                "总市值": total_mv * 100000000 if total_mv is not None else None,
                "流通市值": circ_mv * 100000000 if circ_mv is not None else None,
                "市净率": _safe_float(parts[46], nullable=True) if len(parts) > 46 else None,
                "symbol": symbol[2:],
            }
        )
    return rows


def _fetch_stock_spot_tencent_df(timeout: int = 15) -> pd.DataFrame:
    code_list: list[str] = []
    name_df = _get_stock_name_df(timeout=max(timeout, 30))
    if name_df is not None and not name_df.empty:
        code_col = _find_column(name_df, "code", "代码")
        if code_col:
            code_list = (
                name_df[code_col]
                .astype(str)
                .str.strip()
                .str.zfill(6)
                .drop_duplicates()
                .tolist()
            )
    if not code_list:
        code_list = [
            str(item.get("code", "")).strip().zfill(6)
            for item in pytdx_data.list_all_a_share_candidates()
            if str(item.get("code", "")).strip()
        ]
        code_list = list(dict.fromkeys(code_list))
    if not code_list:
        return pd.DataFrame()
    rows: list[dict] = []
    chunk_size = 200
    for start in range(0, len(code_list), chunk_size):
        chunk = code_list[start:start + chunk_size]
        symbols = [f"{_get_tencent_prefix(code)}{code}" for code in chunk]
        text = _fetch_tencent_quote_text(symbols, timeout=min(timeout, 10))
        rows.extend(_parse_tencent_quote_text(text))
    return pd.DataFrame(rows)


def _fetch_index_spot_tencent_df(timeout: int = 15) -> pd.DataFrame:
    symbols = [
        f"{'sh' if int(item.get('market', 0)) == 1 else 'sz'}{str(item['code']).zfill(6)}"
        for item in MAJOR_INDEXES
    ]
    text = _fetch_tencent_quote_text(symbols, timeout=min(timeout, 10))
    return pd.DataFrame(_parse_tencent_quote_text(text))


def _fetch_index_spot_pytdx_df(timeout: int = 15) -> pd.DataFrame:
    del timeout
    quotes = pytdx_data.get_realtime_quotes([str(item["code"]).zfill(6) for item in MAJOR_INDEXES])
    if not quotes:
        return pd.DataFrame()
    meta_map = {str(item["code"]).zfill(6): item for item in MAJOR_INDEXES}
    rows: list[dict] = []
    for quote in quotes:
        code = str(quote.get("code", "")).strip().zfill(6)
        if not code:
            continue
        meta = meta_map.get(code, {})
        rows.append(
            {
                "代码": code,
                "名称": str(quote.get("name") or meta.get("name") or code).strip(),
                "最新价": _safe_float(quote.get("price"), nullable=True),
                "涨跌幅": _safe_float(quote.get("change_pct"), nullable=True),
                "涨跌额": _safe_float(quote.get("change"), nullable=True),
                "昨收": _safe_float(quote.get("pre_close"), nullable=True),
                "今开": _safe_float(quote.get("open"), nullable=True),
                "最高": _safe_float(quote.get("high"), nullable=True),
                "最低": _safe_float(quote.get("low"), nullable=True),
                "成交量": _safe_float(quote.get("volume"), nullable=True),
                "成交额": _safe_float(quote.get("amount"), nullable=True),
            }
        )
    return pd.DataFrame(rows)


def _fetch_stock_spot_by_source(source: str, timeout: int = 15) -> pd.DataFrame:
    normalized_source = str(source or "").strip().lower()
    if normalized_source == "tencent":
        return _fetch_stock_spot_tencent_df(timeout=max(timeout, 20))
    if normalized_source == "sina":
        return _fetch_stock_spot_sina_df(timeout=timeout)
    raise ValueError(f"不支持的A股现货源: {source}")


def _fetch_index_spot_by_source(source: str, timeout: int = 15) -> pd.DataFrame:
    normalized_source = str(source or "").strip().lower()
    if normalized_source == "pytdx":
        return _fetch_index_spot_pytdx_df(timeout=timeout)
    if normalized_source == "tencent":
        return _fetch_index_spot_tencent_df(timeout=timeout)
    if normalized_source == "sina":
        return _fetch_index_spot_sina_df(timeout=timeout)
    raise ValueError(f"不支持的指数现货源: {source}")


def _fetch_stock_sector_spot_df(timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(_call_akshare_silently, ak.stock_sector_spot, indicator="行业")
    return future.result(timeout=timeout)


def _fetch_stock_sector_detail_df(sector: str, timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(_call_akshare_silently, ak.stock_sector_detail, sector=sector)
    return future.result(timeout=timeout)


def _fetch_stock_industry_cninfo_df(code: str, timeout: int = 15) -> pd.DataFrame:
    future = _executor.submit(
        _call_akshare_silently,
        ak.stock_industry_change_cninfo,
        symbol=code,
        start_date="20000101",
        end_date=now_beijing().strftime("%Y%m%d"),
    )
    return future.result(timeout=timeout)


def _find_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    if df is None or df.empty:
        return None

    normalized = {str(col).replace(" ", ""): col for col in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        matched = normalized.get(candidate.replace(" ", ""))
        if matched is not None:
            return matched
    return None


def _safe_float(value, default=0, nullable: bool = False):
    if pd.isna(value) or value in ("", "-", "--", None):
        return None if nullable else default
    try:
        parsed = float(value)
        if math.isnan(parsed):
            return None if nullable else default
        return parsed
    except (TypeError, ValueError):
        return None if nullable else default


def _is_transient_upstream_error(exc: Exception) -> bool:
    text = str(exc)
    transient_markers = (
        "ProxyError",
        "RemoteDisconnected",
        "Max retries exceeded",
        "Read timed out",
        "ConnectTimeout",
        "Connection aborted",
        "SSLError",
        "Can not decode value starting with character '<'",
        "Expecting value: line 1 column 1",
        "<html",
        "<!DOCTYPE html",
    )
    return any(marker in text for marker in transient_markers)


def _upstream_retry_cooldown(exc: Exception, transient_seconds: int = 90, default_seconds: int = 30) -> int:
    return transient_seconds if _is_transient_upstream_error(exc) else default_seconds


def _log_fetch_issue(context: str, exc: Exception, *, source: str = "", transient_level: int = logging.WARNING, default_level: int = logging.ERROR):
    level = transient_level if _is_transient_upstream_error(exc) else default_level
    prefix = f"{context}{f' {source}' if source else ''}"
    logger.log(level, f"{prefix}失败: {exc}")


def _row_value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in ("", "-", "--", None) and not pd.isna(value):
            return value
    return None


def _row_text(row, *keys, default: str = "") -> str:
    value = _row_value(row, *keys)
    return str(value).strip() if value not in (None, "") else default


def _optional_text(value) -> Optional[str]:
    if value in ("", "-", "--", None):
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _row_float(row, *keys, nullable: bool = False, default=0):
    return _safe_float(_row_value(row, *keys), default=default, nullable=nullable)


def _normalize_spot_row(row, code: Optional[str] = None) -> dict:
    actual_code = str(code or _row_value(row, "代码", "code", "symbol") or "").zfill(6)
    return {
        "code": actual_code,
        "name": _row_text(row, "名称", "name", default=actual_code),
        "price": _row_float(row, "最新价", "trade", "price"),
        "change_pct": _row_float(row, "涨跌幅", "changepercent", "change_pct"),
        "change": _row_float(row, "涨跌额", "pricechange", "change"),
        "volume": _row_float(row, "成交量", "volume"),
        "amount": _row_float(row, "成交额", "amount"),
        "open": _row_float(row, "开盘价", "今开", "open"),
        "high": _row_float(row, "最高价", "最高", "high"),
        "low": _row_float(row, "最低价", "最低", "low"),
        "prev_close": _row_float(row, "昨收", "昨收盘", "settlement", "pre_close", "prev_close"),
        "iopv": _safe_float(_row_value(row, "IOPV实时估值", "IOPV", "IOPV估值"), nullable=True),
        "premium_rate": _safe_float(_row_value(row, "基金折价率", "折价率", "溢价率"), nullable=True),
        "turnover_rate": _safe_float(_row_value(row, "换手率", "turnoverratio"), nullable=True),
        "total_mv": _safe_float(_row_value(row, "总市值", "基金规模", "mktcap", "total_mv"), nullable=True),
        "circ_mv": _safe_float(_row_value(row, "流通市值", "nmc", "circ_mv"), nullable=True),
        "market": get_market_code(actual_code),
    }


def _normalize_stock_spot_row(row, code: Optional[str] = None) -> dict:
    actual_code = str(code or _row_value(row, "代码", "code", "symbol") or "").zfill(6)
    return {
        "code": actual_code,
        "name": _row_text(row, "名称", "name", default=actual_code),
        "price": _row_float(row, "最新价", "trade", "price"),
        "change_pct": _row_float(row, "涨跌幅", "changepercent", "change_pct"),
        "change": _row_float(row, "涨跌额", "pricechange", "change"),
        "volume": _row_float(row, "成交量", "volume"),
        "amount": _row_float(row, "成交额", "amount"),
        "open": _row_float(row, "今开", "开盘价", "open"),
        "high": _row_float(row, "最高", "最高价", "high"),
        "low": _row_float(row, "最低", "最低价", "low"),
        "prev_close": _row_float(row, "昨收", "昨收盘", "settlement", "pre_close", "prev_close"),
        "turnover_rate": _safe_float(_row_value(row, "换手率", "turnoverratio"), nullable=True),
        "total_mv": _safe_float(_row_value(row, "总市值", "mktcap", "total_mv"), nullable=True),
        "circ_mv": _safe_float(_row_value(row, "流通市值", "nmc", "circ_mv"), nullable=True),
        "industry": _row_text(row, "所属行业", "所处行业", "行业") or None,
        "market": get_market_code(actual_code),
    }


def _get_stock_industry_map_from_sina(timeout: int = 8, allow_stale: bool = True) -> dict[str, str]:
    global _industry_cache_map, _industry_cache_at

    now = now_beijing()
    if (
        _industry_cache_map is not None
        and _industry_cache_at is not None
        and (now - _industry_cache_at).total_seconds() < _industry_cache_ttl
    ):
        return _industry_cache_map

    with _industry_map_refresh_lock:
        now = now_beijing()
        if (
            _industry_cache_map is not None
            and _industry_cache_at is not None
            and (now - _industry_cache_at).total_seconds() < _industry_cache_ttl
        ):
            return _industry_cache_map

        try:
            sector_df = _fetch_stock_sector_spot_df(timeout=timeout)
            if sector_df is None or sector_df.empty:
                return _industry_cache_map or {}

            sector_df = sector_df.copy()
            label_col = _find_column(sector_df, "label")
            industry_col = _find_column(sector_df, "板块")
            if not label_col or not industry_col:
                return _industry_cache_map or {}

            industry_map: dict[str, str] = {}
            for _, sector_row in sector_df.iterrows():
                sector_label = _optional_text(sector_row.get(label_col)) or ""
                industry_name = _optional_text(sector_row.get(industry_col)) or ""
                if not sector_label or not industry_name:
                    continue
                try:
                    detail_df = _fetch_stock_sector_detail_df(sector_label, timeout=timeout)
                except Exception as exc:
                    logger.debug(f"新浪行业板块详情获取失败 {sector_label}: {exc}")
                    continue
                if detail_df is None or detail_df.empty:
                    continue
                code_col = _find_column(detail_df, "code", "代码")
                if not code_col:
                    continue
                for code in detail_df[code_col].astype(str).str.strip().str.zfill(6).tolist():
                    if code and code not in industry_map:
                        industry_map[code] = industry_name

            if industry_map:
                _industry_cache_map = industry_map
                _industry_cache_at = now
                return industry_map
        except Exception as exc:
            logger.warning(f"新浪行业板块映射获取失败: {exc}")

    return _industry_cache_map or {}


def _get_stock_industry_from_cninfo(code: str, timeout: int = 8) -> Optional[str]:
    try:
        df = _fetch_stock_industry_cninfo_df(code, timeout=timeout)
        if df is None or df.empty:
            return None
        date_col = _find_column(df, "变更日期")
        standard_col = _find_column(df, "分类标准")
        work_df = df.copy()
        if date_col:
            work_df[date_col] = pd.to_datetime(work_df[date_col], errors="coerce")

        def _format_sw_industry(row: pd.Series) -> str:
            category = _row_text(row, "行业门类")
            sub_category = _row_text(row, "行业次类")
            if category and sub_category:
                return f"{category}-{sub_category}"
            return category or sub_category or _row_text(row, "行业大类") or _row_text(row, "行业中类")

        if standard_col:
            sw_df = work_df[work_df[standard_col].astype(str).str.strip().isin({
                "申银万国行业分类标准",
                "申银万国行业分类标准(旧)",
            })].copy()
            if not sw_df.empty:
                sw_df["_sw_rank"] = sw_df[standard_col].astype(str).map(
                    lambda value: 0 if str(value).strip() == "申银万国行业分类标准" else 1
                )
                sort_cols = ["_sw_rank"]
                ascending = [True]
                if date_col:
                    sort_cols.append(date_col)
                    ascending.append(False)
                sw_df = sw_df.sort_values(sort_cols, ascending=ascending, na_position="last").reset_index(drop=True)
                industry = _format_sw_industry(sw_df.iloc[0])
                if industry:
                    return industry

        # 兜底仍保留巨潮其它分类，避免极少数股票没有申万分类时直接丢失行业。
        fallback_df = work_df.copy()
        fallback_df["_industry_mid"] = fallback_df.apply(lambda row: _row_text(row, "行业中类"), axis=1)
        fallback_df = fallback_df[fallback_df["_industry_mid"] != ""]
        if not fallback_df.empty:
            if date_col:
                fallback_df = fallback_df.sort_values([date_col], ascending=[False], na_position="last").reset_index(drop=True)
            return str(fallback_df.iloc[0]["_industry_mid"]).strip() or None

        if date_col:
            work_df = work_df.sort_values([date_col], ascending=[False], na_position="last").reset_index(drop=True)
        row = work_df.iloc[0]
        industry = _row_text(row, "行业大类") or _row_text(row, "行业门类")
        return industry or None
    except Exception as exc:
        logger.warning(f"巨潮获取股票行业失败 {code}: {exc}")
        return None


def _get_pytdx_stock_name_map(allow_stale: bool = True) -> dict[str, str]:
    global _pytdx_stock_name_map, _pytdx_stock_name_at

    now = now_beijing()
    if (
        _pytdx_stock_name_map is not None
        and _pytdx_stock_name_at is not None
        and (now - _pytdx_stock_name_at).total_seconds() < _pytdx_stock_name_ttl
    ):
        return _pytdx_stock_name_map

    try:
        items = pytdx_data.list_all_a_share_candidates()
        name_map = {
            str(item.get("code", "")).strip().zfill(6): str(item.get("name", "") or "").strip()
            for item in items
            if str(item.get("code", "")).strip()
        }
        name_map = {code: name for code, name in name_map.items() if name}
        if name_map:
            _pytdx_stock_name_map = name_map
            _pytdx_stock_name_at = now
            return name_map
    except Exception as exc:
        logger.warning(f"pytdx获取A股名称映射失败: {exc}")

    return _pytdx_stock_name_map or {} if allow_stale else {}


def _merge_normalized_rows(row_groups: list[list[dict]]) -> list[dict]:
    merged: dict[str, dict] = {}
    for rows in row_groups:
        for item in rows:
            code = str(item.get("code", "")).zfill(6)
            if not code:
                continue
            if code not in merged:
                merged[code] = dict(item)
                continue
            existing = merged[code]
            for key, value in item.items():
                if key == "code":
                    continue
                if existing.get(key) in ("", None, 0) and value not in ("", None, 0):
                    existing[key] = value
                elif key in {"price", "amount", "volume", "total_mv", "circ_mv"} and value not in ("", None, 0):
                    existing[key] = value
    return sorted(merged.values(), key=lambda x: x.get("code", ""))


def _is_exchange_traded_candidate(name: str, fund_type: str) -> bool:
    name_upper = (name or "").upper()
    type_upper = (fund_type or "").upper()
    if "联接" in (name or "") or "联接" in (fund_type or ""):
        return False
    return "ETF" in name_upper or "LOF" in name_upper or "ETF" in type_upper or "LOF" in type_upper


def _get_etf_spot_df(timeout: int = 5, allow_stale: bool = True) -> pd.DataFrame:
    global _spot_cache_df, _spot_cache_at

    now = now_beijing()
    if (
        _spot_cache_df is not None
        and _spot_cache_at is not None
        and (now - _spot_cache_at).total_seconds() < _spot_cache_ttl
    ):
        return _spot_cache_df

    with _etf_spot_refresh_lock:
        now = now_beijing()
        if (
            _spot_cache_df is not None
            and _spot_cache_at is not None
            and (now - _spot_cache_at).total_seconds() < _spot_cache_ttl
        ):
            return _spot_cache_df

        try:
            df = _fetch_etf_spot_df(timeout=timeout)
            if df is not None and not df.empty:
                _spot_cache_df = df
                _spot_cache_at = now
                return df
        except FuturesTimeoutError:
            logger.info("AkShare获取ETF现货列表超时")
        except Exception as e:
            logger.error(f"AkShare获取ETF现货列表失败: {e}")

    if allow_stale and _spot_cache_df is not None:
        return _spot_cache_df

    logger.error("AkShare获取ETF现货列表失败：无可用数据")
    return pd.DataFrame()


def _get_fund_name_df(timeout: int = 5, allow_stale: bool = True) -> pd.DataFrame:
    global _fund_name_cache_df, _fund_name_cache_at

    now = now_beijing()
    if (
        _fund_name_cache_df is not None
        and _fund_name_cache_at is not None
        and (now - _fund_name_cache_at).total_seconds() < _fund_name_cache_ttl
    ):
        return _fund_name_cache_df

    with _fund_name_refresh_lock:
        now = now_beijing()
        if (
            _fund_name_cache_df is not None
            and _fund_name_cache_at is not None
            and (now - _fund_name_cache_at).total_seconds() < _fund_name_cache_ttl
        ):
            return _fund_name_cache_df

        try:
            df = _fetch_fund_name_df(timeout=timeout)
            if df is not None and not df.empty:
                _fund_name_cache_df = df
                _fund_name_cache_at = now
                return df
        except FuturesTimeoutError:
            logger.error("AkShare获取基金名称列表超时")
        except Exception as e:
            logger.error(f"AkShare获取基金名称列表失败: {e}")

    if allow_stale and _fund_name_cache_df is not None:
        return _fund_name_cache_df

    return pd.DataFrame()


def _get_stock_spot_df(timeout: int = 8, allow_stale: bool = True) -> pd.DataFrame:
    global _stock_spot_cache_df, _stock_spot_cache_at, _stock_spot_retry_blocked_until

    now = now_beijing()
    if (
        _stock_spot_cache_df is not None
        and _stock_spot_cache_at is not None
        and (now - _stock_spot_cache_at).total_seconds() < _stock_spot_cache_ttl
    ):
        return _stock_spot_cache_df

    if _stock_spot_retry_blocked_until is not None and now < _stock_spot_retry_blocked_until:
        if allow_stale and _stock_spot_cache_df is not None:
            return _stock_spot_cache_df
        return pd.DataFrame()

    with _stock_spot_refresh_lock:
        now = now_beijing()
        if (
            _stock_spot_cache_df is not None
            and _stock_spot_cache_at is not None
            and (now - _stock_spot_cache_at).total_seconds() < _stock_spot_cache_ttl
        ):
            return _stock_spot_cache_df

        if _stock_spot_retry_blocked_until is not None and now < _stock_spot_retry_blocked_until:
            if allow_stale and _stock_spot_cache_df is not None:
                return _stock_spot_cache_df
            return pd.DataFrame()

        df = pd.DataFrame()
        for source in MARKET_SPOT_SOURCE_PRIORITY:
            try:
                df = _fetch_stock_spot_by_source(source, timeout=timeout)
                if df is not None and not df.empty:
                    _stock_spot_cache_df = df
                    _stock_spot_cache_at = now
                    _stock_spot_retry_blocked_until = None
                    return df
            except FuturesTimeoutError:
                logger.warning(f"A股现货源获取超时: {source}")
            except Exception as exc:
                _log_fetch_issue("A股现货源获取", exc, source=source, transient_level=logging.WARNING, default_level=logging.WARNING)

        _stock_spot_retry_blocked_until = now + timedelta(seconds=45 if df is None or df.empty else 0)

    if allow_stale and _stock_spot_cache_df is not None:
        return _stock_spot_cache_df

    return pd.DataFrame()


def _resample_hist_df(df: pd.DataFrame, period: str) -> pd.DataFrame:
    normalized_period = str(period)
    if df is None or df.empty:
        return pd.DataFrame()
    if normalized_period == "daily":
        return df.sort_values("date").reset_index(drop=True)
    if "date" not in df.columns:
        return pd.DataFrame()

    work_df = df.copy()
    work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce", utc=True)
    work_df = work_df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if work_df.empty:
        return pd.DataFrame()
    work_df = work_df.set_index("date")
    rule = "W-FRI" if normalized_period == "weekly" else "ME"
    agg_map = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "amount": "sum",
    }
    existing_agg = {key: value for key, value in agg_map.items() if key in work_df.columns}
    result = work_df.resample(rule).agg(existing_agg).dropna(subset=["open", "high", "low", "close"], how="any")
    result = result.reset_index()
    return result


def _normalize_em_hist_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work_df = df.copy()
    work_df = work_df.rename(columns={
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "change_pct",
        "涨跌额": "change",
        "换手率": "turnover",
    })
    if "date" not in work_df.columns:
        return pd.DataFrame()
    work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce", utc=True)
    work_df = work_df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume", "amount", "amplitude", "change_pct", "change", "turnover"):
        if col in work_df.columns:
            work_df[col] = pd.to_numeric(work_df[col], errors="coerce")
    preferred_cols = ["date", "open", "high", "low", "close", "volume", "amount", "amplitude", "change_pct", "change", "turnover"]
    existing_cols = [col for col in preferred_cols if col in work_df.columns]
    return work_df[existing_cols]


def _load_etf_hist_from_fallback_sources(
    code: str,
    period: str,
    start_date: str,
    end_date: str,
    timeout: int,
) -> pd.DataFrame:
    symbol = str(code).zfill(6)
    symbol_with_market = f"{_get_market_prefix(code)}{symbol}"
    loaders = [
        lambda: ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="hfq", timeout=timeout),
        lambda: ak.stock_zh_a_hist_tx(symbol=symbol_with_market, start_date=start_date, end_date=end_date, adjust="hfq", timeout=timeout),
        lambda: ak.stock_zh_a_daily(symbol=symbol_with_market, start_date=start_date, end_date=end_date, adjust="hfq"),
    ]
    for loader in loaders:
        try:
            raw_df = loader()
            df = _normalize_em_hist_df(raw_df)
            if df is None or df.empty:
                df = _normalize_sina_daily_hist_df(raw_df)
            if df is not None and not df.empty:
                return _resample_hist_df(df, period)
        except Exception as e:
            logger.warning(f"ETF历史数据兜底源失败 {code} {period}: {e}")
            continue
    return _load_security_hist_from_fallback_sources(code, period, start_date, end_date, timeout)


def _normalize_sina_daily_hist_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work_df = df.copy()
    rename_map = {
        "日期": "date",
        "day": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover",
    }
    work_df = work_df.rename(columns={k: v for k, v in rename_map.items() if k in work_df.columns})
    if "date" not in work_df.columns:
        return pd.DataFrame()
    work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce", utc=True)
    work_df = work_df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume", "amount", "turnover"):
        if col in work_df.columns:
            work_df[col] = pd.to_numeric(work_df[col], errors="coerce")
    preferred_cols = ["date", "open", "high", "low", "close", "volume", "amount", "turnover"]
    existing_cols = [col for col in preferred_cols if col in work_df.columns]
    return work_df[existing_cols]


def _load_security_hist_from_fallback_sources(
    code: str,
    period: str,
    start_date: str,
    end_date: str,
    timeout: int,
) -> pd.DataFrame:
    symbol = f"{_get_market_prefix(code)}{str(code).zfill(6)}"
    loaders = [
        lambda: ak.stock_zh_a_daily(symbol=symbol, start_date=start_date, end_date=end_date, adjust="hfq"),
        lambda: ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start_date, end_date=end_date, adjust="hfq", timeout=timeout),
    ]
    for loader in loaders:
        try:
            df = _normalize_sina_daily_hist_df(loader())
            if df is not None and not df.empty:
                return _resample_hist_df(df, period)
        except Exception as e:
            logger.warning(f"历史数据兜底源失败 {code} {period}: {e}")
            continue
    return pd.DataFrame()


def _get_index_spot_df(timeout: int = 5, allow_stale: bool = True) -> pd.DataFrame:
    global _index_spot_cache_df, _index_spot_cache_at, _index_spot_retry_blocked_until

    now = now_beijing()
    if (
        _index_spot_cache_df is not None
        and _index_spot_cache_at is not None
        and (now - _index_spot_cache_at).total_seconds() < _index_spot_cache_ttl
    ):
        return _index_spot_cache_df

    if _index_spot_retry_blocked_until is not None and now < _index_spot_retry_blocked_until:
        if allow_stale and _index_spot_cache_df is not None:
            return _index_spot_cache_df
        return pd.DataFrame()

    with _index_spot_refresh_lock:
        now = now_beijing()
        if (
            _index_spot_cache_df is not None
            and _index_spot_cache_at is not None
            and (now - _index_spot_cache_at).total_seconds() < _index_spot_cache_ttl
        ):
            return _index_spot_cache_df

        if _index_spot_retry_blocked_until is not None and now < _index_spot_retry_blocked_until:
            if allow_stale and _index_spot_cache_df is not None:
                return _index_spot_cache_df
            return pd.DataFrame()

        df = pd.DataFrame()
        for source in MARKET_INDEX_SOURCE_PRIORITY:
            try:
                df = _fetch_index_spot_by_source(source, timeout=timeout)
                if df is not None and not df.empty:
                    _index_spot_cache_df = df
                    _index_spot_cache_at = now
                    _index_spot_retry_blocked_until = None
                    return df
            except FuturesTimeoutError:
                logger.warning(f"指数现货源获取超时: {source}")
            except Exception as e:
                _log_fetch_issue("指数现货源获取", e, source=source, transient_level=logging.WARNING, default_level=logging.ERROR)
                _index_spot_retry_blocked_until = now + timedelta(seconds=_upstream_retry_cooldown(e))

        if _index_spot_retry_blocked_until is None:
            _index_spot_retry_blocked_until = now + timedelta(seconds=45)

    if allow_stale and _index_spot_cache_df is not None:
        return _index_spot_cache_df

    return pd.DataFrame()


def _get_stock_name_df(timeout: int = 20, allow_stale: bool = True) -> pd.DataFrame:
    global _stock_name_cache_df, _stock_name_cache_at

    now = now_beijing()
    if (
        _stock_name_cache_df is not None
        and _stock_name_cache_at is not None
        and (now - _stock_name_cache_at).total_seconds() < _stock_name_cache_ttl
    ):
        return _stock_name_cache_df

    with _stock_name_refresh_lock:
        now = now_beijing()
        if (
            _stock_name_cache_df is not None
            and _stock_name_cache_at is not None
            and (now - _stock_name_cache_at).total_seconds() < _stock_name_cache_ttl
        ):
            return _stock_name_cache_df

        try:
            df = _fetch_stock_name_df(timeout=timeout)
            if df is not None and not df.empty:
                _stock_name_cache_df = df
                _stock_name_cache_at = now
                return df
        except FuturesTimeoutError:
            logger.error("AkShare获取A股代码名称列表超时")
        except Exception as e:
            logger.error(f"AkShare获取A股代码名称列表失败: {e}")

    if allow_stale and _stock_name_cache_df is not None:
        return _stock_name_cache_df

    return pd.DataFrame()


def _get_spot_row(code: str, df: Optional[pd.DataFrame] = None):
    spot_df = df if df is not None else _get_etf_spot_df(timeout=2)
    if spot_df is None or spot_df.empty:
        return None

    code_col = _find_column(spot_df, "代码")
    if code_col is None:
        return None

    matched = spot_df[spot_df[code_col].astype(str).str.zfill(6) == str(code).zfill(6)]
    if matched.empty:
        return None
    return matched.iloc[0]


def get_etf_hist_daily(code: str, start_date: str = None, end_date: str = None, period: str = "daily", timeout: int = 15) -> pd.DataFrame:
    global _etf_hist_retry_blocked_until

    cache_key = f"hist_{code}_{period}_{start_date}_{end_date}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        if not start_date:
            start_date = (now_beijing() - timedelta(days=365)).strftime("%Y%m%d")
        if not end_date:
            end_date = now_beijing().strftime("%Y%m%d")

        now = now_beijing()
        if _etf_hist_retry_blocked_until is not None and now < _etf_hist_retry_blocked_until:
            fallback_df = _load_etf_hist_from_fallback_sources(code, period, start_date, end_date, timeout)
            _cache[cache_key] = fallback_df
            return fallback_df

        future = _executor.submit(
            ak.fund_etf_hist_em,
            symbol=code,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust="hfq"
        )
        df = _normalize_em_hist_df(future.result(timeout=timeout))

        if df is not None and not df.empty:
            _etf_hist_retry_blocked_until = None
            _cache[cache_key] = df
            return df
    except FuturesTimeoutError:
        logger.error(f"AkShare获取ETF历史数据超时 {code}")
        _etf_hist_retry_blocked_until = now_beijing() + timedelta(seconds=45)
    except Exception as e:
        logger.error(f"AkShare获取ETF历史数据失败 {code}: {e}")
        cooldown_seconds = 120 if _is_transient_upstream_error(e) else 30
        _etf_hist_retry_blocked_until = now_beijing() + timedelta(seconds=cooldown_seconds)

    fallback_df = _load_etf_hist_from_fallback_sources(code, period, start_date, end_date, timeout)
    _cache[cache_key] = fallback_df
    return fallback_df


def get_stock_hist_daily(code: str, start_date: str = None, end_date: str = None, period: str = "daily", timeout: int = 15) -> pd.DataFrame:
    cache_key = f"stock_hist_{code}_{period}_{start_date}_{end_date}"
    if cache_key in _cache:
        return _cache[cache_key]

    if not start_date:
        start_date = (now_beijing() - timedelta(days=365)).strftime("%Y%m%d")
    if not end_date:
        end_date = now_beijing().strftime("%Y%m%d")

    symbol = str(code).zfill(6)
    symbol_with_market = f"{_get_market_prefix(code)}{symbol}"
    loaders = [
        lambda: ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="hfq",
            timeout=timeout,
        ),
        lambda: ak.stock_zh_a_hist_tx(
            symbol=symbol_with_market,
            start_date=start_date,
            end_date=end_date,
            adjust="hfq",
            timeout=timeout,
        ),
        lambda: ak.stock_zh_a_daily(
            symbol=symbol_with_market,
            start_date=start_date,
            end_date=end_date,
            adjust="hfq",
        ),
    ]
    for loader in loaders:
        try:
            raw_df = loader()
            df = _normalize_em_hist_df(raw_df)
            if df is None or df.empty:
                df = _normalize_sina_daily_hist_df(raw_df)
            if df is not None and not df.empty:
                df = _resample_hist_df(df, period)
                _cache[cache_key] = df
                return df
        except Exception as e:
            logger.warning(f"AkShare获取股票历史数据失败 {code}: {e}")

    fallback_df = _load_security_hist_from_fallback_sources(code, period, start_date, end_date, timeout)
    _cache[cache_key] = fallback_df
    return fallback_df


def get_etf_minute_data(code: str, period: str = "1") -> pd.DataFrame:
    cache_key = f"minute_{code}_{period}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        prefix = "sz" if code.startswith("15") else "sh"
        symbol = f"{prefix}{code}"

        df = ak.stock_zh_a_minute(symbol=symbol, period=period, adjust="")

        if df is not None and not df.empty:
            df = df.rename(columns={
                "day": "datetime",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            })
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        _cache[cache_key] = df
        return df
    except Exception as e:
        logger.error(f"AkShare获取ETF分钟数据失败 {code}: {e}")
        return pd.DataFrame()


def get_etf_realtime_quote(code: str) -> Optional[dict]:
    try:
        quotes = get_realtime_quotes([code])
        return quotes[0] if quotes else None
    except Exception as e:
        logger.error(f"AkShare获取ETF实时行情失败 {code}: {e}")
        return None


def get_realtime_quotes(codes: List[str]) -> List[dict]:
    if not codes:
        return []

    try:
        df = _get_etf_spot_df(timeout=3)
        if df is None or df.empty:
            return []

        code_col = _find_column(df, "代码")
        if code_col is None:
            return []

        spot_lookup = {}
        for _, row in df.iterrows():
            spot_lookup[str(row.get(code_col, "")).zfill(6)] = row

        results = []
        for code in codes:
            row = spot_lookup.get(str(code).zfill(6))
            if row is not None:
                results.append(_normalize_spot_row(row, code))
        return results
    except Exception as e:
        logger.error(f"AkShare批量获取ETF实时行情失败: {e}")
        return []


def get_tencent_realtime_quote(code: str, timeout: int = 8) -> Optional[dict]:
    """腾讯轻量单点实时行情（qt.gtimg.cn），个股/ETF 通用。

    用作盘中日K实时补充的主源：pytdx 的 get_security_quotes 对 ETF/基金存在已知
    小数点解析问题——price 与昨收被整体放大 10 倍（实测 510300 真实 4.66 返回 46.5），
    会导致合成的当天 bar 被合理性校验丢弃、日K无法补充当天实时K线。腾讯接口对
    个股与 ETF 报价均准确，且为单点轻量请求，适合盘中高频补充。

    注意：指数代码（如 000001 上证指数）在 _get_tencent_prefix 里会被判为 sz 前缀
    （应为 sh），因此指数不要走本函数，继续用 pytdx。

    返回归一化 dict：{code, price, open, high, low, pre_close, volume, amount}，
    字段与 pytdx_data.get_realtime_quotes 保持一致；取不到返回 None。
    """
    code = str(code).strip().zfill(6)
    cached = _tencent_quote_cache.get(code)
    if cached is not None:
        return cached
    symbol = f"{_get_tencent_prefix(code)}{code}"
    try:
        text = _fetch_tencent_quote_text([symbol], timeout=min(timeout, 10))
        rows = _parse_tencent_quote_text(text)
    except Exception as e:
        logger.error(f"腾讯实时行情失败 {code}: {e}")
        return None
    for row in rows or []:
        if str(row.get("代码", "")).zfill(6) == code:
            quote = {
                "code": code,
                "price": row.get("最新价"),
                "open": row.get("今开"),
                "high": row.get("最高"),
                "low": row.get("最低"),
                "pre_close": row.get("昨收"),
                "volume": row.get("成交量"),
                "amount": row.get("成交额"),
            }
            _tencent_quote_cache[code] = quote
            return quote
    return None


def get_all_etf_realtime() -> pd.DataFrame:
    try:
        df = _get_etf_spot_df(timeout=5)
        if df is None or df.empty:
            return pd.DataFrame()
        normalized_rows = [_normalize_spot_row(row) for _, row in df.iterrows()]
        return pd.DataFrame(normalized_rows)
    except Exception as e:
        logger.error(f"AkShare获取ETF实时行情列表失败: {e}")
        return pd.DataFrame()


def search_etf_akshare(keyword: str, limit: int = 20) -> list:
    cache_key = f"search_{keyword}_{limit}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        keyword = keyword.strip()
        if not keyword:
            return []

        df = _get_etf_spot_df(timeout=2)
        results = []
        existing_codes = set()

        if df is not None and not df.empty:
            code_col = _find_column(df, "代码")
            name_col = _find_column(df, "名称")
            if code_col and name_col:
                mask = (
                    df[code_col].astype(str).str.contains(keyword, case=False, na=False)
                    | df[name_col].astype(str).str.contains(keyword, case=False, na=False)
                )
                filtered = df[mask].head(limit)
                for _, row in filtered.iterrows():
                    item = _normalize_spot_row(row)
                    results.append(item)
                    existing_codes.add(item["code"])

        if len(results) < limit:
            fund_df = _get_fund_name_df(timeout=5)
            if fund_df is not None and not fund_df.empty:
                code_col = _find_column(fund_df, "基金代码")
                name_col = _find_column(fund_df, "基金简称")
                type_col = _find_column(fund_df, "基金类型")
                pinyin_short_col = _find_column(fund_df, "拼音缩写")
                pinyin_full_col = _find_column(fund_df, "拼音全称")

                if code_col and name_col:
                    exact_code_lookup = keyword.isdigit() and len(keyword) == 6
                    mask = (
                        fund_df[code_col].astype(str).str.contains(keyword, case=False, na=False)
                        | fund_df[name_col].astype(str).str.contains(keyword, case=False, na=False)
                    )
                    if pinyin_short_col:
                        mask = mask | fund_df[pinyin_short_col].astype(str).str.contains(keyword, case=False, na=False)
                    if pinyin_full_col:
                        mask = mask | fund_df[pinyin_full_col].astype(str).str.contains(keyword, case=False, na=False)

                    filtered = fund_df[mask]

                    for _, row in filtered.head(limit * 2).iterrows():
                        code = str(row.get(code_col, "")).zfill(6)
                        if not code or code in existing_codes:
                            continue
                        name = str(row.get(name_col, "") or code)
                        fund_type = str(row.get(type_col, "")) if type_col else ""
                        if not _is_exchange_traded_candidate(name, fund_type):
                            continue
                        results.append({
                            "code": code,
                            "name": name,
                            "market": get_market_code(code),
                        })
                        existing_codes.add(code)
                        if len(results) >= limit:
                            break

        _cache[cache_key] = results
        return results[:limit]
    except Exception as e:
        logger.error(f"AkShare搜索ETF失败: {e}")
        return []


def search_stock_code_name(keyword: str, limit: int = 20) -> list:
    cache_key = f"stock_search_{keyword}_{limit}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        keyword = keyword.strip()
        if not keyword:
            return []

        results = []
        seen_codes = set()

        spot_df = _get_stock_spot_df(timeout=5)
        if spot_df is not None and not spot_df.empty:
            code_col = _find_column(spot_df, "代码")
            name_col = _find_column(spot_df, "名称")
            if code_col and name_col:
                mask = (
                    spot_df[code_col].astype(str).str.contains(keyword, case=False, na=False)
                    | spot_df[name_col].astype(str).str.contains(keyword, case=False, na=False)
                )
                for _, row in spot_df[mask].head(limit).iterrows():
                    item = _normalize_stock_spot_row(row)
                    results.append(item)
                    seen_codes.add(item["code"])

        if len(results) < limit:
            df = _get_stock_name_df(timeout=20)
            if df is not None and not df.empty:
                code_col = _find_column(df, "code", "代码")
                name_col = _find_column(df, "name", "名称")
                if code_col and name_col:
                    mask = (
                        df[code_col].astype(str).str.contains(keyword, case=False, na=False)
                        | df[name_col].astype(str).str.contains(keyword, case=False, na=False)
                    )
                    filtered = df[mask].head(limit * 2)
                    for _, row in filtered.iterrows():
                        code = str(row.get(code_col, "")).zfill(6)
                        if not code or code in seen_codes:
                            continue
                        results.append(
                            {
                                "code": code,
                                "name": str(row.get(name_col, "") or code),
                                "market": get_market_code(code),
                            }
                        )
                        seen_codes.add(code)
                        if len(results) >= limit:
                            break
        _cache[cache_key] = results
        return results[:limit]
    except Exception as e:
        logger.error(f"AkShare搜索A股代码名称失败: {e}")
        return []


def search_major_indices(keyword: str, limit: int = 20) -> list:
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return []
    results = []
    for item in MAJOR_INDEXES:
        if keyword in item["code"].lower() or keyword in item["name"].lower():
            results.append(dict(item))
            if len(results) >= limit:
                break
    return results


def get_stock_name_by_code(code: str) -> Optional[str]:
    code = str(code).strip().zfill(6)
    for source in STOCK_NAME_SOURCE_PRIORITY:
        if source == "akshare":
            try:
                df = _get_stock_name_df(timeout=20)
                if df is None or df.empty:
                    continue

                code_col = _find_column(df, "code", "代码")
                name_col = _find_column(df, "name", "名称")
                if not code_col or not name_col:
                    continue

                matched = df[df[code_col].astype(str).str.zfill(6) == code]
                if matched.empty:
                    continue

                name = str(matched.iloc[0].get(name_col, "") or "")
                if name:
                    return name
            except Exception as e:
                logger.error(f"AkShare按代码获取A股名称失败 {code}: {e}")
        elif source == "pytdx":
            pytdx_name = _get_pytdx_stock_name_map().get(code)
            if pytdx_name:
                return pytdx_name
    return None


def get_stock_spot_detail(code: str) -> Optional[dict]:
    code = str(code).strip().zfill(6)
    try:
        quotes = pytdx_data.get_realtime_quotes([code])
        if quotes:
            quote = quotes[0]
            price = _safe_float(quote.get("price"), nullable=True)
            finance_info = pytdx_data.get_finance_info(code)
            total_shares = _safe_float(finance_info.get("zongguben") if finance_info else None, nullable=True)
            circ_shares = _safe_float(finance_info.get("liutongguben") if finance_info else None, nullable=True)
            name = str(quote.get("name") or "").strip() or get_stock_name_by_code(code) or code
            detail = {
                "code": code,
                "name": name,
                "price": price,
                "change_pct": _safe_float(quote.get("change_pct"), nullable=True),
                "change": _safe_float(quote.get("change"), nullable=True),
                "volume": _safe_float(quote.get("volume"), nullable=True),
                "amount": _safe_float(quote.get("amount"), nullable=True),
                "open": _safe_float(quote.get("open"), nullable=True),
                "high": _safe_float(quote.get("high"), nullable=True),
                "low": _safe_float(quote.get("low"), nullable=True),
                "prev_close": _safe_float(quote.get("pre_close"), nullable=True),
                "turnover_rate": None,
                "total_mv": price * total_shares if price is not None and total_shares is not None else None,
                "circ_mv": price * circ_shares if price is not None and circ_shares is not None else None,
                "industry": None,
                "market": get_market_code(code),
            }
            detail["industry"] = get_stock_industry(code)
            return detail
    except Exception as e:
        logger.warning(f"pytdx获取A股详情失败，回退AkShare {code}: {e}")
    try:
        df = _get_stock_spot_df(timeout=5)
        if df is None or df.empty:
            return None
        code_col = _find_column(df, "代码")
        if not code_col:
            return None
        matched = df[df[code_col].astype(str).str.zfill(6) == code]
        if matched.empty:
            return None
        detail = _normalize_stock_spot_row(matched.iloc[0], code)
        if not detail.get("industry"):
            detail["industry"] = get_stock_industry(code)
        return detail
    except Exception as e:
        logger.error(f"AkShare获取A股详情失败 {code}: {e}")
        return None


def get_stock_industry(code: str) -> Optional[str]:
    code = str(code).strip().zfill(6)
    if not code:
        return None
    for source in INDUSTRY_SOURCE_PRIORITY:
        if source == "cninfo":
            industry = _get_stock_industry_from_cninfo(code)
            if industry:
                return industry
        elif source == "sina":
            industry_map = _get_stock_industry_map_from_sina()
            if industry_map.get(code):
                return industry_map.get(code)
    return None


def get_all_a_share_spot() -> pd.DataFrame:
    def save_snapshot(rows: list[dict]):
        if not db._db_initialized:
            ensure_runtime_db_ready()
        db.replace_a_share_spot_snapshot(rows)

    def load_snapshot() -> pd.DataFrame:
        if not db._db_initialized:
            ensure_runtime_db_ready()
        return pd.DataFrame(db.list_a_share_spot_snapshot())

    try:
        source_rows: list[list[dict]] = []

        try:
            name_df = _get_stock_name_df(timeout=20)
            if name_df is not None and not name_df.empty:
                source_rows.append([_normalize_stock_spot_row(row) for _, row in name_df.iterrows()])
                logger.info(f"获取A股代码名称列表: {len(name_df)} 条")
        except Exception as e:
            logger.warning(f"A股代码名称列表获取失败: {e}")

        for source in MARKET_SPOT_SOURCE_PRIORITY:
            try:
                df = _fetch_stock_spot_by_source(source, timeout=8)
                if df is not None and not df.empty:
                    source_rows.append([_normalize_stock_spot_row(row) for _, row in df.iterrows()])
            except Exception as e:
                _log_fetch_issue(
                    "A股现货源获取",
                    e,
                    source=source,
                    transient_level=logging.WARNING,
                    default_level=logging.WARNING,
                )

        normalized_rows = _merge_normalized_rows(source_rows)
        if not normalized_rows:
            snapshot_df = load_snapshot()
            if not snapshot_df.empty:
                logger.warning("AkShare A股现货列表为空，回退使用本地快照")
                return snapshot_df
            return pd.DataFrame()

        snapshot_df = load_snapshot()
        if not snapshot_df.empty and len(snapshot_df) > len(normalized_rows):
            normalized_rows = _merge_normalized_rows([normalized_rows, snapshot_df.to_dict("records")])

        industry_map = _get_stock_industry_map_from_sina()
        if industry_map:
            for item in normalized_rows:
                if str(item.get("security_type", "stock")).lower() != "stock":
                    continue
                code = str(item.get("code", "")).zfill(6)
                item["industry"] = _optional_text(item.get("industry"))
                if code and item.get("industry") is None:
                    item["industry"] = industry_map.get(code)

        save_snapshot(normalized_rows)
        return pd.DataFrame(normalized_rows)
    except Exception as e:
        logger.error(f"AkShare获取A股现货列表失败: {e}")
        snapshot_df = load_snapshot()
        if not snapshot_df.empty:
            logger.warning("AkShare获取A股现货列表失败，回退使用本地快照")
            return snapshot_df
        return pd.DataFrame()


def get_major_index_quotes(codes: Optional[list[str]] = None) -> list[dict]:
    code_set = {str(code).zfill(6) for code in codes} if codes else None
    requested_codes = [
        str(item["code"]).zfill(6)
        for item in MAJOR_INDEXES
        if code_set is None or str(item["code"]).zfill(6) in code_set
    ]
    meta_map = {str(item["code"]).zfill(6): item for item in MAJOR_INDEXES}
    try:
        quotes = pytdx_data.get_realtime_quotes(requested_codes)
        if quotes:
            quote_map = {str(item.get("code", "")).zfill(6): item for item in quotes}
            results = []
            for code in requested_codes:
                quote = quote_map.get(code)
                if not quote:
                    continue
                meta = meta_map.get(code, {})
                results.append(
                    {
                        "code": code,
                        "name": str(quote.get("name") or meta.get("name") or code),
                        "price": _safe_float(quote.get("price"), nullable=True),
                        "change_pct": _safe_float(quote.get("change_pct"), nullable=True),
                        "change": _safe_float(quote.get("change"), nullable=True),
                        "market": int(meta.get("market", get_market_code(code))),
                    }
                )
            if results:
                return results
    except Exception as e:
        logger.warning(f"pytdx获取主要指数行情失败，回退备用源: {e}")
    try:
        df = _get_index_spot_df(timeout=5)
        if df is None or df.empty:
            return []
        code_col = _find_column(df, "代码")
        name_col = _find_column(df, "名称")
        price_col = _find_column(df, "最新价", "最新点位")
        change_pct_col = _find_column(df, "涨跌幅")
        change_col = _find_column(df, "涨跌额")
        if not code_col or not name_col or not price_col:
            return []

        results = []
        for _, row in df.iterrows():
            code = str(row.get(code_col, "")).zfill(6)
            if not code:
                continue
            if code_set and code not in code_set:
                continue
            matched_meta = next((item for item in MAJOR_INDEXES if item["code"] == code), None)
            results.append({
                "code": code,
                "name": str(row.get(name_col, "") or (matched_meta["name"] if matched_meta else code)),
                "price": _safe_float(row.get(price_col), nullable=True),
                "change_pct": _safe_float(row.get(change_pct_col), nullable=True),
                "change": _safe_float(row.get(change_col), nullable=True),
                "market": matched_meta["market"] if matched_meta else get_market_code(code),
            })
        return results
    except Exception as e:
        logger.error(f"AkShare获取主要指数行情失败: {e}")
        return []


def _get_recent_trade_dates(limit: int = 31) -> list[str]:
    try:
        trade_dates = ak.tool_trade_date_hist_sina()
        if trade_dates is None or trade_dates.empty:
            return []

        date_col = _find_column(trade_dates, "trade_date", "日期")
        if not date_col:
            return []

        normalized = (
            pd.to_datetime(trade_dates[date_col], errors="coerce", utc=True)
            .dropna()
            .dt.strftime("%Y%m%d")
            .tolist()
        )
        if not normalized:
            return []
        return normalized[-limit:]
    except Exception as e:
        logger.error(f"AkShare获取交易日历失败: {e}")
        return []


def get_margin_profile(code: str, window: int = 30) -> Optional[dict]:
    code = str(code).strip().zfill(6)
    cache_key = f"margin_profile_{code}_{int(window)}"
    if cache_key in _cache:
        return _cache[cache_key]

    if any(item["code"] == code for item in MAJOR_INDEXES) or not _is_margin_supported_security(code):
        return None

    market = get_market_code(code)
    fetch_dates = _get_recent_trade_dates(max(window + 1, 10))
    if not fetch_dates:
        return None

    series = []
    security_name = ""

    for trade_date in fetch_dates:
        try:
            detail_df = (
                ak.stock_margin_detail_sse(date=trade_date)
                if market == 1
                else ak.stock_margin_detail_szse(date=trade_date)
            )
        except Exception as e:
            if "Length mismatch" in str(e):
                logger.debug(f"融资融券明细为空或结构异常 {code} {trade_date}: {e}")
            else:
                logger.warning(f"获取融资融券明细失败 {code} {trade_date}: {e}")
            continue

        if detail_df is None or detail_df.empty:
            continue

        code_col = _find_column(detail_df, "标的证券代码", "证券代码")
        name_col = _find_column(detail_df, "标的证券简称", "证券简称")
        balance_col = _find_column(detail_df, "融资余额")
        buy_col = _find_column(detail_df, "融资买入额")
        if not code_col or not balance_col:
            continue

        matched = detail_df[detail_df[code_col].astype(str).str.zfill(6) == code]
        if matched.empty:
            continue

        row = matched.iloc[0]
        if not security_name and name_col:
            security_name = str(row.get(name_col, "") or "")

        balance_value = _safe_float(row.get(balance_col), nullable=True)
        buy_value = _safe_float(row.get(buy_col), nullable=True) if buy_col else None
        if balance_value is None:
            continue

        series.append(
            {
                "date": pd.to_datetime(trade_date, format="%Y%m%d", errors="coerce").strftime("%Y-%m-%d"),
                "financing_balance": balance_value,
                "financing_buy": buy_value,
            }
        )

    if not series:
        return None

    series = sorted(series, key=lambda item: item["date"])
    normalized_series = []
    previous_balance = None
    for item in series:
        current_balance = item["financing_balance"]
        net_inflow = (
            None
            if previous_balance is None
            else current_balance - previous_balance
        )
        normalized_series.append(
            {
                "date": item["date"],
                "financing_balance": current_balance,
                "financing_buy": item["financing_buy"],
                "net_inflow": net_inflow,
            }
        )
        previous_balance = current_balance

    latest = normalized_series[-1]
    valid_net_values = [item["net_inflow"] for item in normalized_series if item["net_inflow"] is not None]
    result = {
        "code": code,
        "name": security_name or code,
        "latest_trade_date": latest["date"],
        "latest_financing_balance": latest["financing_balance"],
        "latest_financing_buy": latest["financing_buy"],
        "latest_net_inflow": latest["net_inflow"],
        "rolling_net_inflow_30d": sum(valid_net_values) if valid_net_values else None,
        "positive_days_30d": sum(1 for value in valid_net_values if value > 0),
        "negative_days_30d": sum(1 for value in valid_net_values if value < 0),
        "series": normalized_series[-window:],
    }
    _cache[cache_key] = result
    return result


_trade_date_cache_set = None
_trade_date_cache_at = None
_trade_date_cache_ttl = 3600
_trade_date_refresh_lock = threading.Lock()


def _get_trade_date_set() -> Optional[set]:
    """缓存全年交易日集合(1小时)。is_trading_date 在扫描状态轮询里高频调用，
    不能每次都打新浪接口；失败返回 None，调用方退化为工作日判断。"""
    global _trade_date_cache_set, _trade_date_cache_at
    now = now_beijing()
    if (
        _trade_date_cache_set is not None
        and _trade_date_cache_at is not None
        and (now - _trade_date_cache_at).total_seconds() < _trade_date_cache_ttl
    ):
        return _trade_date_cache_set
    with _trade_date_refresh_lock:
        now = now_beijing()
        if (
            _trade_date_cache_set is not None
            and _trade_date_cache_at is not None
            and (now - _trade_date_cache_at).total_seconds() < _trade_date_cache_ttl
        ):
            return _trade_date_cache_set
        try:
            trade_dates = ak.tool_trade_date_hist_sina()
            if trade_dates is None or trade_dates.empty:
                return None
            date_col = _find_column(trade_dates, "trade_date", "日期")
            if not date_col:
                return None
            _trade_date_cache_set = set(
                pd.to_datetime(trade_dates[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
            )
            _trade_date_cache_at = now
            return _trade_date_cache_set
        except Exception:
            return None


def is_trading_date(date_value: Optional[datetime] = None) -> bool:
    target = pd.Timestamp(date_value or now_beijing()).strftime("%Y-%m-%d")
    cached = _get_trade_date_set()
    if cached is not None:
        return target in cached
    return pd.Timestamp(date_value or now_beijing()).weekday() < 5


def get_etf_detail(code: str, timeout: int = 10) -> Optional[dict]:
    try:
        row = _get_spot_row(code, _get_etf_spot_df(timeout=min(timeout, 5)))
        if row is not None:
            return _normalize_spot_row(row, code)

        fund_df = _get_fund_name_df(timeout=min(timeout, 5))
        if fund_df is None or fund_df.empty:
            return None

        code_col = _find_column(fund_df, "基金代码")
        name_col = _find_column(fund_df, "基金简称")
        type_col = _find_column(fund_df, "基金类型")
        if not code_col or not name_col:
            return None

        matched = fund_df[fund_df[code_col].astype(str).str.zfill(6) == str(code).zfill(6)]
        if matched.empty:
            return None

        row = matched.iloc[0]
        return {
            "code": str(code).zfill(6),
            "name": str(row.get(name_col, "") or code),
            "price": 0,
            "change_pct": 0,
            "change": 0,
            "volume": 0,
            "amount": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "prev_close": 0,
            "iopv": None,
            "premium_rate": None,
            "turnover_rate": None,
            "total_mv": None,
            "circ_mv": None,
            "market": get_market_code(code),
            "fund_type": str(row.get(type_col, "")) if type_col else "",
        }
    except FuturesTimeoutError:
        logger.error(f"AkShare获取ETF详情超时 {code}")
        return None
    except Exception as e:
        logger.error(f"AkShare获取ETF详情失败 {code}: {e}")
        return None


def get_cached_etf_detail(code: str) -> Optional[dict]:
    global _spot_cache_df

    if _spot_cache_df is None or _spot_cache_df.empty:
        return None

    try:
        row = _get_spot_row(code, _spot_cache_df)
        if row is None:
            return None
        return _normalize_spot_row(row, code)
    except Exception as e:
        logger.error(f"读取ETF详情缓存失败 {code}: {e}")
        return None
