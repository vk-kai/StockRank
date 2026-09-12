from __future__ import annotations

from typing import Optional

from backend import auth_service
from backend import db
from backend.market import akshare_data
from backend.time_utils import now_beijing

from .periods import normalize_scan_period, resolve_next_run_slot
from .readiness import get_scan_readiness
from .runtime import runtime_state
from .strategies import list_strategies


def _user_visible_settings(settings: dict, user: Optional[dict]) -> dict:
    visible = dict(settings)
    access = auth_service.get_strategy_access(str(visible.get("strategy_name") or ""), user)
    if not access["allowed"]:
        visible["strategy_name"] = auth_service.get_default_strategy_for_user(user)
    visible["default_strategy"] = auth_service.get_default_strategy_for_user(user)
    return visible


def get_scan_status(user: Optional[dict] = None) -> dict:
    settings = db.get_scan_settings()
    settings = _user_visible_settings(settings, user)
    owner_username = auth_service.get_visible_owner_username(user)
    effective_focus_codes = (
        list(settings.get("scan_focus_codes") or [])
        if settings.get("scan_scope_type") != "selected"
        else []
    )
    latest_run = db.get_latest_scan_run(owner_username=owner_username)
    recent_runs = db.list_scan_runs(limit=20, owner_username=owner_username)
    recent_signals = db.list_scan_signals(limit=500, owner_username=owner_username)
    unread_count = len(recent_signals)
    readiness = get_scan_readiness()
    # 下次自动扫描时间(北京时间锚定)：开启自动扫描才有意义
    now = now_beijing()
    is_trading_day = akshare_data.is_trading_date(now)
    next_scan_dt = None
    if settings.get("enabled"):
        next_scan_dt = resolve_next_run_slot(
            now, settings.get("scan_period"), is_trading_date=is_trading_day
        )
    return {
        **settings,
        "scan_focus_codes": effective_focus_codes,
        "running": bool(runtime_state["running"]),
        "last_run_slot": runtime_state["last_run_slot"],
        "current_code": runtime_state["current_code"],
        "current_name": runtime_state["current_name"],
        "current_index": runtime_state["current_index"],
        "total_count": runtime_state["total_count"],
        "progress_pct": runtime_state["progress_pct"],
        "current_message": runtime_state["current_message"],
        "estimated_remaining_seconds": int(runtime_state.get("estimated_remaining_seconds") or 0),
        "latest_run": latest_run,
        "recent_runs": recent_runs,
        "recent_signals": recent_signals,
        "unread_count": unread_count,
        "scan_ready": bool(readiness["scan_ready"]),
        "scan_ready_message": readiness["message"],
        "scan_universe_count": int(readiness["scan_universe_count"]),
        "local_ready_count": int(readiness["local_ready_count"]),
        "required_periods": readiness["required_periods"],
        "scan_period": readiness["scan_period"],
        "scan_period_label": readiness["scan_period_label"],
        "is_trading_day": bool(is_trading_day),
        "next_scan_at": next_scan_dt.strftime("%Y-%m-%d %H:%M:%S") if next_scan_dt else None,
    }


def update_scan_settings(
    enabled: Optional[bool] = None,
    strategy_name: Optional[str] = None,
    interval_minutes: Optional[int] = None,
    scan_scope_type: Optional[str] = None,
    scan_scope_codes: Optional[list[str]] = None,
    scan_focus_codes: Optional[list[str]] = None,
    scan_period: Optional[str] = None,
    auto_download_enabled: Optional[bool] = None,
    auto_download_hour: Optional[int] = None,
    kline_force_refresh: Optional[bool] = None,
    current_user: Optional[dict] = None,
) -> dict:
    normalized_strategy_name = strategy_name
    if strategy_name is not None:
        available = [item["name"] for item in list_strategies()]
        if strategy_name not in available:
            normalized_strategy_name = auth_service.get_default_strategy_for_user(current_user)
        access = auth_service.get_strategy_access(str(normalized_strategy_name), current_user)
        if not access["allowed"]:
            raise auth_service.StrategyAccessDenied(
                str(access.get("message") or "无权使用该策略"),
                int(access.get("status_code") or 401),
            )

    owner_username = None
    if normalized_strategy_name is not None or enabled is not None:
        target_strategy = normalized_strategy_name or db.get_scan_settings().get("strategy_name")
        access = auth_service.get_strategy_access(str(target_strategy), current_user)
        if not access["allowed"]:
            raise auth_service.StrategyAccessDenied(
                str(access.get("message") or "无权使用该策略"),
                int(access.get("status_code") or 401),
            )
        owner_username = (current_user or {}).get("username") or ""

    db.update_scan_settings(
        enabled=enabled,
        strategy_name=normalized_strategy_name,
        interval_minutes=interval_minutes,
        scan_scope_type=scan_scope_type,
        scan_scope_codes=scan_scope_codes,
        scan_focus_codes=scan_focus_codes,
        scan_period=normalize_scan_period(scan_period) if scan_period is not None else None,
        auto_download_enabled=auto_download_enabled,
        auto_download_hour=auto_download_hour,
        kline_force_refresh=kline_force_refresh,
        strategy_owner_username=owner_username,
    )
    return get_scan_status(current_user)


def mark_signal_alerts_read(signal_ids: list[int]):
    db.delete_scan_signals(signal_ids)
