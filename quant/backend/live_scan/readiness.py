from __future__ import annotations

from backend import db
from backend.config import LOCAL_KLINE_CACHE_RULES
from backend.history_download_service import get_history_download_status
from backend.kline_service import get_local_history_ready
from backend.market import akshare_data
from backend.time_utils import now_beijing

from .data_loader import load_scan_universe_candidates, normalize_selected_codes
from .periods import (
    get_required_periods,
    get_scan_period_label,
    is_market_session_time,
    normalize_scan_period,
    resolve_latest_completed_slot,
)


SESSION_CLOSE_PERIODS = ("daily", "weekly", "monthly")


def _session_close_download_pending(now, scan_period: str, download_status: dict) -> str | None:
    """日/周/月线收盘扫描的等待闸门：当天数据下载好以后，当天收盘扫描才开始。

    15:00 收盘 slot 与当天自动下载同一时刻触发，下载没完成前本地日K末根还是
    昨天，抢先扫出来的信号全是"非当天"的，被前端按扫描日期过滤后整轮空结果，
    还把当天 slot 消耗掉（下载完成后不再补扫）。这里在 15:00 后把收盘扫描挂起
    （不消耗 slot，auto_scan_task 每 20 秒探测一次），等当天日K下载完成
    （auto_download_today_done）后自动放行，配合 config 里拉长到 23:00 的缓冲
    窗口，下载再慢/失败重试后当天扫描照样触发。

    只在「自动下载开启」时守着——用户关掉自动下载等于自己接管数据时效，不拦。
    非交易日 / 15:00 前 / 交易日判断失败一律放行（闸门只做等待，不做硬卡）。
    """
    if normalize_scan_period(scan_period) not in SESSION_CLOSE_PERIODS:
        return None
    if now.strftime("%H:%M") < "15:00":
        return None
    try:
        if not akshare_data.is_trading_date(now):
            return None
    except Exception:
        return None
    today = now.strftime("%Y-%m-%d")
    done = (
        str(download_status.get("auto_download_today") or "") == today
        and bool(download_status.get("auto_download_today_done"))
    )
    if done:
        return None
    if not bool(download_status.get("auto_download_enabled")):
        return None
    label = get_scan_period_label(scan_period)
    return (
        f"当天日K数据尚未下载完成，{label}收盘扫描已挂起：下载完成后自动开始，"
        "无需手动触发，期间不消耗当天扫描轮次。"
    )


def get_scan_scope_candidates(page: int = 1, page_size: int = 50, keyword: str = "") -> dict:
    settings = db.get_scan_settings()
    scan_period = normalize_scan_period(settings.get("scan_period"))
    requirements = {
        period: int(LOCAL_KLINE_CACHE_RULES.get(period, {}).get("min_bars", 160))
        for period in get_required_periods(scan_period)
    }
    return db.list_ready_price_history_candidates(
        requirements,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )


def get_scan_readiness() -> dict:
    now = now_beijing()  # 服务器时区≠北京，交易时段/slot 判断必须用北京时间为锚
    candidates = load_scan_universe_candidates()
    total_count = len(candidates)
    download_status = get_history_download_status()
    settings = db.get_scan_settings()
    scan_period = normalize_scan_period(settings.get("scan_period"))
    scan_period_label = get_scan_period_label(scan_period)
    required_periods = get_required_periods(scan_period)
    required_period_labels = "和".join(get_scan_period_label(period) for period in required_periods)
    scan_scope_type = str(settings.get("scan_scope_type") or "all")
    scan_scope_codes = normalize_selected_codes(settings.get("scan_scope_codes") or [])
    scan_focus_codes = normalize_selected_codes(settings.get("scan_focus_codes") or [])
    if scan_scope_type == "selected":
        scan_focus_codes = []

    if total_count == 0:
        return {
            "scan_ready": False,
            "message": "请先在数据下载中生成并下载股票池后再开始扫描。",
            "scan_universe_count": 0,
            "local_ready_count": 0,
            "required_periods": list(required_periods),
            "scan_period": scan_period,
            "scan_period_label": scan_period_label,
            "scan_scope_type": scan_scope_type,
            "scan_scope_codes": scan_scope_codes,
            "scan_focus_codes": scan_focus_codes,
            "candidates": [],
        }

    # 逐股"本地K线就绪"判定,所有分支共用同一口径(sync_state 存在且根数达标,
    # 不随一天内的时刻变化)。下载中/收盘挂起分支此前误用下载状态的
    # qualified_count(上一次规则下载站上144均线的数量,下载启动即清0)充当
    # local_ready_count,导致挂起期间面板显示"立即扫描(0)/还有N只未满足条件"
    # ——那不是逐股判定的结果,是分支切换带来的字段语义错位。
    ready_candidates = [
        item
        for item in candidates
        if all(get_local_history_ready(item["code"], period) for period in required_periods)
    ]
    if scan_scope_type == "selected":
        selected_codes_set = set(scan_scope_codes)
        ready_candidates = [item for item in ready_candidates if item["code"] in selected_codes_set]
    ready_count = len(ready_candidates)
    universe_count = total_count if scan_scope_type != "selected" else len(scan_scope_codes)

    if download_status.get("running"):
        return {
            "scan_ready": False,
            "message": "数据下载正在执行，必须等三步流程全部完成后才能开始本地扫描。",
            "scan_universe_count": universe_count,
            "local_ready_count": ready_count,
            "required_periods": list(required_periods),
            "scan_period": scan_period,
            "scan_period_label": scan_period_label,
            "scan_scope_type": scan_scope_type,
            "scan_scope_codes": scan_scope_codes,
            "scan_focus_codes": scan_focus_codes,
            "candidates": [],
        }

    pending_message = _session_close_download_pending(now, scan_period, download_status)
    if pending_message:
        return {
            "scan_ready": False,
            "message": pending_message,
            "scan_universe_count": universe_count,
            "local_ready_count": ready_count,
            "required_periods": list(required_periods),
            "scan_period": scan_period,
            "scan_period_label": scan_period_label,
            "scan_scope_type": scan_scope_type,
            "scan_scope_codes": scan_scope_codes,
            "scan_focus_codes": scan_focus_codes,
            "candidates": [],
        }

    if scan_scope_type == "selected" and not scan_scope_codes:
        return {
            "scan_ready": False,
            "message": "当前扫描模式为指定股票，请先勾选至少一只已下载完成的股票。",
            "scan_universe_count": 0,
            "local_ready_count": 0,
            "required_periods": list(required_periods),
            "scan_period": scan_period,
            "scan_period_label": scan_period_label,
            "scan_scope_type": scan_scope_type,
            "scan_scope_codes": scan_scope_codes,
            "scan_focus_codes": scan_focus_codes,
            "candidates": [],
        }

    if scan_period in {"1min", "5min", "15min", "30min", "60min"} and is_market_session_time(now) and akshare_data.is_trading_date(now):
        slot = resolve_latest_completed_slot(now, scan_period, is_trading_date=akshare_data.is_trading_date(now))
        if slot is None:
            return {
                "scan_ready": False,
                "message": f"当前还没有形成完整的{scan_period_label}K线，请在首个{scan_period_label}槽位完成后再扫描。",
                "scan_universe_count": total_count,
                "local_ready_count": ready_count,
                "required_periods": list(required_periods),
                "scan_period": scan_period,
                "scan_period_label": scan_period_label,
                "scan_scope_type": scan_scope_type,
                "scan_scope_codes": scan_scope_codes,
                "scan_focus_codes": scan_focus_codes,
                "candidates": [],
            }

    if scan_scope_type == "selected":
        expected_total = len(scan_scope_codes)
        if ready_count < expected_total:
            return {
                "scan_ready": False,
                "message": (
                    f"当前扫描范围共 {expected_total} 只，本地完成{required_period_labels}K线的股票为 {ready_count} 只。"
                    "需要等数据下载全部完成后再开始本地扫描。"
                ),
                "scan_universe_count": expected_total,
                "local_ready_count": ready_count,
                "required_periods": list(required_periods),
                "scan_period": scan_period,
                "scan_period_label": scan_period_label,
                "scan_scope_type": scan_scope_type,
                "scan_scope_codes": scan_scope_codes,
                "scan_focus_codes": scan_focus_codes,
                "candidates": [],
            }
    elif ready_count == 0:
        return {
            "scan_ready": False,
            "message": f"当前没有本地完成{required_period_labels}K线的股票，请先下载历史数据。",
            "scan_universe_count": total_count,
            "local_ready_count": 0,
            "required_periods": list(required_periods),
            "scan_period": scan_period,
            "scan_period_label": scan_period_label,
            "scan_scope_type": scan_scope_type,
            "scan_scope_codes": scan_scope_codes,
            "scan_focus_codes": scan_focus_codes,
            "candidates": [],
        }

    return {
        "scan_ready": True,
        "message": (
            f"当前按{scan_period_label}可扫描 "
            f"{ready_count}/{total_count if scan_scope_type != 'selected' else len(scan_scope_codes)} 只股票，"
            "扫描时仅使用本地历史数据并叠加盘中实时行情。"
        ),
        "scan_universe_count": total_count if scan_scope_type != "selected" else len(scan_scope_codes),
        "local_ready_count": ready_count,
        "required_periods": list(required_periods),
        "scan_period": scan_period,
        "scan_period_label": scan_period_label,
        "scan_scope_type": scan_scope_type,
        "scan_scope_codes": scan_scope_codes,
        "scan_focus_codes": scan_focus_codes,
        "candidates": ready_candidates,
    }
