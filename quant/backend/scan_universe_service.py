from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import pandas as pd

from backend import db
from backend.config import A_SHARE_LIST_SOURCE_PRIORITY, LOCAL_KLINE_CACHE_RULES
from backend.kline_parquet import get_kline_parquet
from backend.market import akshare_data, pytdx_data
from backend.security_service import ensure_runtime_db_ready
from backend.system_utils import get_optimal_worker_count

MIN_MARKET_CAP = 10_000_000_000
DAILY_MA_PERIOD = 144
MIN_DAILY_BARS = max(int(LOCAL_KLINE_CACHE_RULES.get("daily", {}).get("min_bars", 160)), DAILY_MA_PERIOD)
SCREENING_MAX_WORKERS = get_optimal_worker_count("io", max_limit=16)


def is_non_st_stock(name: str) -> bool:
    normalized = (name or "").upper().replace("*", "")
    return "ST" not in normalized


def is_not_delisted_stock(name: str) -> bool:
    normalized = str(name or "").strip().replace("*", "")
    return not (normalized.startswith("退") or "退市" in normalized)


def _safe_float(value, default: Optional[float] = None) -> Optional[float]:
    if value in ("", "-", "--", None):
        return default
    try:
        if pd.isna(value):
            return default
        parsed = float(value)
        if pd.isna(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


def _safe_text(value) -> Optional[str]:
    if value in ("", "-", "--", None):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _flag_is_true(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _normalize_source_item(item: dict) -> dict:
    code = str(item.get("code", "")).strip().zfill(6)
    name = str(item.get("name", "") or code)
    security_type = str(item.get("security_type", "stock") or "stock").lower()
    total_mv = _safe_float(item.get("total_mv"))
    raw_download_source = item.get("download_source")
    download_tags = db._download_source_tags(raw_download_source)

    normalized = {
        **item,
        "code": code,
        "name": name,
        "market": int(item.get("market", 1) or 1),
        "total_mv": total_mv,
        "industry": _safe_text(item.get("industry")),
        "security_type": security_type,
        "is_st": False,
        "is_delisted": False,
        "is_low_mv": False,
        "download_source": db._normalize_download_source(raw_download_source),
        "kline_downloaded": 1 if (item.get("kline_downloaded") or download_tags) else 0,
    }

    if security_type == "stock":
        normalized["is_st"] = _flag_is_true(item.get("is_st")) or not is_non_st_stock(name)
        normalized["is_delisted"] = _flag_is_true(item.get("is_delisted")) or not is_not_delisted_stock(name)
        normalized["is_low_mv"] = (
            _flag_is_true(item.get("is_low_mv"))
            or total_mv is None
            or total_mv <= MIN_MARKET_CAP
        )

    is_basic_eligible = _is_basic_download_candidate(normalized)
    normalized["scan_eligible"] = 1 if is_basic_eligible else 0
    normalized["ma144_passed"] = None if item.get("ma144_passed") is None else int(_flag_is_true(item.get("ma144_passed")))
    return normalized


def _is_basic_download_candidate(item: dict) -> bool:
    if str(item.get("security_type", "stock") or "stock").lower() != "stock":
        return True
    return not (
        item.get("is_st", False)
        or item.get("is_delisted", False)
        or item.get("is_low_mv", False)
    )


def _source_universe_stats(items: list[dict]) -> dict:
    stock_items = [item for item in items if str(item.get("security_type", "")).lower() == "stock"]
    etf_items = [item for item in items if str(item.get("security_type", "")).lower() == "etf"]
    index_items = [item for item in items if str(item.get("security_type", "")).lower() == "index"]
    eligible_stock_count = sum(1 for item in stock_items if _is_basic_download_candidate(item))

    return {
        "raw_total_count": len(items),
        "raw_stock_count": len(stock_items),
        "raw_etf_count": len(etf_items),
        "raw_index_count": len(index_items),
        "removed_st_count": sum(1 for item in stock_items if item.get("is_st")),
        "removed_market_cap_count": sum(1 for item in stock_items if item.get("is_low_mv")),
        "removed_delisted_count": sum(1 for item in stock_items if item.get("is_delisted")),
        "eligible_stock_count": eligible_stock_count,
        "basic_candidate_count": eligible_stock_count + len(etf_items) + len(index_items),
    }


def _save_rule_download_universe_snapshot(items: list[dict]):
    # 兼容旧调用，现已不再写入规则快照。
    return len(items)


def _save_manual_download_universe_snapshot(items: list[dict]):
    # 兼容旧调用，现已不再写入手动快照。
    return len(items)


def load_download_universe_snapshot() -> list[dict]:
    if not db._db_initialized:
        ensure_runtime_db_ready()
    return db.list_stock_pool(scan_eligible_only=True)


def mark_manual_download_candidates(items: list[dict]) -> int:
    _save_manual_download_universe_snapshot(items)
    if not db._db_initialized:
        ensure_runtime_db_ready()
    return db.upsert_manual_download_universe(items)


def load_download_source_universe(
    progress_callback: Optional[Callable[[dict], None]] = None,
    force_refresh: bool = False,
) -> list[dict]:
    if not db._db_initialized:
        ensure_runtime_db_ready()
    cached_items = []
    if cached_items:
        cached_items = [_normalize_source_item(item) for item in cached_items]
        db.replace_download_source_universe(cached_items)
        stats = _source_universe_stats(cached_items)
        if progress_callback:
            progress_callback(
                {
                    "stage": "collecting",
                    "message": (
                        f"第1步已完成初始化，直接使用数据库中的基础股票池 {len(cached_items)} 个，"
                        f"标记 ST {stats['removed_st_count']} 个、市值不足 {stats['removed_market_cap_count']} 个、"
                        f"退市 {stats['removed_delisted_count']} 个，"
                        f"第2步将下载 {stats['basic_candidate_count']} 个标的。"
                    ),
                    **stats,
                    "a_share_fetched_count": stats["raw_stock_count"],
                    "qualified_count": stats["basic_candidate_count"],
                    "current_index": 0,
                    "total_count": stats["basic_candidate_count"],
                }
            )
        return cached_items

    if progress_callback:
        progress_callback(
            {
                "stage": "collecting",
                "message": "第1步：开始获取A股、ETF、指数，并筛出基础股票池...",
                "raw_total_count": 0,
                "raw_stock_count": 0,
                "raw_etf_count": 0,
                "raw_index_count": 0,
            }
        )

    stock_items: list[dict] = []
    raw_stock_rows: list[dict] = []
    source_candidates = _load_base_candidates_from_sources()
    if source_candidates:
        for item in source_candidates:
            code = str(item.get("code", "")).zfill(6)
            name = str(item.get("name", "") or code)
            total_mv = _safe_float(item.get("total_mv"))
            if not code:
                continue
            is_st = not is_non_st_stock(name)
            is_delisted = not is_not_delisted_stock(name)
            is_low_mv = total_mv is None or total_mv <= MIN_MARKET_CAP
            stock_items.append(
                {
                    "code": code,
                    "name": name,
                    "market": int(item.get("market", 1)),
                    "total_mv": total_mv,
                    "industry": _safe_text(item.get("industry")),
                    "security_type": "stock",
                    "is_st": is_st,
                    "is_delisted": is_delisted,
                    "is_low_mv": is_low_mv,
                }
            )
        raw_stock_rows = list(source_candidates)
    if raw_stock_rows:
        if progress_callback:
            progress_callback(
                {
                    "stage": "collecting",
                    "message": f"第1步：正在获取A股股票池中，已经获取 {len(raw_stock_rows)} 个。",
                    "a_share_fetched_count": len(raw_stock_rows),
                    "raw_total_count": len(raw_stock_rows),
                    "raw_stock_count": 0,
                    "raw_etf_count": 0,
                    "raw_index_count": 0,
                    "removed_st_count": 0,
                    "removed_market_cap_count": 0,
                    "removed_delisted_count": 0,
                    "qualified_count": 0,
                    "current_index": 0,
                    "total_count": len(raw_stock_rows),
                }
            )

    if progress_callback:
        qualified_count = sum(
            1 for item in stock_items
            if not item.get("is_st") and not item.get("is_delisted") and not item.get("is_low_mv")
        )
        progress_callback(
            {
                "stage": "collecting",
                "message": (
                    f"第1步：股票池共 {len(stock_items)} 个（合格 {qualified_count} 个），"
                    "开始补充ETF和指数..."
                ),
                "a_share_fetched_count": len(stock_items),
                "raw_total_count": len(stock_items),
                "raw_stock_count": len(stock_items),
                "raw_etf_count": 0,
                "raw_index_count": 0,
            }
        )

    etf_items: list[dict] = []
    etf_df = akshare_data.get_all_etf_realtime()
    if etf_df is not None and not etf_df.empty:
        for _, row in etf_df.iterrows():
            code = str(row.get("code", "")).zfill(6)
            if not code:
                continue
            etf_items.append(
                {
                    "code": code,
                    "name": str(row.get("name", "") or code),
                    "market": int(row.get("market", 1)),
                    "total_mv": _safe_float(row.get("total_mv")),
                    "security_type": "etf",
                    "is_st": False,
                    "is_delisted": False,
                    "is_low_mv": False,
                }
            )

    index_items = [
        {
            "code": str(item["code"]).zfill(6),
            "name": str(item.get("name", "") or item["code"]),
            "market": int(item.get("market", 1)),
            "total_mv": None,
            "security_type": "index",
            "is_st": False,
            "is_delisted": False,
            "is_low_mv": False,
        }
        for item in akshare_data.MAJOR_INDEXES
    ]

    raw_total_count = len(stock_items) + len(etf_items) + len(index_items)
    final_removed_st = sum(1 for item in stock_items if item.get("is_st"))
    final_removed_market_cap = sum(1 for item in stock_items if item.get("is_low_mv"))
    final_removed_delisted = sum(1 for item in stock_items if item.get("is_delisted"))
    eligible_stock_count = sum(
        1 for item in stock_items
        if not item.get("is_st") and not item.get("is_delisted") and not item.get("is_low_mv")
    )
    basic_candidate_count = eligible_stock_count + len(etf_items) + len(index_items)
    if progress_callback:
        progress_callback(
            {
                "stage": "collecting",
                "message": (
                    f"第1步完成：全量入库 {raw_total_count} 个（股票 {len(stock_items)} 个、ETF {len(etf_items)} 个、指数 {len(index_items)} 个），"
                    f"标记 ST {final_removed_st} 个、市值不足 {final_removed_market_cap} 个、退市 {final_removed_delisted} 个，"
                    f"待验证144均线 {eligible_stock_count} 个。"
                ),
                "raw_total_count": raw_total_count,
                "raw_stock_count": len(stock_items),
                "raw_etf_count": len(etf_items),
                "raw_index_count": len(index_items),
                "a_share_fetched_count": len(raw_stock_rows) if raw_stock_rows else len(stock_items),
                "removed_st_count": final_removed_st,
                "removed_market_cap_count": final_removed_market_cap,
                "removed_delisted_count": final_removed_delisted,
                "eligible_stock_count": eligible_stock_count,
                "qualified_count": basic_candidate_count,
                "current_index": raw_total_count,
                "total_count": raw_total_count,
            }
        )

    items = [*stock_items, *etf_items, *index_items]
    for item in items:
        is_stock_eligible = (
            not item.get("is_st", False)
            and not item.get("is_delisted", False)
            and not item.get("is_low_mv", False)
        )
        if item.get("security_type") != "stock":
            item["scan_eligible"] = 1
        else:
            item["scan_eligible"] = 1 if is_stock_eligible else 0
    db.replace_download_source_universe(items)
    return items


def _load_base_candidates_from_pytdx() -> list[dict]:
    base_items = pytdx_data.list_all_a_share_candidates()
    if not base_items:
        return []

    quotes_map: dict[str, dict] = {}
    codes = [item["code"] for item in base_items]
    for start in range(0, len(codes), 80):
        chunk = codes[start:start + 80]
        for quote in pytdx_data.get_realtime_quotes(chunk):
            quotes_map[str(quote.get("code", "")).zfill(6)] = quote

    candidates = []
    for item in base_items:
        code = str(item["code"]).zfill(6)
        name = str(item.get("name", "") or code)
        if not is_non_st_stock(name):
            continue

        quote = quotes_map.get(code, {})
        finance_info = pytdx_data.get_finance_info(code)
        total_shares = _safe_float(finance_info.get("zongguben") if finance_info else None)
        price = _safe_float(quote.get("price"))
        total_mv = price * total_shares if price and total_shares else None
        if total_mv is None or total_mv <= MIN_MARKET_CAP:
            continue

        candidates.append(
            {
                "code": code,
                "name": name,
                "market": int(item.get("market", 1)),
                "total_mv": float(total_mv),
            }
        )
    return candidates


def _load_base_candidates_from_akshare_spot() -> list[dict]:
    spot_df = akshare_data.get_all_a_share_spot()
    if spot_df is None or spot_df.empty:
        return []

    candidates = []
    for _, row in spot_df.iterrows():
        code = str(row.get("code", "")).zfill(6)
        name = str(row.get("name", "") or code)
        total_mv = _safe_float(row.get("total_mv"))
        if not code or not is_non_st_stock(name):
            continue
        if total_mv is None or total_mv <= MIN_MARKET_CAP:
            continue
        candidates.append(
            {
                "code": code,
                "name": name,
                "market": int(row.get("market", 1)),
                "total_mv": float(total_mv),
                "industry": _safe_text(row.get("industry")),
            }
        )
    return candidates


def _load_base_candidates_from_sources() -> list[dict]:
    for source in A_SHARE_LIST_SOURCE_PRIORITY:
        try:
            if source == "akshare_spot":
                candidates = _load_base_candidates_from_akshare_spot()
            elif source == "pytdx":
                candidates = _load_base_candidates_from_pytdx()
            else:
                continue
            if candidates:
                return candidates
        except Exception:
            continue
    return []


def load_base_scan_candidates() -> list[dict]:
    return _load_base_candidates_from_sources()


def passes_daily_ma_filter(code: str, force_refresh: bool = False) -> bool:
    return passes_security_daily_ma_filter(code=code, security_type="stock", force_refresh=force_refresh)


def passes_security_daily_ma_filter(code: str, security_type: str = "stock", force_refresh: bool = False) -> bool:
    df = get_kline_parquet(code, "daily", limit=MIN_DAILY_BARS)
    if df is None or df.empty or len(df) < DAILY_MA_PERIOD:
        return False

    work_df = df.copy()
    work_df["close"] = pd.to_numeric(work_df["close"], errors="coerce")
    work_df["ma144"] = work_df["close"].rolling(window=DAILY_MA_PERIOD).mean()
    work_df = work_df.dropna(subset=["close", "ma144"])
    if work_df.empty:
        return False
    latest = work_df.iloc[-1]
    return float(latest["close"]) > float(latest["ma144"])


def build_download_universe(
    progress_callback: Optional[Callable[[dict], None]] = None,
    force_refresh: bool = False,
) -> list[dict]:
    raw_items = [
        _normalize_source_item(item)
        for item in load_download_source_universe(progress_callback=progress_callback, force_refresh=force_refresh)
    ]
    stats = _source_universe_stats(raw_items)
    candidates = [item for item in raw_items if _is_basic_download_candidate(item)]
    if progress_callback:
        progress_callback(
            {
                "stage": "collecting",
                "current_index": len(candidates),
                "total_count": len(candidates),
                "qualified_count": len(candidates),
                **stats,
                "message": (
                    f"第1步完成：全量入库 {stats['raw_total_count']} 个，"
                    f"剔除 ST {stats['removed_st_count']} 个、市值不足 {stats['removed_market_cap_count']} 个、"
                    f"退市 {stats['removed_delisted_count']} 个后，"
                    f"第2步下载 {len(candidates)} 个标的历史K线。"
                ),
            }
        )
    return candidates


def finalize_rule_download_universe(
    items: list[dict],
    progress_callback: Optional[Callable[[dict], None]] = None,
    force_refresh: bool = False,
) -> list[dict]:
    if not items:
        _save_rule_download_universe_snapshot([])
        db.recalculate_scan_eligible()
        return []

    qualified: list[dict] = []
    total_stock_count = sum(1 for item in items if str(item.get("security_type", "stock")) == "stock")
    total_index_count = sum(1 for item in items if str(item.get("security_type", "stock")) == "index")
    total_etf_count = sum(1 for item in items if str(item.get("security_type", "stock")) == "etf")

    def screen_one(item: dict) -> tuple[dict, bool]:
        is_ma144_passed = False
        if item.get("is_st") or item.get("is_delisted") or item.get("is_low_mv"):
            return item, is_ma144_passed
        is_ma144_passed = passes_security_daily_ma_filter(
            code=item["code"],
            security_type=str(item.get("security_type", "stock") or "stock"),
            force_refresh=force_refresh,
        )
        return item, is_ma144_passed

    max_workers = max(1, min(SCREENING_MAX_WORKERS, len(items) or 1))
    ma144_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(screen_one, item): item for item in items}
        completed = 0
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            completed += 1
            try:
                result_item, is_ma144_passed = future.result()
                ma144_rows.append({"code": item["code"], "ma144_passed": 1 if is_ma144_passed else 0})
                if is_ma144_passed:
                    qualified.append({
                        "code": item["code"],
                        "name": item["name"],
                        "market": int(item.get("market", 1)),
                        "total_mv": _safe_float(item.get("total_mv")),
                        "security_type": str(item.get("security_type", "stock") or "stock"),
                        "ma144_passed": 1,
                    })
            except Exception:
                pass
            if progress_callback:
                progress_callback(
                    {
                        "stage": "finalizing",
                        "current_index": completed,
                        "total_count": len(items),
                        "code": item["code"],
                        "name": item["name"],
                        "qualified_count": len(qualified),
                        "removed_ma_count": completed - len(qualified),
                        "final_stock_count": sum(1 for row in qualified if row["security_type"] == "stock"),
                        "final_index_count": sum(1 for row in qualified if row["security_type"] == "index"),
                        "final_etf_count": sum(1 for row in qualified if row["security_type"] == "etf"),
                        "raw_total_count": len(items),
                        "message": (
                            f"第3步：并行验证日线144均线，去除不符合条件股票 {completed - len(qualified)} 个，"
                            f"当前最终可扫描股票池 {len(qualified)} 个"
                        ),
                    }
                )

    _save_rule_download_universe_snapshot(qualified)
    db.update_ma144_flags_batch(ma144_rows)
    db.recalculate_scan_eligible()
    if progress_callback:
        progress_callback(
            {
                "stage": "finalizing",
                "current_index": len(items),
                "total_count": len(items),
                "qualified_count": len(qualified),
                "removed_ma_count": len(items) - len(qualified),
                "final_stock_count": sum(1 for row in qualified if row["security_type"] == "stock"),
                "final_index_count": sum(1 for row in qualified if row["security_type"] == "index"),
                "final_etf_count": sum(1 for row in qualified if row["security_type"] == "etf"),
                "source_stock_count": total_stock_count,
                "source_index_count": total_index_count,
                "source_etf_count": total_etf_count,
                "message": (
                    f"第3步完成：并行验证日线站上144均线股票 {len(items) - len(qualified)} 个，"
                    f"最终可扫描股票 {len(qualified)} 个，"
                    f"{sum(1 for row in qualified if row['security_type'] == 'stock')} 个股票，"
                    f"{sum(1 for row in qualified if row['security_type'] == 'index')} 个指数，"
                    f"{sum(1 for row in qualified if row['security_type'] == 'etf')} 个ETF。"
                ),
            }
        )
    return qualified
