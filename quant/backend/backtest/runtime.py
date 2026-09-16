from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.auto_scan import get_scan_readiness
from backend import db
from backend.time_utils import now_beijing
from backend.backtest import remote
from backend.backtest.engine import run_backtest
from backend.config import MINUTE_PERIODS, PI_NODE_BATCH_CHUNK
from backend.kline_service import get_security_kline
from backend.market import akshare_data, pytdx_data
from backend.security_service import get_etf_info
from backend.time_utils import format_beijing_date, format_beijing_time
from backend.system_utils import get_optimal_worker_count
_executor = ThreadPoolExecutor(max_workers=1)
_state_lock = threading.Lock()
_state = {
    "job_id": "",
    "running": False,
    "mode": "single",
    "progress_pct": 0,
    "current_step": "",
    "message": "",
    "total_targets": 0,
    "completed_targets": 0,
    "success_targets": 0,
    "failed_targets": 0,
    "current_target_index": 0,
    "current_target_code": "",
    "current_target_name": "",
    "owner_username": "",
    "result": None,
    "error": "",
    "updated_at": "",
    "node_used": "",
}


def _now_text() -> str:
    return now_beijing().strftime("%Y-%m-%d %H:%M:%S")


def _parse_api_date(value: str) -> Optional[pd.Timestamp]:
    if not value:
        return None
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed


def _filter_date_range(df: pd.DataFrame, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    time_col = "datetime" if "datetime" in df.columns else "date"
    if time_col not in df.columns:
        return df

    start_ts = _parse_api_date(start_date)
    end_ts = _parse_api_date(end_date)

    result = df.copy()
    result[time_col] = pd.to_datetime(result[time_col], errors="coerce", utc=True)
    result = result.dropna(subset=[time_col])

    if start_ts is not None:
        result = result[result[time_col] >= start_ts]
    if end_ts is not None:
        result = result[result[time_col] < end_ts + pd.Timedelta(days=1)]

    return result.reset_index(drop=True)


def filter_dataframe_by_time_range(
    df: pd.DataFrame,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    time_col = "datetime" if "datetime" in df.columns else "date"
    if time_col not in df.columns:
        return df.copy()

    result = df.copy()
    result[time_col] = pd.to_datetime(result[time_col], errors="coerce", utc=True)
    result = result.dropna(subset=[time_col])

    from backend.time_utils import to_utc_timestamp
    start_ts = to_utc_timestamp(start_time) if start_time else None
    end_ts = to_utc_timestamp(end_time) if end_time else None

    if start_ts is not None and not pd.isna(start_ts):
        result = result[result[time_col] >= start_ts]
    if end_ts is not None and not pd.isna(end_ts):
        result = result[result[time_col] <= end_ts]

    return result.reset_index(drop=True)


def _estimate_minute_fetch_count(start_date: Optional[str], end_date: Optional[str], period: str) -> int:
    start_ts = _parse_api_date(start_date)
    end_ts = _parse_api_date(end_date) or pd.Timestamp.now()
    direct_period = _direct_minute_period(period)

    if start_ts is None:
        if direct_period is not None:
            return 2000
        return 12000

    days = max((end_ts - start_ts).days + 1, 1)
    if direct_period is not None:
        minute_value = int(period)
        bars_per_day = max(240 // minute_value, 1)
        direct_bars = days * bars_per_day + bars_per_day * 10
        return min(max(direct_bars, 500), 12000)

    return 12000


def _set_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)
        _state["updated_at"] = _now_text()


def _direct_minute_period(period: str) -> Optional[str]:
    return {
        "1": "1min",
        "5": "5min",
        "15": "15min",
        "30": "30min",
        "60": "60min",
        "120": "120min",
    }.get(period)


def _is_major_index_backtest(code: str, name_hint: str = "") -> bool:
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

    watch_item = get_etf_info(code)
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


def _get_backtest_kline(code: str, period: str, count: int, name_hint: str = "") -> pd.DataFrame:
    security_kind = "index" if _is_major_index_backtest(code, name_hint) else "security"
    response = get_security_kline(code, period, count, security_kind)
    if isinstance(response, pd.DataFrame):
        return response
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, pd.DataFrame):
            return data
    return pd.DataFrame()


def load_backtest_dataframe(
    code: str,
    name: str,
    period: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    df = None

    if period in MINUTE_PERIODS:
        fetch_count = _estimate_minute_fetch_count(start_date, end_date, period)
        direct_period = _direct_minute_period(period)
        if direct_period is None:
            return pd.DataFrame()
        df = _get_backtest_kline(code, direct_period, fetch_count, name)
        if df is not None and not df.empty:
            df = _filter_date_range(df, start_date, end_date)
        return df if df is not None else pd.DataFrame()

    pytdx_period_map = {
        "daily": "daily",
        "weekly": "weekly",
        "monthly": "monthly",
    }
    source_period = pytdx_period_map.get(period)
    if source_period is not None:
        df = _get_backtest_kline(code, source_period, 2000, name)

    if df is None or df.empty:
        df = akshare_data.get_etf_hist_daily(
            code,
            start_date=start_date,
            end_date=end_date if end_date else None,
            period=period,
        )

    if df is not None and not df.empty:
        df = _filter_date_range(df, start_date, end_date)
        return df
    return pd.DataFrame()


def _load_backtest_dataframe_with_retry(
    code: str,
    name: str,
    period: str,
    start_date: str,
    end_date: str,
    attempts: int = 3,
) -> pd.DataFrame:
    last_df = pd.DataFrame()
    for attempt in range(max(1, attempts)):
        last_df = load_backtest_dataframe(code, name, period, start_date, end_date)
        if last_df is not None and not last_df.empty:
            return last_df
        if attempt < attempts - 1:
            time.sleep(0.2)
    return last_df


def _build_status() -> dict:
    with _state_lock:
        return {
            "job_id": _state["job_id"],
            "running": bool(_state["running"]),
            "mode": _state["mode"],
            "progress_pct": int(_state["progress_pct"]),
            "current_step": _state["current_step"],
            "message": _state["message"],
            "total_targets": int(_state["total_targets"]),
            "completed_targets": int(_state["completed_targets"]),
            "success_targets": int(_state["success_targets"]),
            "failed_targets": int(_state["failed_targets"]),
            "current_target_index": int(_state["current_target_index"]),
            "current_target_code": _state["current_target_code"],
            "current_target_name": _state["current_target_name"],
            "owner_username": _state.get("owner_username") or "",
            "result": _state["result"],
            "error": _state["error"],
            "updated_at": _state["updated_at"],
            "node_used": _state.get("node_used") or "",
        }


def get_backtest_status() -> dict:
    return _build_status()


def _format_display_date(value: str) -> str:
    parsed = _parse_api_date(value)
    if parsed is None:
        return ""
    return parsed.strftime("%Y-%m-%d")


def _format_range_boundary(value, period: str) -> str:
    if period in MINUTE_PERIODS:
        return format_beijing_time(value, "%Y-%m-%d %H:%M")
    return format_beijing_date(value)


def _first_buy_return_metrics(result: dict) -> tuple[float, float]:
    """从第一笔买入开始，计算到回测周期结束的股票涨跌幅，以及策略相对不操作多赚/少赚的百分点。"""
    stock_change_pct = float(result.get("stock_change_pct", 0) or 0)
    trade_records = result.get("trade_records") or []
    buy_records = [record for record in trade_records if str(record.get("direction") or "") == "buy"]
    if not buy_records:
        return round(stock_change_pct, 2), round(float(result.get("total_return", 0) or 0) - stock_change_pct, 2)

    first_buy = buy_records[0]
    first_buy_price = float(first_buy.get("price") or 0)
    final_price = float(result.get("final_close_price", 0) or 0)
    if final_price <= 0:
        final_price = first_buy_price

    hold_return_from_first_buy = (
        (final_price - first_buy_price) / first_buy_price * 100 if first_buy_price > 0 else 0.0
    )
    vs_hold_return = float(result.get("total_return", 0) or 0) - hold_return_from_first_buy
    return round(hold_return_from_first_buy, 2), round(vs_hold_return, 2)


def _build_full_backtest_summary(
    *,
    strategy: str,
    period: str,
    start_date: str,
    end_date: str,
    total_targets: int,
    success_items: list[dict],
    failed_items: list[dict],
) -> dict:
    def _group_return_sum(items: list[dict], key: str) -> float:
        return sum(float(item.get(key, 0) or 0) for item in items)

    def _build_stock_bucket_details(items: list[dict], descending: bool) -> list[dict]:
        return sorted(
            [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "total_profit": round(float(item.get("total_profit", 0) or 0), 2),
                    "total_return": round(float(item.get("total_return", 0) or 0), 2),
                    "stock_change_pct": _first_buy_return_metrics(item)[0],
                    "vs_hold_return": _first_buy_return_metrics(item)[1],
                    "max_drawdown": round(float(item.get("max_drawdown", 0) or 0), 2),
                    "round_trip_trades": int(item.get("round_trip_trades", 0) or 0),
                    "won_trades": int(item.get("won_trades", 0) or 0),
                    "lost_trades": int(item.get("lost_trades", 0) or 0),
                    "bucket": "profit" if descending else "loss",
                }
                for item in items
            ],
            key=lambda row: row["total_profit"],
            reverse=descending,
        )

    traded_items = [item for item in success_items if int(item.get("round_trip_trades", 0) or 0) > 0]
    total_round_trip_trades = sum(int(item.get("round_trip_trades", 0) or 0) for item in success_items)
    success_count = sum(int(item.get("won_trades", 0) or 0) for item in success_items)
    failed_count = sum(int(item.get("lost_trades", 0) or 0) for item in success_items)

    profitable_items = [
        item for item in traded_items if float(item.get("total_return", 0) or 0) > 0
    ]
    loss_items = [
        item for item in traded_items if float(item.get("total_return", 0) or 0) <= 0
    ]

    profitable_count = len(profitable_items)
    loss_count = len(loss_items)
    cumulative_return = sum(float(item.get("realized_total_return", 0) or 0) for item in success_items)
    average_return = (
        sum(float(item.get("realized_total_return", 0) or 0) for item in traded_items) / len(traded_items)
        if traded_items else 0.0
    )
    max_drawdown = max((float(item.get("max_drawdown", 0) or 0) for item in success_items), default=0.0)
    max_gain = max((float(item.get("total_return", 0) or 0) for item in success_items), default=0.0)
    win_rate = (success_count / total_round_trip_trades * 100) if total_round_trip_trades > 0 else 0.0
    profitable_avg_return = (
        sum(float(item.get("total_return", 0) or 0) for item in profitable_items) / len(profitable_items)
        if profitable_items else 0.0
    )
    loss_avg_return = (
        sum(float(item.get("total_return", 0) or 0) for item in loss_items) / len(loss_items)
        if loss_items else 0.0
    )
    profitable_cumulative_return = _group_return_sum(profitable_items, "total_return")
    loss_cumulative_return = _group_return_sum(loss_items, "total_return")
    profitable_items_detail = _build_stock_bucket_details(profitable_items, True)
    loss_items_detail = _build_stock_bucket_details(loss_items, False)
    max_drawdown_item = max(
        success_items,
        key=lambda item: float(item.get("max_drawdown", 0) or 0),
        default=None,
    )
    max_gain_item = max(
        success_items,
        key=lambda item: float(item.get("total_return", 0) or 0),
        default=None,
    )

    summary = {
        "strategy_name": strategy,
        "period": period,
        "range_start": _format_display_date(start_date),
        "range_end": _format_display_date(end_date) if end_date else "",
        "target_count": total_targets,
        "success_count": success_count,
        "failed_count": failed_count,
        "backtest_failed_count": len(failed_items),
        "backtest_success_target_count": len(success_items),
        "traded_target_count": len(traded_items),
        "total_round_trip_trades": total_round_trip_trades,
        "profitable_count": profitable_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 2),
        "cumulative_return": round(cumulative_return, 2),
        "average_return": round(average_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_gain": round(max_gain, 2),
        "profitable_average_return": round(profitable_avg_return, 2),
        "loss_average_return": round(loss_avg_return, 2),
        "profitable_cumulative_return": round(profitable_cumulative_return, 2),
        "loss_cumulative_return": round(loss_cumulative_return, 2),
        "profitable_items": profitable_items_detail,
        "loss_items": loss_items_detail,
        "max_drawdown_item": max_drawdown_item,
        "max_gain_item": max_gain_item,
    }
    return summary


def _run_full_backtest_worker(task: dict) -> dict:
    code = str(task["code"]).zfill(6)
    name = str(task.get("name", "") or code)
    period = str(task["period"])
    start_date = str(task["start_date"])
    end_date = str(task.get("end_date", "") or "")
    strategy = str(task["strategy"])
    cash = float(task["cash"])
    min_quality_score = int(task.get("min_quality_score") or 0)
    index = int(task["index"])

    try:
        df = _load_backtest_dataframe_with_retry(code, name, period, start_date, end_date)
        if df is None or df.empty:
            return {
                "ok": False,
                "code": code,
                "name": name,
                "message": "选定区间内暂无可用数据",
                "index": index,
            }

        result = run_backtest(
            df,
            strategy_name=strategy,
            cash=cash,
            progress_callback=None,
            lightweight=True,
            include_equity_curve=False,
            period=period,
            min_quality_score=min_quality_score,
        )
        if not result.get("success"):
            return {
                "ok": False,
                "code": code,
                "name": name,
                "message": result.get("message", "回测失败"),
                "index": index,
            }

        time_col = "datetime" if "datetime" in df.columns else "date"
        return {
            "ok": True,
            "item": {
                "code": code,
                "name": name,
                "bar_count": len(df),
                "period": period,
                "range_start": _format_range_boundary(df[time_col].iloc[0], period),
                "range_end": _format_range_boundary(df[time_col].iloc[-1], period),
                **result,
            },
            "index": index,
            "code": code,
            "name": name,
        }
    except Exception as exc:
        return {
            "ok": False,
            "code": code,
            "name": name,
            "message": str(exc),
            "index": index,
        }


def _run_full_backtest_worker_with_df(task: dict) -> dict:
    """df 已由主进程预取好的全量回测 worker（用于 Pi 卸载的本地回落）。

    返回结构严格对齐 ``_run_full_backtest_worker``：复用同一份 df 对象，
    保证 Pi 路径与本地回落路径同输入、同结果。
    """
    code = str(task["code"]).zfill(6)
    name = str(task.get("name", "") or code)
    period = str(task.get("period", ""))
    strategy = str(task["strategy"])
    cash = float(task["cash"])
    min_quality_score = int(task.get("min_quality_score") or 0)
    index = int(task["index"])
    df = task.get("df")

    try:
        if df is None or (hasattr(df, "empty") and df.empty):
            return {
                "ok": False,
                "code": code,
                "name": name,
                "message": "选定区间内暂无可用数据",
                "index": index,
            }

        result = run_backtest(
            df,
            strategy_name=strategy,
            cash=cash,
            progress_callback=None,
            lightweight=True,
            include_equity_curve=False,
            period=period,
            min_quality_score=min_quality_score,
        )
        if not result.get("success"):
            return {
                "ok": False,
                "code": code,
                "name": name,
                "message": result.get("message", "回测失败"),
                "index": index,
            }

        time_col = "datetime" if "datetime" in df.columns else "date"
        return {
            "ok": True,
            "item": {
                "code": code,
                "name": name,
                "bar_count": len(df),
                "period": period,
                "range_start": _format_range_boundary(df[time_col].iloc[0], period),
                "range_end": _format_range_boundary(df[time_col].iloc[-1], period),
                **result,
            },
            "index": index,
            "code": code,
            "name": name,
        }
    except Exception as exc:
        return {
            "ok": False,
            "code": code,
            "name": name,
            "message": str(exc),
            "index": index,
        }


def _build_batch_extreme_detail(
    item: Optional[dict],
    *,
    strategy: str,
    period: str,
    start_date: str,
    end_date: str,
    cash: float,
    min_quality_score: int = 0,
) -> Optional[dict]:
    if not item:
        return None

    code = str(item.get("code", "")).zfill(6)
    name = str(item.get("name", "") or code)
    df = _load_backtest_dataframe_with_retry(code, name, period, start_date, end_date)
    if df is None or df.empty:
        return None

    result = run_backtest(
        df,
        strategy_name=strategy,
        cash=cash,
        progress_callback=None,
        lightweight=False,
        include_equity_curve=True,
        period=period,
        min_quality_score=min_quality_score,
    )
    if not result.get("success"):
        return None

    first_buy_stock_change_pct, vs_hold_return = _first_buy_return_metrics(result)

    time_col = "datetime" if "datetime" in df.columns else "date"
    return {
        "code": code,
        "name": name,
        "period": period,
        "strategy_name": strategy,
        "bar_count": len(df),
        "range_start": _format_range_boundary(df[time_col].iloc[0], period),
        "range_end": _format_range_boundary(df[time_col].iloc[-1], period),
        "total_return": round(float(result.get("total_return", 0) or 0), 2),
        "stock_change_pct": first_buy_stock_change_pct,
        "vs_hold_return": vs_hold_return,
        "max_drawdown": round(float(result.get("max_drawdown", 0) or 0), 2),
        "round_trip_trades": int(result.get("round_trip_trades", 0) or 0),
        "won_trades": int(result.get("won_trades", 0) or 0),
        "lost_trades": int(result.get("lost_trades", 0) or 0),
        "win_rate": round(float(result.get("win_rate", 0) or 0), 2),
        "trade_records": result.get("trade_records") or [],
        "drawdown_detail": result.get("drawdown_detail"),
        "best_trade": result.get("best_trade"),
        "worst_trade": result.get("worst_trade"),
    }


def build_full_backtest_stock_detail(run_id: int, code: str) -> Optional[dict]:
    run = db.get_full_backtest_run(int(run_id))
    if not run:
        return None
    summary = (run.get("payload") or {}).get("summary") or {}
    payload = run.get("payload") or {}
    strategy = str(summary.get("strategy_name") or run.get("strategy_name") or "")
    period = str(summary.get("period") or run.get("period") or "daily")
    start_date = str(summary.get("range_start") or run.get("start_date") or "").replace("-", "")
    end_date = str(summary.get("range_end") or run.get("end_date") or "").replace("-", "")
    cash = float((run.get("payload") or {}).get("cash") or 100000.0)
    code_text = str(code).zfill(6)
    name = ""
    for group in ("profitable_items", "loss_items", "top_successes", "top_losses"):
        for item in payload.get(group, []) or []:
            if str(item.get("code", "")).zfill(6) == code_text:
                name = str(item.get("name", "") or "")
                break
        if name:
            break
    return _build_batch_extreme_detail(
        {"code": code_text, "name": name},
        strategy=strategy,
        period=period,
        start_date=start_date,
        end_date=end_date,
        cash=cash,
        min_quality_score=int(payload.get("min_quality_score") or 0),
    )


def _run_full_backtest_job(params: dict):
    strategy = params["strategy"]
    start_date = params["start_date"]
    end_date = params["end_date"]
    cash = params["cash"]
    period = params["period"]
    min_quality_score = int(params.get("min_quality_score") or 0)
    owner_username = params.get("owner_username")

    readiness = get_scan_readiness()
    candidates = list(readiness.get("candidates") or [])
    total_targets = len(candidates)
    if total_targets <= 0:
        message = str(readiness.get("message") or "当前没有可扫描目标，请先在数据下载中准备好可扫描股票池")
        _set_state(
            running=False,
            progress_pct=100,
            current_step="失败",
            message=message,
            total_targets=0,
            completed_targets=0,
            success_targets=0,
            failed_targets=0,
            current_target_index=0,
            current_target_code="",
            current_target_name="",
            result={"success": False, "message": message, "mode": "batch"},
            error=message,
        )
        return

    success_items: list[dict] = []
    failed_items: list[dict] = []
    worker_count = get_optimal_worker_count("cpu", max_limit=8)
    _set_state(
        progress_pct=6,
        current_step="准备全量回测",
        message=f"已加载 {total_targets} 个可扫描目标，准备轻量并行回测（{worker_count} 进程）",
        total_targets=total_targets,
        completed_targets=0,
        success_targets=0,
        failed_targets=0,
        current_target_index=0,
        current_target_code="",
        current_target_name="",
        owner_username=str(owner_username or ""),
        result=None,
        error="",
    )

    def _apply_finished(finished: dict) -> None:
        nonlocal completed
        completed += 1
        code = finished.get("code", "")
        name = finished.get("name", code)

        if finished.get("ok"):
            success_items.append(finished["item"])
        else:
            failed_items.append(
                {
                    "code": code,
                    "name": name,
                    "message": finished.get("message", "回测失败"),
                }
            )

        progress_pct = min(95, 8 + int((completed / max(total_targets, 1)) * 84))
        _set_state(
            completed_targets=completed,
            success_targets=len(success_items),
            failed_targets=len(failed_items),
            current_target_index=int(finished.get("index", completed)),
            current_target_code=code,
            current_target_name=name,
            current_step=f"正在回测 {completed}/{total_targets}",
            message=(
                f"已完成 {completed}/{total_targets}，成功 {len(success_items)} 个，失败 {len(failed_items)} 个，"
                f"当前完成标的 {name} ({code})"
            ),
            progress_pct=progress_pct,
        )

    completed = 0
    any_node_pi = False
    any_node_local = False
    if not remote.offload_enabled_for("full"):
        # —— 节点关闭：逐字保留原本地 ProcessPool 路径 ——
        any_node_local = True
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    _run_full_backtest_worker,
                    {
                        "index": index,
                        "code": str(item.get("code", "")).zfill(6),
                        "name": str(item.get("name", "") or ""),
                        "period": period,
                        "start_date": start_date,
                        "end_date": end_date,
                        "strategy": strategy,
                        "cash": cash,
                        "min_quality_score": min_quality_score,
                    },
                ): (index, item)
                for index, item in enumerate(candidates, start=1)
            }

            for future in as_completed(future_map):
                try:
                    finished = future.result()
                except Exception as exc:
                    index, item = future_map[future]
                    finished = {
                        "ok": False,
                        "code": str(item.get("code", "")).zfill(6),
                        "name": str(item.get("name", "") or ""),
                        "message": str(exc),
                        "index": index,
                    }
                _apply_finished(finished)
    else:
        # —— 节点启用：分块卸载到 Pi，整 chunk 失败则回落本地（复用同一份 df）——
        for chunk_start in range(0, total_targets, PI_NODE_BATCH_CHUNK):
            chunk = candidates[chunk_start : chunk_start + PI_NODE_BATCH_CHUNK]
            loaded = []
            for index, item in enumerate(chunk, start=chunk_start + 1):
                code = str(item.get("code", "")).zfill(6)
                name = str(item.get("name", "") or code)
                df = _load_backtest_dataframe_with_retry(code, name, period, start_date, end_date)
                loaded.append({"index": index, "code": code, "name": name, "df": df, "period": period})

            runnable = [t for t in loaded if t["df"] is not None and not t["df"].empty]
            empty_tasks = [t for t in loaded if t["df"] is None or t["df"].empty]

            results = (
                remote.run_batch_on_node(
                    runnable,
                    strategy=strategy,
                    cash=cash,
                    commission=0.0001,
                    lightweight=True,
                    include_equity_curve=False,
                    period=period,
                    min_quality_score=min_quality_score,
                )
                if runnable
                else None
            )

            if results is None:
                # 整 chunk 回落本地：复用主进程已取好的 df，保证与 Pi 路径同输入
                any_node_local = True
                with ProcessPoolExecutor(max_workers=worker_count) as pool:
                    fallback_map = {
                        pool.submit(
                            _run_full_backtest_worker_with_df,
                            {
                                "index": t["index"],
                                "code": t["code"],
                                "name": t["name"],
                                "period": t["period"],
                                "strategy": strategy,
                                "cash": cash,
                                "min_quality_score": min_quality_score,
                                "df": t["df"],
                            },
                        ): t["index"]
                        for t in runnable
                    }
                    for future in as_completed(fallback_map):
                        try:
                            _apply_finished(future.result())
                        except Exception as exc:
                            _apply_finished(
                                {
                                    "ok": False,
                                    "code": "",
                                    "name": "",
                                    "message": f"本地 worker 崩溃: {exc}",
                                    "index": fallback_map[future],
                                }
                            )
            else:
                # Pi 只回结果字段；用主进程持有的 df 补齐 bar_count/period/range_start/range_end，
                # 与本地 _run_full_backtest_worker 产出完全一致（同 df、同 _format_range_boundary）
                any_node_pi = True
                df_by_index = {t["index"]: t for t in loaded}
                for finished in results:
                    item = finished.get("item") if finished.get("ok") else None
                    if item is not None:
                        task = df_by_index.get(int(finished.get("index", -1)))
                        if task and task["df"] is not None and not task["df"].empty:
                            df_t = task["df"]
                            time_col = "datetime" if "datetime" in df_t.columns else "date"
                            item.setdefault("bar_count", len(df_t))
                            item.setdefault("period", task["period"])
                            item.setdefault("range_start", _format_range_boundary(df_t[time_col].iloc[0], task["period"]))
                            item.setdefault("range_end", _format_range_boundary(df_t[time_col].iloc[-1], task["period"]))
                    _apply_finished(finished)

            for task in empty_tasks:
                _apply_finished(
                    {
                        "ok": False,
                        "code": task["code"],
                        "name": task["name"],
                        "message": "选定区间内暂无可用数据",
                        "index": task["index"],
                    }
                )

    node_used = (
        "pi" if any_node_pi and not any_node_local
        else "local" if any_node_local and not any_node_pi
        else "mixed" if any_node_pi and any_node_local
        else ""
    )

    if not success_items:
        message = "全量回测未得到有效结果，请检查数据下载和回测区间"
        _set_state(
            running=False,
            progress_pct=100,
            current_step="失败",
            message=message,
            result={"success": False, "message": message, "mode": "batch"},
            error=message,
            completed_targets=total_targets,
            total_targets=total_targets,
            success_targets=0,
            failed_targets=len(failed_items),
            node_used=node_used,
        )
        return

    summary = _build_full_backtest_summary(
        strategy=strategy,
        period=period,
        start_date=start_date,
        end_date=end_date,
        total_targets=total_targets,
        success_items=success_items,
        failed_items=failed_items,
    )
    _set_state(
        progress_pct=97,
        current_step="整理极值明细",
        message="正在补充最大回撤和最大涨幅的详细交易信息...",
    )
    max_drawdown_detail = _build_batch_extreme_detail(
        summary.get("max_drawdown_item"),
        strategy=strategy,
        period=period,
        start_date=start_date,
        end_date=end_date,
        cash=cash,
        min_quality_score=min_quality_score,
    )
    max_gain_detail = _build_batch_extreme_detail(
        summary.get("max_gain_item"),
        strategy=strategy,
        period=period,
        start_date=start_date,
        end_date=end_date,
        cash=cash,
        min_quality_score=min_quality_score,
    )
    run_id = db.save_full_backtest_run(
        strategy_name=strategy,
        period=period,
        start_date=summary["range_start"],
        end_date=summary["range_end"],
        target_count=summary["target_count"],
        success_count=summary["success_count"],
        failed_count=summary["failed_count"],
        profitable_count=summary["success_count"],
        loss_count=summary["failed_count"],
        win_rate=summary["win_rate"],
        cumulative_return=summary["cumulative_return"],
        average_return=summary["average_return"],
        max_drawdown=summary["max_drawdown"],
        max_gain=summary["max_gain"],
        payload={
            "cash": cash,
            "min_quality_score": min_quality_score,
            "summary": summary,
            "profitable_items": summary.get("profitable_items", []),
            "loss_items": summary.get("loss_items", []),
            "top_successes": sorted(
                (
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "total_return": round(float(item.get("total_return", 0) or 0), 2),
                        "max_drawdown": round(float(item.get("max_drawdown", 0) or 0), 2),
                    }
                    for item in success_items
                ),
                key=lambda row: row["total_return"],
                reverse=True,
            )[:10],
            "top_losses": sorted(
                (
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "total_return": round(float(item.get("total_return", 0) or 0), 2),
                        "max_drawdown": round(float(item.get("max_drawdown", 0) or 0), 2),
                    }
                    for item in success_items
                ),
                key=lambda row: row["total_return"],
            )[:10],
            "max_drawdown_item": summary.get("max_drawdown_item"),
            "max_gain_item": summary.get("max_gain_item"),
            "max_drawdown_detail": max_drawdown_detail,
            "max_gain_detail": max_gain_detail,
            "failed_items": failed_items[:30],
        },
        owner_username=owner_username,
    )

    result = {
        "success": True,
        "mode": "batch",
        "strategy_name": strategy,
        "period": period,
        "range_start": summary["range_start"],
        "range_end": summary["range_end"],
        "batch_run_id": run_id,
        "batch_summary": summary,
        "owner_username": owner_username,
        "message": "全量回测完成",
        "node_used": node_used,
    }
    _set_state(
        running=False,
        progress_pct=100,
        current_step="完成",
        message=f"全量回测完成，成功 {summary['success_count']} / {summary['target_count']} 个目标",
        result=result,
        error="",
        completed_targets=total_targets,
        total_targets=total_targets,
        success_targets=summary["success_count"],
        failed_targets=summary["failed_count"],
        node_used=node_used,
    )


def _run_backtest_job(params: dict):
    code = params["code"]
    name = params.get("name", "")
    strategy = params["strategy"]
    start_date = params["start_date"]
    end_date = params["end_date"]
    cash = params["cash"]
    period = params["period"]
    mode = str(params.get("mode", "single") or "single").lower()
    min_quality_score = int(params.get("min_quality_score") or 0)
    owner_username = params.get("owner_username")

    node_used = ""
    try:
        if mode == "full":
            _run_full_backtest_job(params)
            return
        _set_state(
            mode="single",
            progress_pct=5,
            current_step="初始化任务",
            message="正在准备回测任务...",
            total_targets=1,
            completed_targets=0,
            success_targets=0,
            failed_targets=0,
            current_target_index=1,
            current_target_code=code,
            current_target_name=name or code,
            result=None,
            error="",
        )
        if period in MINUTE_PERIODS:
            _set_state(progress_pct=15, current_step="拉取分钟数据", message="正在从 pytdx 拉取分钟K线...")
            if _direct_minute_period(period) is None:
                message = f"分钟周期 {period} 暂无原生接口支持"
                _set_state(
                    running=False,
                    mode="single",
                    progress_pct=100,
                    current_step="失败",
                    message=message,
                    total_targets=1,
                    completed_targets=1,
                    success_targets=0,
                    failed_targets=1,
                    current_target_index=1,
                    current_target_code=code,
                    current_target_name=name or code,
                    result={"success": False, "message": message},
                    error=message,
                )
                return
            _set_state(progress_pct=28, current_step="过滤分钟区间", message="正在过滤分钟K线区间...")
        else:
            _set_state(progress_pct=15, current_step="拉取日线数据", message="正在获取回测所需日线数据...")
            _set_state(progress_pct=35, current_step="过滤日线区间", message="正在过滤回测日期区间...")

        df = _load_backtest_dataframe_with_retry(code, name, period, start_date, end_date)

        if df is None or df.empty:
            message = "选定区间内暂无可用数据，请调整回测区间或周期"
            _set_state(
                running=False,
                mode="single",
                progress_pct=100,
                current_step="失败",
                message=message,
                total_targets=1,
                completed_targets=1,
                success_targets=0,
                failed_targets=1,
                current_target_index=1,
                current_target_code=code,
                current_target_name=name or code,
                result={"success": False, "message": message},
                error=message,
            )
            return

        _set_state(progress_pct=55, current_step="准备运行策略", message="数据准备完成，正在启动回测引擎...")

        def progress_callback(progress_pct: int, message: str, current_step: str):
            _set_state(progress_pct=progress_pct, message=message, current_step=current_step)

        # 先尝试卸载到 Pi 节点；None 表示节点不可用/传输失败 → 回落本机
        node_used = "local"
        remote_result = None
        if remote.offload_enabled_for("single"):
            _set_state(progress_pct=60, current_step="远端节点回测中", message="正在将回测卸载到 Pi 节点...")
            remote_result = remote.run_single_on_node(
                df,
                strategy_name=strategy,
                cash=cash,
                commission=0.0001,
                lightweight=False,
                include_equity_curve=False,
                period=period,
                min_quality_score=min_quality_score,
            )
            if remote_result is not None:
                node_used = "pi"

        if remote_result is None:
            # 本地执行，保留细粒度进度回调
            result = run_backtest(
                df,
                strategy_name=strategy,
                cash=cash,
                progress_callback=progress_callback,
                period=period,
                min_quality_score=min_quality_score,
            )
        else:
            # 节点已执行（成功或业务失败都采用）；细粒度进度跨网不可用，跳到 90
            result = remote_result
            _set_state(progress_pct=90, current_step="远端结果已返回", message="Pi 节点回测完成，正在汇总...")
        if result.get("success"):
            time_col = "datetime" if "datetime" in df.columns else "date"
            result["bar_count"] = len(df)
            result["period"] = period
            result["strategy_name"] = strategy
            result["owner_username"] = owner_username
            result["range_start"] = _format_range_boundary(df[time_col].iloc[0], period)
            result["range_end"] = _format_range_boundary(df[time_col].iloc[-1], period)

        final_message = "回测完成" if result.get("success") else result.get("message", "回测失败")
        _set_state(
            running=False,
            mode="single",
            progress_pct=100,
            current_step="完成" if result.get("success") else "失败",
            message=final_message,
            total_targets=1,
            completed_targets=1,
            success_targets=1 if result.get("success") else 0,
            failed_targets=0 if result.get("success") else 1,
            current_target_index=1,
            current_target_code=code,
            current_target_name=name or code,
            result=result,
            error="" if result.get("success") else final_message,
            node_used=node_used,
        )
    except Exception as exc:
        _set_state(
            running=False,
            mode="single",
            progress_pct=100,
            current_step="失败",
            message=str(exc),
            total_targets=1,
            completed_targets=1,
            success_targets=0,
            failed_targets=1,
            current_target_index=1,
            current_target_code=code,
            current_target_name=name or code,
            result={"success": False, "message": str(exc)},
            error=str(exc),
            node_used=node_used,
        )


def start_backtest_job(
    code: str,
    name: str,
    strategy: str,
    start_date: str,
    end_date: str,
    cash: float,
    period: str,
    mode: str = "single",
    owner_username: Optional[str] = None,
    min_quality_score: int = 0,
) -> dict:
    current = get_backtest_status()
    if current["running"]:
        return {
            "success": False,
            "message": "已有回测任务正在运行，请稍候",
            "data": current,
        }

    job_id = f"BT{now_beijing().strftime('%Y%m%d%H%M%S%f')}"
    _set_state(
        job_id=job_id,
        running=True,
        mode=str(mode or "single").lower(),
        progress_pct=0,
        current_step="排队中",
        message="回测任务已创建，准备启动...",
        total_targets=0,
        completed_targets=0,
        success_targets=0,
        failed_targets=0,
        current_target_index=0,
        current_target_code="",
        current_target_name="",
        result=None,
        error="",
        node_used="",
    )
    _executor.submit(
        _run_backtest_job,
        {
            "code": code,
            "name": name,
            "strategy": strategy,
            "start_date": start_date,
            "end_date": end_date,
            "cash": cash,
            "period": period,
            "mode": mode,
            "owner_username": owner_username,
            "min_quality_score": int(min_quality_score or 0),
        },
    )
    return {
        "success": True,
        "data": get_backtest_status(),
    }
