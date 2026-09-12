from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from backend import db
from backend import auth_service
from backend.market import akshare_data
from backend.time_utils import now_beijing

from .data_loader import load_local_kline_df, merge_scan_realtime_tail
from .periods import (
    get_min_scan_bars,
    get_signal_time_format,
    get_time_col_for_period,
    is_completed_scan_bar,
    normalize_scan_period,
    resolve_latest_completed_slot,
    resolve_run_slot,
    scan_period_to_chart_period,
)
from .readiness import get_scan_readiness
from .runtime import (
    SCAN_LOCK,
    append_completion_time,
    reset_progress_state,
    runtime_state,
    set_running,
    update_progress_state,
)
from .strategies import get_strategy
from backend.system_utils import get_optimal_worker_count

SCAN_MAX_WORKERS = get_optimal_worker_count("cpu", max_limit=16)
SIGNAL_LOOKBACK_BARS = 8


def _signal_trade_day_text(value: str) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def _get_recent_signals_for_code(
    code: str,
    name: str,
    strategy_name: str,
    scan_period: str,
    now: datetime,
    *,
    is_trading_day: bool = True,
) -> list[dict]:
    scan_period = normalize_scan_period(scan_period)
    min_scan_bars = get_min_scan_bars(scan_period)
    time_col = get_time_col_for_period(scan_period)
    signal_time_format = get_signal_time_format(scan_period)
    df = load_local_kline_df(code=code, period=scan_period, limit=min_scan_bars)
    if df is None or df.empty:
        return []
    if is_trading_day:
        df = merge_scan_realtime_tail(df, code, scan_period, min_scan_bars)
        if df.empty:
            return []

    if scan_period in {"1min", "5min", "15min", "30min", "60min"} and is_trading_day:
        expected_slot = resolve_latest_completed_slot(now, scan_period, is_trading_date=is_trading_day)
        if expected_slot is None:
            return []
        latest_bar_ts = pd.Timestamp(df.iloc[-1][time_col])
        if not is_completed_scan_bar(latest_bar_ts, now, scan_period, is_trading_date=is_trading_day):
            return []  # 实时数据尚未跟上最新完成槽位
        # 剔除实时尾巴里未完成的 forming bar（pytdx 以周期结束时间戳标记），
        # 只让已完成K线进入策略，避免用半根bar计算指标。
        trimmed = df[pd.to_datetime(df[time_col], errors="coerce", utc=True, format="mixed") <= expected_slot]
        if trimmed.empty:
            return []
        df = trimmed.reset_index(drop=True)

    strategy = get_strategy(strategy_name)
    signals = strategy.generate_signals(df, code=code, name=name)
    if not signals:
        return []

    lookback_df = df.tail(SIGNAL_LOOKBACK_BARS)
    lookback_times = set()
    for _, row in lookback_df.iterrows():
        ts = pd.Timestamp(row[time_col])
        lookback_times.add(ts.strftime(signal_time_format))

    recent_signals = []
    for sig in signals:
        signal_time = pd.Timestamp(sig.time).strftime(signal_time_format)
        if signal_time in lookback_times:
            recent_signals.append(
                {
                    "code": code,
                    "name": name,
                    "direction": sig.direction,
                    "price": round(float(sig.price), 5),
                    "signal_time": signal_time,
                    "reason": sig.reason,
                    "strategy_name": strategy_name,
                    "period": scan_period_to_chart_period(scan_period),
                    "run_slot": signal_time,
                }
            )

    if not any(item["direction"] == "buy" for item in recent_signals):
        return []

    filtered = []
    found_first_buy = False
    current_entry_trade_day = ""
    for item in recent_signals:
        if item["direction"] == "buy":
            found_first_buy = True
            current_entry_trade_day = _signal_trade_day_text(item["signal_time"])
            filtered.append(item)
        elif found_first_buy:
            if current_entry_trade_day and _signal_trade_day_text(item["signal_time"]) <= current_entry_trade_day:
                # A股按 T+1 处理，盘中扫描不展示买入当日就触发的卖点。
                continue
            filtered.append(item)
            if item["direction"] == "sell":
                current_entry_trade_day = ""

    # 过滤掉"买卖"模式：如果最后一个信号是卖出，说明已清仓，无操作价值
    # 只保留：只有买（持仓中）、或买卖买（卖出后再次买入持仓）
    if filtered and filtered[-1]["direction"] == "sell":
        return []

    return filtered


def run_scan_if_needed(force: bool = False, current_user: dict | None = None) -> list[dict]:
    if not SCAN_LOCK.acquire(blocking=False):
        return []

    set_running(True)
    try:
        settings = db.get_scan_settings()
        if not force and not settings["enabled"]:
            return []

        now = now_beijing()  # 服务器时区≠北京，交易时段/slot 判断必须用北京时间为锚
        is_trading_day = akshare_data.is_trading_date(now)
        scan_period = normalize_scan_period(settings.get("scan_period"))
        run_slot = resolve_run_slot(now, scan_period, is_trading_date=is_trading_day)
        run_slot_key = f"{scan_period}:{run_slot}" if run_slot else None
        if not force:
            if not run_slot:
                return []
            if run_slot_key == runtime_state["last_run_slot"]:
                return []

        strategy_name = settings["strategy_name"]
        strategy_user = current_user if force else auth_service.get_active_user_by_username(
            settings.get("strategy_owner_username")
        )
        access = auth_service.get_strategy_access(strategy_name, strategy_user)
        if not access["allowed"]:
            runtime_state["current_message"] = str(access.get("message") or "当前策略需要登录")
            if force:
                raise auth_service.StrategyAccessDenied(
                    runtime_state["current_message"],
                    int(access.get("status_code") or 401),
                )
            return []
        readiness = get_scan_readiness()
        if not readiness["scan_ready"]:
            runtime_state["current_message"] = readiness["message"]
            return []

        owner_username = auth_service.get_visible_owner_username(strategy_user)
        run_id = db.create_scan_run(
            strategy_name,
            trigger_type="manual" if force else "auto",
            owner_username=owner_username,
        )
        candidates = list(readiness["candidates"])
        runtime_state["total_count"] = len(candidates)
        scanned_count = 0
        new_alerts: list[dict] = []

        try:
            def scan_one(item: dict) -> list[dict]:
                return _get_recent_signals_for_code(
                    item["code"],
                    item["name"],
                    strategy_name,
                    scan_period,
                    now,
                    is_trading_day=is_trading_day,
                )

            max_workers = max(1, min(SCAN_MAX_WORKERS, len(candidates) or 1))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {executor.submit(scan_one, item): item for item in candidates}
                for index, future in enumerate(as_completed(future_to_item), start=1):
                    item = future_to_item[future]
                    code = item["code"]
                    name = item["name"]
                    try:
                        alerts = future.result()
                    except Exception:
                        alerts = []
                    scanned_count += 1
                    append_completion_time(now_beijing())
                    update_progress_state(code, name, index, len(candidates))
                    for alert in alerts:
                        try:
                            stored = db.insert_scan_signal(
                                code=alert["code"],
                                name=alert["name"],
                                direction=alert["direction"],
                                price=alert["price"],
                                signal_time=alert["signal_time"],
                                reason=alert["reason"],
                                strategy_name=alert["strategy_name"],
                                period=alert["period"],
                                run_slot=alert.get("run_slot") or run_slot_key or f"manual-{now.strftime('%Y%m%d%H%M%S')}",
                                run_id=run_id,
                                owner_username=owner_username,
                            )
                            if stored:
                                new_alerts.append(stored)
                        except Exception:
                            continue

            db.finish_scan_run(
                run_id=run_id,
                candidate_count=len(candidates),
                scanned_count=scanned_count,
                signal_count=len(new_alerts),
                status="success",
                message="",
            )
            if run_slot:
                runtime_state["last_run_slot"] = run_slot_key or run_slot
            return new_alerts
        except Exception as exc:
            db.finish_scan_run(
                run_id=run_id,
                candidate_count=len(candidates),
                scanned_count=scanned_count,
                signal_count=len(new_alerts),
                status="failed",
                message=str(exc),
            )
            raise
    finally:
        set_running(False)
        reset_progress_state()
        SCAN_LOCK.release()
