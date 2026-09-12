from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from backend import db
from backend.config import (
    DOWNLOADABLE_KLINE_PERIODS,
    HISTORY_DOWNLOAD_DEFAULT_PERIODS,
    HISTORY_DOWNLOAD_PERIOD_OPTIONS,
    LOCAL_KLINE_CACHE_RULES,
)
from backend.kline_service import ensure_local_kline_cache, get_local_history_ready, normalize_period
from backend.kline_parquet import get_kline_sync_state
from backend.market import akshare_data
from backend.paths import ensure_log_dir
from backend.scan_universe_service import (
    MIN_MARKET_CAP,
    build_download_universe,
    is_non_st_stock,
    is_not_delisted_stock,
    passes_security_daily_ma_filter,
    load_download_universe_snapshot,
    mark_manual_download_candidates,
)
from backend.system_utils import get_optimal_worker_count, get_runtime_info
from backend.time_utils import now_beijing


_executor = ThreadPoolExecutor(max_workers=1)
_download_executor = ThreadPoolExecutor(max_workers=get_optimal_worker_count("io", max_limit=32))
_RECENT_COMPLETION_WINDOW = 100
_state_lock = threading.Lock()
_state = {
    "running": False,
    "periods": list(HISTORY_DOWNLOAD_DEFAULT_PERIODS),
    "stage": "idle",
    "target_mode": "filtered",
    "requested_code_count": 0,
    "raw_total_count": 0,
    "raw_stock_count": 0,
    "raw_etf_count": 0,
    "raw_index_count": 0,
    "a_share_fetched_count": 0,
    "removed_st_count": 0,
    "removed_market_cap_count": 0,
    "removed_delisted_count": 0,
    "eligible_stock_count": 0,
    "removed_ma_count": 0,
    "final_stock_count": 0,
    "final_etf_count": 0,
    "final_index_count": 0,
    "qualified_count": 0,
    "current_period": "",
    "current_code": "",
    "current_name": "",
    "current_index": 0,
    "total_count": 0,
    "ready_count": 0,
    "progress_pct": 0,
    "current_message": "",
    "selection_index": 0,
    "selection_total_count": 0,
    "last_started_at": "",
    "last_finished_at": "",
    "error": "",
    "time_span": "1m",
    "estimated_remaining_seconds": 0,
    "current_download_date": "",
    "download_start_time": None,
    "recent_completion_times": [],
    "trigger_source": "manual",
}
_auto_download_state = {
    "enabled": False,
    "hour": 15,
    "check_interval_seconds": 600,
    "last_checked_at": "",
    "next_check_at": "",
    "today": "",
    "today_started": False,
    "today_done": False,
    "status": "idle",
}


def _build_history_logger() -> logging.Logger:
    logger = logging.getLogger("history_download")
    logger.setLevel(logging.INFO)
    logger.propagate = True

    log_file = ensure_log_dir() / "history_download.log"
    existing_files = {
        getattr(handler, "baseFilename", "")
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    }
    if str(log_file) not in existing_files:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(file_handler)
    return logger


_history_logger = _build_history_logger()
_app_logger = logging.getLogger(__name__)


def _now_text() -> str:
    return now_beijing().strftime("%Y-%m-%d %H:%M:%S")


_TIME_SPAN_DAYS = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "2y": 730,
    "3y": 1095,
}


def _get_bars_for_time_span(period: str, time_span: str) -> int:
    days = _TIME_SPAN_DAYS.get(time_span, 30)
    period_bars_map = {
        "1min": days * 240,
        "5min": days * 48,
        "15min": days * 16,
        "30min": days * 8,
        "60min": days * 4,
        "daily": days,
        "weekly": days // 5,
        "monthly": days // 30,
    }
    return period_bars_map.get(period, days)


def _build_kline_metadata_row(item: dict) -> dict:
    code = str(item.get("code", "")).strip().zfill(6)
    periods_found = []
    time_span_map = {}
    ma144_passed = item.get("ma144_passed") if item.get("ma144_checked") else None

    for period in DOWNLOADABLE_KLINE_PERIODS:
        state = get_kline_sync_state(code, period)
        if state and int(state.get("bar_count") or 0) > 0:
            periods_found.append(period)
            first_bar = state.get("first_bar_time")
            last_bar = state.get("last_bar_time")
            if first_bar and last_bar:
                time_span_map[period] = {
                    "first_bar": first_bar,
                    "last_bar": last_bar,
                    "bar_count": int(state.get("bar_count", 0) or 0),
                }

    return {
        "code": code,
        "kline_downloaded": 1 if periods_found else 0,
        "kline_periods": json.dumps(periods_found, ensure_ascii=False),
        "kline_time_span": json.dumps(time_span_map, ensure_ascii=False),
        "ma144_passed": ma144_passed,
    }


def _batch_update_metadata_and_flags(candidates: list[dict], force_refresh: bool = False):
    """批量更新K线元数据和ma144标记，使用批量数据库操作减少IO"""
    total = len(candidates)
    batch_size = 500
    for i in range(0, total, batch_size):
        batch = candidates[i:i + batch_size]
        rows = []
        for item in batch:
            try:
                rows.append(_build_kline_metadata_row(item))
            except Exception:
                continue

        if rows:
            try:
                db.update_kline_metadata_batch(rows)
            except Exception:
                for row in rows:
                    try:
                        db.update_stock_pool_flags(
                            code=row["code"],
                            kline_downloaded=row["kline_downloaded"],
                            kline_periods=row["kline_periods"],
                            kline_time_span=row["kline_time_span"],
                            ma144_passed=row["ma144_passed"],
                        )
                    except Exception:
                        pass

        done = min(i + len(batch), total)
        _set_state(
            stage="finalizing",
            current_index=done,
            total_count=total,
            progress_pct=min(99, 96 + round(done / max(total, 1) * 3)),
            current_message=f"正在批量更新K线元数据和均线标记... {done}/{total}",
        )


def _weekly_pool_recheck(download_periods: list[str], time_span: str, force_refresh: bool = False) -> dict:
    """每周五盘后对股票池做一次全量复检，让扫描池自愈（双向）：

    1. 用全市场快照刷新每只股票的 名称/总市值/ST/退市/低市值 状态并写回 stock_pool；
    2. 对基础门槛（非ST/非退市/市值达标）通过的股票刷新日线并重算"站上144均线"；
    3. 重新站上均线的出池股票补齐扫描周期数据（如30分钟），最后重算 scan_eligible。
    平时不跑，只在周五盘后自动下载收尾时执行；扫描池因此既能重新收编（如跌破后又
    站上144均线的股票），也能淘汰（市值缩水/被ST的股票）。
    """
    summary = {"checked": 0, "screening_refreshed": 0, "reentered": 0, "exited": 0}
    pool_rows = db.list_stock_pool()
    if not pool_rows:
        return summary

    before_eligible = {
        str(item.get("code") or "").zfill(6)
        for item in pool_rows
        if int(item.get("scan_eligible") or 0) == 1
    }

    # 1) 全市场快照刷新市值/ST/退市（尽力而为：快照拿不到就跳过，保留旧状态）
    spot_map: dict[str, dict] = {}
    try:
        spot_df = akshare_data.get_all_a_share_spot()
        if spot_df is not None and not spot_df.empty:
            for _, row in spot_df.iterrows():
                code = str(row.get("code") or "").zfill(6)
                if code and code not in spot_map:
                    spot_map[code] = row
    except Exception as exc:
        _history_logger.warning("周五复检：全市场快照获取失败，本次跳过市值/ST刷新: %s", exc)

    screening_rows: list[dict] = []
    fresh_flags: dict[str, dict] = {}
    for item in pool_rows:
        if str(item.get("security_type") or "stock").lower() != "stock":
            continue  # ETF/指数没有市值/ST概念，状态保持不变
        code = str(item.get("code") or "").zfill(6)
        spot = spot_map.get(code)
        if spot is None:
            continue
        name = str(spot.get("name") or "").strip()
        total_mv = spot.get("total_mv")
        try:
            total_mv_value = float(total_mv) if total_mv not in (None, "") else None
        except (TypeError, ValueError):
            total_mv_value = None
        if not name or total_mv_value is None or total_mv_value <= 0:
            continue  # 快照缺数据时保留旧状态，避免误伤
        flags = {
            "is_st": 0 if is_non_st_stock(name) else 1,
            "is_delisted": 0 if is_not_delisted_stock(name) else 1,
            "is_low_mv": 1 if total_mv_value <= MIN_MARKET_CAP else 0,
        }
        fresh_flags[code] = flags
        screening_rows.append({"code": code, "name": name, "total_mv": total_mv_value, **flags})
    if screening_rows:
        summary["screening_refreshed"] = db.update_stock_pool_screening_flags_batch(screening_rows)

    # 2) 基础门槛过滤后逐只刷新日线并重算 MA144（在池股票刚被主下载同步过，ensure 会直接跳过网络请求）
    sweep_items: list[dict] = []
    seen_codes: set[str] = set()
    for item in pool_rows:
        code = str(item.get("code") or "").zfill(6)
        if not code or code in seen_codes:
            continue
        security_type = str(item.get("security_type") or "stock").lower()
        seen_codes.add(code)
        fresh = fresh_flags.get(code)
        is_st = int(fresh["is_st"]) if fresh else int(item.get("is_st") or 0)
        is_delisted = int(fresh["is_delisted"]) if fresh else int(item.get("is_delisted") or 0)
        is_low_mv = int(fresh["is_low_mv"]) if fresh else int(item.get("is_low_mv") or 0)
        if security_type == "stock" and (is_st or is_delisted or is_low_mv):
            continue
        sweep_items.append(
            {
                "code": code,
                "security_type": security_type,
                "kline_downloaded": int(item.get("kline_downloaded") or 0),
                "was_eligible": int(item.get("scan_eligible") or 0),
            }
        )
    summary["checked"] = len(sweep_items)
    if not sweep_items:
        db.recalculate_scan_eligible()
        return summary

    daily_bars = _get_bars_for_time_span("daily", time_span)
    scan_periods = [period for period in (download_periods or []) if period != "daily"]

    def recheck_one(item: dict) -> dict:
        code = item["code"]
        security_type = item["security_type"]
        security_kind = "index" if security_type == "index" else "etf" if security_type == "etf" else "security"
        # 从未下载过的股票只拉默认根数不够算MA144（需>=144根），至少拉250根
        limit = daily_bars if item["kline_downloaded"] else max(daily_bars, 250)
        try:
            ensure_local_kline_cache(
                code=code,
                period="daily",
                limit=limit,
                force_refresh=force_refresh,
                security_kind=security_kind,
            )
        except Exception as exc:
            _history_logger.warning("周五复检：%s 日线刷新失败: %s", code, exc)
        try:
            passed = bool(
                passes_security_daily_ma_filter(
                    code=code,
                    security_type=security_type,
                    force_refresh=force_refresh,
                )
            )
        except Exception:
            passed = False
        return {
            "code": code,
            "security_kind": security_kind,
            "ma144_passed": 1 if passed else 0,
            "was_eligible": item["was_eligible"],
            "kline_downloaded": item["kline_downloaded"],
        }

    results: list[dict] = []
    completed = 0
    future_to_item = {
        _download_executor.submit(recheck_one, item): item
        for item in sweep_items
    }
    for future in as_completed(future_to_item):
        item = future_to_item[future]
        try:
            results.append(future.result())
        except Exception as exc:
            _history_logger.warning("周五复检：%s 复检任务失败: %s", item.get("code"), exc)
        completed += 1
        if completed % 50 == 0 or completed == len(sweep_items):
            _set_state(
                stage="finalizing",
                progress_pct=99,
                current_index=completed,
                total_count=len(sweep_items),
                current_message=f"周五全量复检：已重算144均线 {completed}/{len(sweep_items)} 只",
            )

    db.update_ma144_flags_batch(
        [{"code": result["code"], "ma144_passed": result["ma144_passed"]} for result in results]
    )
    # 新下载了数据的股票补齐 kline_downloaded/kline_periods 元数据
    newly_downloaded = [result for result in results if not result["kline_downloaded"]]
    if newly_downloaded:
        _batch_update_metadata_and_flags(
            [
                {"code": result["code"], "ma144_passed": result["ma144_passed"], "ma144_checked": True}
                for result in newly_downloaded
            ],
            force_refresh,
        )

    # 3) 重新站上144均线的出池股票补齐扫描周期数据（如30分钟），否则 readiness 放行不了
    reentry_results = [result for result in results if result["ma144_passed"] == 1 and not result["was_eligible"]]
    for result in reentry_results:
        for period in scan_periods:
            try:
                if not get_local_history_ready(result["code"], period):
                    ensure_local_kline_cache(
                        code=result["code"],
                        period=period,
                        limit=_get_bars_for_time_span(period, time_span),
                        force_refresh=force_refresh,
                        security_kind=result["security_kind"],
                    )
            except Exception as exc:
                _history_logger.warning("周五复检：%s 补拉%s数据失败: %s", result["code"], period, exc)
    if reentry_results:
        _batch_update_metadata_and_flags(
            [
                {"code": result["code"], "ma144_passed": result["ma144_passed"], "ma144_checked": True}
                for result in reentry_results
            ],
            force_refresh,
        )

    db.recalculate_scan_eligible()
    after_eligible = {
        str(item.get("code") or "").zfill(6)
        for item in db.list_stock_pool(scan_eligible_only=True)
    }
    summary["reentered"] = len(after_eligible - before_eligible)
    summary["exited"] = len(before_eligible - after_eligible)
    _history_logger.info(
        "周五全量复检完成：检查 %s 只，市值/ST刷新 %s 只，重新入池 %s 只，移出 %s 只",
        summary["checked"],
        summary["screening_refreshed"],
        summary["reentered"],
        summary["exited"],
    )
    return summary


def _normalize_periods(periods: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized = []
    seen = set()
    for item in periods or ():
        period = normalize_period(str(item))
        if period in DOWNLOADABLE_KLINE_PERIODS and period not in seen:
            normalized.append(period)
            seen.add(period)

    for period in ("30min", "daily"):
        if period not in seen:
            normalized.append(period)
            seen.add(period)
    return normalized


def _normalize_rule_periods(periods: list[str]) -> list[str]:
    normalized = list(periods)
    for period in ("30min", "daily"):
        if period not in normalized:
            normalized.append(period)
    return normalized


def _normalize_codes(codes: list[str] | tuple[str, ...] | None) -> list[str]:
    if not codes:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in codes:
        code = str(item).strip()
        if not code:
            continue
        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) != 6:
            continue
        if digits in seen:
            continue
        seen.add(digits)
        normalized.append(digits)
    return normalized


def _build_direct_download_candidates(codes: list[str]) -> list[dict]:
    candidates: list[dict] = []
    major_index_map = {item["code"]: item for item in akshare_data.MAJOR_INDEXES}
    for code in codes:
        index_meta = major_index_map.get(code)
        likely_exchange_fund = code.startswith(("15", "16", "50", "51", "52", "56", "58"))
        security_type = "stock"
        detail = None if likely_exchange_fund else akshare_data.get_stock_spot_detail(code)
        name = ""
        market = 1
        total_mv = None
        industry = None
        if detail:
            name = str(detail.get("name", "") or code)
            market = int(detail.get("market", 1))
            total_mv = detail.get("total_mv")
            industry = detail.get("industry")
            if "ETF" in name.upper() or "LOF" in name.upper():
                security_type = "etf"
        if not name:
            etf_detail = akshare_data.get_cached_etf_detail(code) or akshare_data.get_etf_detail(code, timeout=3)
            if etf_detail:
                name = str(etf_detail.get("name", "") or code)
                market = int(etf_detail.get("market", 1))
                total_mv = etf_detail.get("total_mv")
                security_type = "etf"
        if not name:
            name = str(index_meta.get("name", "")) if index_meta else ""
            if name:
                market = int(index_meta.get("market", 1))
                security_type = "index"
        if not name:
            name = akshare_data.get_stock_name_by_code(code) or code
        if security_type == "stock" and ("ETF" in name.upper() or "LOF" in name.upper()):
            security_type = "etf"
        candidates.append(
            {
                "code": code,
                "name": name,
                "market": market,
                "total_mv": total_mv,
                "industry": industry,
                "security_type": security_type,
            }
        )
    return candidates


def _build_requirements(periods: list[str]) -> dict[str, int]:
    requirements = {}
    for period in periods:
        rule = LOCAL_KLINE_CACHE_RULES.get(period)
        if rule:
            requirements[period] = int(rule["min_bars"])
    return requirements


def _set_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)


def _append_recent_log(message: str):
    text = str(message or "").strip()
    if not text:
        return
    _history_logger.info(text)


def append_history_log(message: str):
    _append_recent_log(message)


def set_auto_download_schedule_status(**kwargs):
    with _state_lock:
        _auto_download_state.update(kwargs)


def is_auto_download_done_today(today_str: str) -> bool:
    """当天自动下载是否已成功完成(进程内)。

    today_done 由下载完成写入后是"当天已下载完成"的事实,调度循环每轮刷新
    状态时不得抹掉——否则 15:11 完成放行收盘扫描后,下一轮例行检查又翻回
    "未完成",收盘挂起闸门(readiness._session_close_download_pending)整晚
    误报"尚未下载完成"。跨天(today 字段变化)或进程重启(内存态归零)后
    自然为 False。
    """
    with _state_lock:
        return (
            str(_auto_download_state.get("today") or "") == str(today_str)
            and bool(_auto_download_state.get("today_done"))
        )


def _get_auto_download_schedule_status() -> dict:
    with _state_lock:
        snapshot = dict(_auto_download_state)

    next_check_at = str(snapshot.get("next_check_at") or "")
    next_check_seconds = 0
    if next_check_at:
        try:
            next_dt = datetime.strptime(next_check_at, "%Y-%m-%d %H:%M:%S")
            # next_check_at 一律由 now_beijing() 写入(北京墙钟),解析后与北京 naive now 比较,
            # 不能用 datetime.now()(服务器时区会把倒计时算偏数小时)
            next_check_seconds = max(int((next_dt - now_beijing().replace(tzinfo=None)).total_seconds()), 0)
        except Exception:
            next_check_seconds = 0

    return {
        "auto_download_enabled": bool(snapshot.get("enabled")),
        "auto_download_hour": int(snapshot.get("hour") or 15),
        "auto_download_check_interval_seconds": int(snapshot.get("check_interval_seconds") or 600),
        "auto_download_last_checked_at": str(snapshot.get("last_checked_at") or ""),
        "auto_download_next_check_at": next_check_at,
        "auto_download_next_check_seconds": next_check_seconds,
        "auto_download_today": str(snapshot.get("today") or ""),
        "auto_download_today_started": bool(snapshot.get("today_started")),
        "auto_download_today_done": bool(snapshot.get("today_done")),
        "auto_download_status": str(snapshot.get("status") or "idle"),
    }


def _count_ready_codes(candidates: list[dict], periods: list[str], require_fresh: bool = False) -> int:
    if not candidates or not periods:
        return 0
    ready = 0
    for item in candidates:
        if all(get_local_history_ready(item["code"], period, require_fresh=require_fresh) for period in periods):
            ready += 1
    return ready


def _record_recent_completion(completed_at: datetime) -> list[datetime]:
    with _state_lock:
        recent_times = list(_state.get("recent_completion_times") or [])
        recent_times.append(completed_at)
        if len(recent_times) > _RECENT_COMPLETION_WINDOW + 1:
            recent_times = recent_times[-(_RECENT_COMPLETION_WINDOW + 1):]
        _state["recent_completion_times"] = recent_times
        return recent_times


def _estimate_remaining_seconds_from_recent_completions(
    recent_times: list[datetime],
    completed_codes: int,
    total_count: int,
) -> int:
    if completed_codes < 2 or total_count <= completed_codes or len(recent_times) < 2:
        return 0

    window = recent_times[-(_RECENT_COMPLETION_WINDOW + 1):]
    intervals = [
        max((later - earlier).total_seconds(), 0.0)
        for earlier, later in zip(window, window[1:])
    ]
    intervals = [value for value in intervals if value > 0]
    if not intervals:
        return 0

    average_seconds = sum(intervals) / len(intervals)
    remaining_codes = max(total_count - completed_codes, 0)
    return int(average_seconds * remaining_codes)


def get_history_download_status() -> dict:
    with _state_lock:
        periods = list(_state["periods"])
        total_count_from_state = int(_state["total_count"] or 0)
        ready_count_from_state = int(_state["ready_count"] or 0)
        current_message = _state["current_message"]
        state_snapshot = dict(_state)

    universe = []
    target_mode = str(state_snapshot.get("target_mode") or "filtered")
    requested_code_count = int(state_snapshot.get("requested_code_count") or 0)
    should_load_rule_snapshot = (
        not total_count_from_state
        and target_mode != "selected"
    )
    if should_load_rule_snapshot:
        try:
            universe = load_download_universe_snapshot()
        except Exception:
            pass

    if target_mode == "selected":
        total_count = total_count_from_state or requested_code_count
        ready_count = ready_count_from_state
    else:
        total_count = total_count_from_state or len(universe)
        ready_count = ready_count_from_state or (_count_ready_codes(universe, periods) if universe else 0)

    if not current_message and not state_snapshot["running"] and total_count <= 0:
        current_message = "尚未生成规则下载结果，请先执行数据下载。"

    # 统计各周期K线存量
    try:
        from backend.db import get_stock_pool_stats
        pool_stats = get_stock_pool_stats()
        kline_counts = pool_stats.get("kline_counts", {})
        kline_period_days = pool_stats.get("kline_period_days", {})
        kline_downloaded_count = pool_stats.get("kline_downloaded_filtered", pool_stats.get("kline_downloaded", 0))
        scan_eligible_count = pool_stats.get("scan_eligible_realtime", pool_stats.get("scan_eligible", 0))
        kline_latest_date = pool_stats.get("kline_latest_date", "")
    except Exception:
        kline_counts = {}
        kline_period_days = {}
        kline_downloaded_count = 0
        scan_eligible_count = 0
        kline_latest_date = ""

    auto_download_status = _get_auto_download_schedule_status()

    return {
        "running": bool(state_snapshot["running"]),
        "periods": periods,
        "period_options": HISTORY_DOWNLOAD_PERIOD_OPTIONS,
        "stage": state_snapshot["stage"],
        "target_mode": state_snapshot["target_mode"],
        "requested_code_count": int(state_snapshot["requested_code_count"] or 0),
        "raw_total_count": int(state_snapshot["raw_total_count"] or 0),
        "raw_stock_count": int(state_snapshot["raw_stock_count"] or 0),
        "raw_etf_count": int(state_snapshot["raw_etf_count"] or 0),
        "raw_index_count": int(state_snapshot["raw_index_count"] or 0),
        "a_share_fetched_count": int(state_snapshot["a_share_fetched_count"] or 0),
        "removed_st_count": int(state_snapshot["removed_st_count"] or 0),
        "removed_market_cap_count": int(state_snapshot["removed_market_cap_count"] or 0),
        "removed_delisted_count": int(state_snapshot["removed_delisted_count"] or 0),
        "eligible_stock_count": int(state_snapshot.get("eligible_stock_count") or 0),
        "removed_ma_count": int(state_snapshot["removed_ma_count"] or 0),
        "final_stock_count": int(state_snapshot["final_stock_count"] or 0),
        "final_etf_count": int(state_snapshot["final_etf_count"] or 0),
        "final_index_count": int(state_snapshot["final_index_count"] or 0),
        "qualified_count": int(state_snapshot["qualified_count"] or 0),
        "current_period": state_snapshot["current_period"],
        "current_code": state_snapshot["current_code"],
        "current_name": state_snapshot["current_name"],
        "current_index": int(state_snapshot["current_index"] or 0),
        "total_count": total_count,
        "ready_count": ready_count,
        "progress_pct": int(state_snapshot["progress_pct"] or 0),
        "current_message": current_message,
        "selection_index": int(state_snapshot["selection_index"] or 0),
        "selection_total_count": int(state_snapshot["selection_total_count"] or 0),
        "last_started_at": state_snapshot["last_started_at"],
        "last_finished_at": state_snapshot["last_finished_at"],
        "error": state_snapshot["error"],
        "time_span": state_snapshot.get("time_span", "1m"),
        "estimated_remaining_seconds": int(state_snapshot.get("estimated_remaining_seconds", 0) or 0),
        "current_download_date": state_snapshot.get("current_download_date", ""),
        "trigger_source": str(state_snapshot.get("trigger_source") or "manual"),
        "kline_counts": kline_counts,
        "kline_period_days": kline_period_days,
        "kline_downloaded_count": kline_downloaded_count,
        "scan_eligible_count": scan_eligible_count,
        "kline_latest_date": kline_latest_date,
        "runtime_info": get_runtime_info(),
        **auto_download_status,
    }


def _run_history_download(periods: list[str], force_refresh: bool, codes: list[str], time_span: str = "1m"):
    target_mode = "selected" if codes else "filtered"
    trigger_source = str(_state.get("trigger_source") or "manual")
    _set_state(
        running=True,
        periods=periods,
        stage="downloading" if codes else "collecting",
        target_mode=target_mode,
        requested_code_count=len(codes),
        raw_total_count=len(codes) if codes else 0,
        raw_stock_count=0,
        raw_etf_count=0,
        raw_index_count=0,
        a_share_fetched_count=0,
        removed_st_count=0,
        removed_market_cap_count=0,
        removed_delisted_count=0,
        eligible_stock_count=0,
        removed_ma_count=0,
        final_stock_count=0,
        final_etf_count=0,
        final_index_count=0,
        qualified_count=0,
        current_period="",
        current_code="",
        current_name="",
        current_index=0,
        total_count=len(codes) if codes else 0,
        ready_count=0,
        progress_pct=0,
        current_message="指定代码模式：准备下载所选标的历史数据..." if codes else "第1步：正在初始化基础股票池...",
        selection_index=0,
        selection_total_count=0,
        last_started_at=_now_text(),
        last_finished_at="",
        error="",
        time_span=time_span,
        estimated_remaining_seconds=0,
        current_download_date="",
        download_start_time=now_beijing(),
    )
    _append_recent_log(
        f"{'自动' if trigger_source == 'auto' else '手动'}下载开始："
        f"{'指定代码' if codes else '规则股票池'}，周期 {', '.join(periods)}，时间跨度 {time_span}。"
    )

    try:
        def on_selection_progress(payload: dict):
            stage = str(payload.get("stage", "screening") or "screening")
            _set_state(
                stage=stage,
                raw_total_count=int(payload.get("raw_total_count", _state["raw_total_count"]) or 0),
                raw_stock_count=int(payload.get("raw_stock_count", _state["raw_stock_count"]) or 0),
                raw_etf_count=int(payload.get("raw_etf_count", _state["raw_etf_count"]) or 0),
                raw_index_count=int(payload.get("raw_index_count", _state["raw_index_count"]) or 0),
                a_share_fetched_count=int(payload.get("a_share_fetched_count", _state["a_share_fetched_count"]) or 0),
                removed_st_count=int(payload.get("removed_st_count", _state["removed_st_count"]) or 0),
                removed_market_cap_count=int(payload.get("removed_market_cap_count", _state["removed_market_cap_count"]) or 0),
                removed_delisted_count=int(payload.get("removed_delisted_count", _state["removed_delisted_count"]) or 0),
                eligible_stock_count=int(payload.get("eligible_stock_count", _state.get("eligible_stock_count") or 0) or 0),
                qualified_count=int(payload.get("qualified_count", _state["qualified_count"]) or 0),
                current_period="",
                current_code=payload.get("code", ""),
                current_name=payload.get("name", ""),
                current_index=0,
                total_count=0,
                progress_pct=(
                    100
                    if stage == "collecting" and int(payload.get("raw_total_count", 0) or 0) > 0
                    else min(
                        round(int(payload.get("current_index", 0)) / max(int(payload.get("total_count", 1)), 1) * 100),
                        100,
                    )
                ),
                current_message=payload.get("message", "正在筛选符合规则的股票池..."),
                selection_index=int(payload.get("current_index", 0)),
                selection_total_count=int(
                    payload.get("total_count", payload.get("raw_total_count", 0)) or 0
                ),
            )

        def on_finalize_progress(payload: dict):
            _set_state(
                stage="finalizing",
                current_period="日线144均线",
                current_code=payload.get("code", ""),
                current_name=payload.get("name", ""),
                current_index=int(payload.get("current_index", 0)),
                total_count=int(payload.get("total_count", 0)),
                qualified_count=int(payload.get("qualified_count", 0)),
                removed_ma_count=int(payload.get("removed_ma_count", _state["removed_ma_count"]) or 0),
                final_stock_count=int(payload.get("final_stock_count", _state["final_stock_count"]) or 0),
                final_index_count=int(payload.get("final_index_count", _state["final_index_count"]) or 0),
                final_etf_count=int(payload.get("final_etf_count", _state["final_etf_count"]) or 0),
                progress_pct=min(
                    round(int(payload.get("current_index", 0)) / max(int(payload.get("total_count", 1)), 1) * 100),
                    100,
                ),
                current_message=payload.get("message", "第3步：并行验证日线144均线，生成最终可扫描股票池..."),
            )

        if codes:
            candidates = _build_direct_download_candidates(codes)
            total_count = len(candidates)
            ready_count = _count_ready_codes(candidates, periods, require_fresh=not force_refresh)
            raw_stock_count = sum(1 for item in candidates if item.get("security_type") == "stock")
            raw_etf_count = sum(1 for item in candidates if item.get("security_type") == "etf")
            raw_index_count = sum(1 for item in candidates if item.get("security_type") == "index")
            _set_state(
                stage="downloading",
                raw_total_count=total_count,
                raw_stock_count=raw_stock_count,
                raw_etf_count=raw_etf_count,
                raw_index_count=raw_index_count,
                final_stock_count=raw_stock_count,
                final_etf_count=raw_etf_count,
                final_index_count=raw_index_count,
                qualified_count=ready_count,
                total_count=total_count,
                ready_count=ready_count,
                selection_index=total_count,
                selection_total_count=total_count,
                current_message=f"指定代码模式：跳过规则筛选，直接下载 {total_count} 个标的历史K线。",
            )
            download_periods = periods
        else:
            if trigger_source == "auto":
                candidates = load_download_universe_snapshot()
                if candidates:
                    raw_stock_count = sum(1 for item in candidates if item.get("security_type") == "stock")
                    raw_etf_count = sum(1 for item in candidates if item.get("security_type") == "etf")
                    raw_index_count = sum(1 for item in candidates if item.get("security_type") == "index")
                    _set_state(
                        stage="collecting",
                        raw_total_count=len(candidates),
                        raw_stock_count=raw_stock_count,
                        raw_etf_count=raw_etf_count,
                        raw_index_count=raw_index_count,
                        eligible_stock_count=raw_stock_count,
                        qualified_count=len(candidates),
                        selection_index=len(candidates),
                        selection_total_count=len(candidates),
                        current_message=f"自动下载：使用本地扫描池 {len(candidates)} 个标的，跳过在线股票池重建。",
                    )
                else:
                    candidates = build_download_universe(progress_callback=on_selection_progress, force_refresh=force_refresh)
            else:
                candidates = build_download_universe(progress_callback=on_selection_progress, force_refresh=force_refresh)
            total_count = len(candidates)
            download_periods = _normalize_rule_periods(periods)
            ready_count = _count_ready_codes(candidates, download_periods, require_fresh=not force_refresh)

            _set_state(
                stage="downloading",
                current_period="",
                current_code="",
                current_name="",
                current_index=0,
                total_count=total_count,
                ready_count=ready_count,
                qualified_count=0,
                progress_pct=0,
                periods=download_periods,
                current_message=f"第1步完成：符合 ST/市值规则的下载标的 {total_count} 个。第2步：开始下载历史K线...",
            )

        def download_one_code(item: dict) -> dict:
            code = item["code"]
            name = item["name"]
            security_type = str(item.get("security_type", "stock") or "stock")
            if security_type == "index":
                security_kind = "index"
            elif security_type == "etf":
                security_kind = "etf"
            else:
                security_kind = "security"
            completed_periods: list[str] = []
            skipped_periods: list[str] = []
            period_updates: list[dict] = []
            was_ready_before = all(get_local_history_ready(code, period, require_fresh=True) for period in download_periods)
            for period in download_periods:
                bars_to_fetch = _get_bars_for_time_span(period, time_span)
                before_sync_state = get_kline_sync_state(code, period) or {}
                before_bar_count = int(before_sync_state.get("bar_count", 0) or 0)
                if not force_refresh:
                    if before_bar_count >= bars_to_fetch and get_local_history_ready(code, period, require_fresh=True):
                        completed_periods.append(period)
                        skipped_periods.append(period)
                        period_updates.append(
                            {
                                "period": period,
                                "added_bars": 0,
                                "latest_bar": str(before_sync_state.get("last_bar_time") or ""),
                                "bar_count": before_bar_count,
                            }
                        )
                        continue
                ensure_local_kline_cache(
                    code=code,
                    period=period,
                    limit=bars_to_fetch,
                    force_refresh=force_refresh,
                    security_kind=security_kind,
                )
                completed_periods.append(period)
                after_sync_state = get_kline_sync_state(code, period) or {}
                after_bar_count = int(after_sync_state.get("bar_count", 0) or 0)
                period_updates.append(
                    {
                        "period": period,
                        "added_bars": max(after_bar_count - before_bar_count, 0),
                        "latest_bar": str(after_sync_state.get("last_bar_time") or before_sync_state.get("last_bar_time") or ""),
                        "bar_count": after_bar_count,
                    }
                )
            after_ready = all(get_local_history_ready(code, period) for period in download_periods)
            is_ma144_passed = None
            ma144_checked = False
            if security_type in {"stock", "etf", "index"} and after_ready:
                try:
                    is_ma144_passed = passes_security_daily_ma_filter(
                        code=code,
                        security_type=security_type,
                        force_refresh=force_refresh,
                    )
                    ma144_checked = True
                except Exception:
                    is_ma144_passed = None

            return {
                "code": code,
                "name": name,
                "completed_periods": completed_periods,
                "skipped_periods": skipped_periods,
                "after_ready": after_ready,
                "was_ready_before": was_ready_before,
                "last_period": completed_periods[-1] if completed_periods else "",
                "period_updates": period_updates,
                "latest_download_date": next(
                    (
                        str(update.get("latest_bar") or "")
                        for update in reversed(period_updates)
                        if update.get("latest_bar")
                    ),
                    "",
                ),
                "ma144_passed": is_ma144_passed,
                "ma144_checked": ma144_checked,
            }

        total_tasks = len(candidates) * len(download_periods)
        future_to_item = {
            _download_executor.submit(download_one_code, item): item
            for item in candidates
        }
        completed_tasks = 0
        processed_codes = 0
        initial_ready_count = ready_count
        newly_ready_count = 0
        ma144_passed_count = 0
        ma144_failed_count = 0
        qualified_candidates: list[dict] = []
        period_summary: dict[str, dict] = {}

        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                result = future.result()
            except Exception:
                result = {
                    "code": item["code"],
                    "name": item["name"],
                    "security_type": str(item.get("security_type", "stock") or "stock"),
                    "completed_periods": [],
                    "skipped_periods": [],
                    "after_ready": False,
                    "was_ready_before": False,
                    "last_period": "",
                    "period_updates": [],
                    "latest_download_date": "",
                    "ma144_passed": None,
                    "ma144_checked": False,
                }

            completed_tasks += len(result.get("completed_periods") or [])
            processed_codes += 1
            item["ma144_checked"] = bool(result.get("ma144_checked", False))
            if item["ma144_checked"]:
                item["ma144_passed"] = bool(result.get("ma144_passed", False))
            if result.get("after_ready") and not result.get("was_ready_before"):
                newly_ready_count += 1
            if not codes and result.get("ma144_checked") and result.get("ma144_passed"):
                ma144_passed_count += 1
                qualified_candidates.append(
                    {
                        "code": result.get("code", item["code"]),
                        "name": result.get("name", item["name"]),
                        "market": int(item.get("market", 1)),
                        "total_mv": item.get("total_mv"),
                        "security_type": str(item.get("security_type", "stock") or "stock"),
                        "ma144_passed": 1,
                        "ma144_checked": True,
                    }
                )
            elif not codes and result.get("ma144_checked"):
                ma144_failed_count += 1
            ready_count = min(total_count, initial_ready_count + newly_ready_count)

            for update in result.get("period_updates") or []:
                period = str(update.get("period") or "")
                if not period:
                    continue
                summary = period_summary.setdefault(
                    period,
                    {
                        "touched_codes": 0,
                        "added_bars": 0,
                        "latest_bar": "",
                    },
                )
                summary["touched_codes"] += 1
                summary["added_bars"] += int(update.get("added_bars", 0) or 0)
                latest_bar = str(update.get("latest_bar") or "")
                if latest_bar and latest_bar > str(summary.get("latest_bar") or ""):
                    summary["latest_bar"] = latest_bar

            recent_times = _record_recent_completion(now_beijing())
            estimated_remaining = _estimate_remaining_seconds_from_recent_completions(
                recent_times,
                processed_codes,
                total_count,
            )

            progress_pct = min(round(processed_codes / max(total_count, 1) * 100), 100)
            last_period = str(result.get("last_period") or "")
            mode_label = "指定代码" if codes else "规则股票池"
            _set_state(
                stage="downloading",
                current_period=last_period,
                current_code=result.get("code", item["code"]),
                current_name=result.get("name", item["name"]),
                current_index=processed_codes,
                total_count=total_count,
                ready_count=ready_count,
                qualified_count=ma144_passed_count if not codes else ready_count,
                removed_ma_count=ma144_failed_count if not codes else 0,
                progress_pct=progress_pct,
                estimated_remaining_seconds=estimated_remaining,
                current_download_date=str(result.get("latest_download_date") or ""),
                current_message=(
                    f"{mode_label} {result.get('name', item['name'])}（{result.get('code', item['code'])}）"
                    f"：下载与验证中，股票 {processed_codes}/{total_count}"
                    + (f"，已通过 {ma144_passed_count}，已淘汰 {ma144_failed_count}" if not codes else "")
                ),
            )

        result_candidates = candidates if codes else qualified_candidates
        final_total_count = total_count if codes else len(result_candidates)
        final_ready_count = _count_ready_codes(candidates, download_periods)
        downloaded_count = total_count

        if codes:
            mark_manual_download_candidates(candidates)

        # 批量更新metadata和ma144标记（不在每个线程中做，减少数据库竞争）
        _set_state(
            stage="finalizing",
            current_message="正在批量更新K线元数据和均线标记...",
            progress_pct=99,
        )
        _batch_update_metadata_and_flags(candidates, force_refresh)

        db.recalculate_scan_eligible()

        # 每周五盘后自动下载：对股票池做一次全量复检（市值/ST/退市 + 日线144均线），
        # 让扫描池自愈（双向）；周一~周四不加这步，避免每天全量重算。
        weekly_recheck_note = ""
        if trigger_source == "auto" and not codes and now_beijing().weekday() == 4:
            try:
                recheck = _weekly_pool_recheck(download_periods, time_span, force_refresh)
                weekly_recheck_note = (
                    f"；周五全量复检：检查 {recheck['checked']} 只，"
                    f"重新入池 {recheck['reentered']} 只，移出 {recheck['exited']} 只"
                )
                _append_recent_log(
                    f"周五全量复检：检查 {recheck['checked']} 只，市值/ST刷新 {recheck['screening_refreshed']} 只，"
                    f"重新入池 {recheck['reentered']} 只，移出 {recheck['exited']} 只。"
                )
            except Exception as exc:
                _append_recent_log(f"周五全量复检失败：{exc}")
                _app_logger.exception("周五全量复检失败：%s", exc)

        period_label_map = {
            "1min": "1分钟",
            "5min": "5分钟",
            "15min": "15分钟",
            "30min": "30分钟",
            "60min": "60分钟",
            "daily": "日K",
            "weekly": "周K",
            "monthly": "月K",
        }
        for period in download_periods:
            summary = period_summary.get(period)
            if not summary:
                continue
            latest_bar = str(summary.get("latest_bar") or "")
            added_bars = int(summary.get("added_bars", 0) or 0)
            touched_codes = int(summary.get("touched_codes", 0) or 0)
            _append_recent_log(
                f"{period_label_map.get(period, period)} 更新完成："
                f"覆盖 {touched_codes} 只，新增 {added_bars} 根"
                + (f"，最新K线时间 {latest_bar}" if latest_bar else "")
                + "。"
            )

        if codes:
            final_message = "指定代码下载完成，已写入本地历史库并标记为手动下载。"
        else:
            final_message = (
                f"规则下载完成：已下载 {downloaded_count} 个标的；其中日线站上144均线可扫描 {final_total_count} 个。"
                f"{weekly_recheck_note}"
            )

        final_stock_count = sum(1 for row in result_candidates if row.get("security_type") == "stock")
        final_etf_count = sum(1 for row in result_candidates if row.get("security_type") == "etf")
        final_index_count = sum(1 for row in result_candidates if row.get("security_type") == "index")

        _set_state(
            running=False,
            stage="idle",
            current_period="",
            current_code="",
            current_name="",
            current_index=downloaded_count,
            total_count=downloaded_count,
            ready_count=final_ready_count,
            qualified_count=final_total_count,
            final_stock_count=final_stock_count,
            final_etf_count=final_etf_count,
            final_index_count=final_index_count,
            removed_ma_count=max(total_count - final_total_count, 0) if not codes else 0,
            progress_pct=100 if total_count > 0 else 0,
            current_message=final_message,
            selection_index=_state["selection_total_count"],
            last_finished_at=_now_text(),
            error="",
        )
        _append_recent_log(final_message)
        if trigger_source == "auto":
            set_auto_download_schedule_status(status="completed", today_done=True)
            _app_logger.info(
                "15:00自动下载完成：周期=%s，标的=%s，可用=%s，强制覆盖=%s",
                ",".join(download_periods),
                downloaded_count,
                final_ready_count,
                "是" if force_refresh else "否",
            )
        return
    except Exception as exc:
        _append_recent_log(f"下载失败：{exc}")
        if trigger_source == "auto":
            set_auto_download_schedule_status(status="failed")
            _app_logger.exception("15:00自动下载失败：%s", exc)
        _set_state(
            running=False,
            stage="idle",
            progress_pct=min(int(_state["progress_pct"] or 0), 99),
            current_message=str(exc),
            last_finished_at=_now_text(),
            error=str(exc),
        )


def start_history_download(
    periods: list[str] | tuple[str, ...] | None = None,
    force_refresh: bool = False,
    codes: list[str] | tuple[str, ...] | None = None,
    time_span: str = "1m",
    source: str = "manual",
) -> dict:
    current = get_history_download_status()
    if current["running"]:
        return {
            "success": False,
            "message": "已有历史下载任务正在运行，请稍候",
            "data": current,
        }

    normalized_periods = _normalize_periods(periods)
    normalized_codes = _normalize_codes(codes)
    normalized_time_span = time_span if time_span in _TIME_SPAN_DAYS else "1m"
    _set_state(
        running=True,
        periods=normalized_periods,
        stage="downloading" if normalized_codes else "collecting",
        target_mode="selected" if normalized_codes else "filtered",
        requested_code_count=len(normalized_codes),
        raw_total_count=len(normalized_codes) if normalized_codes else 0,
        raw_stock_count=0,
        raw_etf_count=0,
        raw_index_count=0,
        a_share_fetched_count=0,
        removed_st_count=0,
        removed_market_cap_count=0,
        removed_delisted_count=0,
        eligible_stock_count=0,
        removed_ma_count=0,
        final_stock_count=0,
        final_etf_count=0,
        final_index_count=0,
        qualified_count=0,
        current_period="",
        current_code="",
        current_name="",
        current_index=0,
        total_count=len(normalized_codes) if normalized_codes else 0,
        ready_count=0,
        progress_pct=0,
        current_message="正在创建指定代码下载任务..." if normalized_codes else "正在创建下载任务，准备第1步初始化基础股票池...",
        selection_index=0,
        selection_total_count=0,
        last_started_at=_now_text(),
        last_finished_at="",
        error="",
        time_span=normalized_time_span,
        estimated_remaining_seconds=0,
        current_download_date="",
        download_start_time=now_beijing(),
        recent_completion_times=[],
        trigger_source="auto" if str(source).lower() == "auto" else "manual",
    )
    _executor.submit(_run_history_download, normalized_periods, bool(force_refresh), normalized_codes, normalized_time_span)
    return {
        "success": True,
        "data": get_history_download_status(),
    }
