import asyncio
import json
import logging
import math
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path
from typing import Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.arb.engine import run_arb_tick
from backend.auto_scan import normalize_scan_period, run_scan_if_needed
from backend.history_download_service import (
    append_history_log,
    get_history_download_status,
    is_auto_download_done_today,
    set_auto_download_schedule_status,
    start_history_download,
)
from backend import db
from backend.config import ARB_MONITOR_INTERVAL_SECONDS, CORS_ORIGINS, REALTIME_PUSH_INTERVAL
from backend.api.market import router as market_router
from backend.api.arb import router as arb_router
from backend.api.trading import router as trading_router
from backend.api.backtest import router as backtest_router
from backend.api.auth import router as auth_router
from backend.api.system import router as system_router
from backend.market import akshare_data, pytdx_data
from backend.paths import ensure_log_dir
from backend.security_service import ensure_runtime_db_ready
from backend.node_state import pi_node_health_task
from backend.time_utils import now_beijing
from backend.trading.account import load_account, update_position_prices


def _configure_logging():
    log_dir = ensure_log_dir()
    log_file = Path(log_dir) / "app.log"
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.ERROR)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)


_configure_logging()
logger = logging.getLogger(__name__)

AUTO_DOWNLOAD_START_HOUR = 15
AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS = 10 * 60
AUTO_DOWNLOAD_RETRY_INTERVAL_SECONDS = 60 * 60
# 日线覆盖判定的比例门槛:停牌股/单只源滞后当天永远没有当日bar,100% 门槛会让
# already_updated 永远不触发。95% 容忍零星掉队,池子大面积缺当天bar仍判"未更新"。
AUTO_DOWNLOAD_COVERAGE_MIN_RATIO = 0.95


def _normalize_auto_download_hour(value) -> int:
    try:
        hour = int(value)
    except Exception:
        hour = AUTO_DOWNLOAD_START_HOUR
    return min(23, max(AUTO_DOWNLOAD_START_HOUR, hour))


def _get_daily_kline_update_coverage(trade_date: str) -> dict:
    try:
        from backend.kline_parquet import get_kline_sync_state

        rows = db.list_stock_pool(scan_eligible_only=True)
        codes = [str(item.get("code") or "").strip().zfill(6) for item in rows if str(item.get("code") or "").strip()]
        if not codes:
            return {"updated": False, "updated_count": 0, "total_count": 0, "threshold": 1}

        updated_count = 0
        for code in codes:
            state = get_kline_sync_state(code, "daily") or {}
            last_bar_time = str(state.get("last_bar_time") or "")
            if last_bar_time.startswith(trade_date):
                updated_count += 1

        threshold = max(1, math.ceil(len(codes) * AUTO_DOWNLOAD_COVERAGE_MIN_RATIO))
        return {
            "updated": updated_count >= threshold,
            "updated_count": updated_count,
            "total_count": len(codes),
            "threshold": threshold,
        }
    except Exception as exc:
        logger.warning("Failed to check daily kline coverage: %s", exc)
        return {"updated": False, "updated_count": 0, "total_count": 0, "threshold": 1}

app = FastAPI(title="证券辅助决策终端", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router)
app.include_router(arb_router)
app.include_router(trading_router)
app.include_router(backtest_router)
app.include_router(auth_router)
app.include_router(system_router)

FRONTEND_DIST_DIR = Path("/app/frontend_dist")


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.subscriptions: dict = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket连接, 当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        self.subscriptions.pop(id(websocket), None)
        logger.info(f"WebSocket断开, 当前连接数: {len(self.active_connections)}")

    def subscribe(self, websocket: WebSocket, codes: list):
        self.subscriptions[id(websocket)] = {"ws": websocket, "codes": codes}

    def unsubscribe(self, websocket: WebSocket):
        self.subscriptions.pop(id(websocket), None)

    async def broadcast(self, payload: dict):
        for websocket in list(self.active_connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(websocket)


manager = ConnectionManager()


def _build_realtime_payload_snapshot(codes: list[str]) -> tuple[dict, dict | None]:
    quotes = pytdx_data.get_realtime_quotes(codes)
    index_quotes = akshare_data.get_major_index_quotes(codes)

    quote_map = {q["code"]: q for q in quotes}
    quote_map.update({q["code"]: q for q in index_quotes})
    if not quote_map:
        return {}, None

    account = load_account()
    price_updates = {}
    for q in quote_map.values():
        if q["code"] in account.positions:
            price_updates[q["code"]] = q["price"]
    if price_updates:
        update_position_prices(account, price_updates)

    return quote_map, account.to_dict()


@app.websocket("/ws/realtime")
async def websocket_realtime(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "subscribe":
                    codes = msg.get("codes", [])
                    manager.subscribe(websocket, codes)
                    await websocket.send_json({"type": "subscribed", "codes": codes})
                elif msg.get("type") == "unsubscribe":
                    manager.unsubscribe(websocket)
                    await websocket.send_json({"type": "unsubscribed"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# 盘外(收盘后/周末)推送降频间隔:价格不再变化,3 秒推一次纯属无谓请求
REALTIME_PUSH_OFF_INTERVAL = 30


def _likely_trading_time() -> bool:
    """A股粗略交易时段(工作日 09:15-15:15 北京时间,不含节假日)。

    只用于实时推送降频;判错顶多推送快/慢一点,数据正确性不受影响。
    """
    now = now_beijing()
    if now.weekday() >= 5:
        return False
    hhmm = now.strftime("%H:%M")
    return "09:15" <= hhmm <= "15:15"


async def realtime_push_task():
    while True:
        try:
            if manager.subscriptions:
                all_codes = set()
                for sub in manager.subscriptions.values():
                    all_codes.update(sub["codes"])

                if all_codes:
                    quote_map, account_data = await asyncio.to_thread(
                        _build_realtime_payload_snapshot, list(all_codes)
                    )
                    if quote_map and account_data is not None:
                        for sub in manager.subscriptions.values():
                            ws = sub["ws"]
                            codes = sub["codes"]
                            data = [quote_map.get(c, {}) for c in codes if c in quote_map]
                            try:
                                await ws.send_json({
                                    "type": "quotes",
                                    "data": data,
                                    "account": account_data,
                                    "time": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
                                })
                            except Exception:
                                pass

            # 盘内 3 秒实时推;盘外价格不动,降频到 30 秒防无谓请求
            await asyncio.sleep(REALTIME_PUSH_INTERVAL if _likely_trading_time() else REALTIME_PUSH_OFF_INTERVAL)
        except Exception as e:
            logger.error(f"实时推送任务异常: {e}")
            await asyncio.sleep(5)


async def auto_scan_task():
    while True:
        try:
            alerts = await asyncio.to_thread(run_scan_if_needed, False)
            if alerts:
                await manager.broadcast({
                    "type": "scan_alerts",
                    "data": alerts,
                    "time": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
                })
            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"自动扫描任务异常: {e}")
            await asyncio.sleep(10)


async def arb_monitor_task():
    """套利背离监控:每 ARB_MONITOR_INTERVAL_SECONDS 秒一轮,新告警经 WS 广播。"""
    while True:
        try:
            alerts = await asyncio.to_thread(run_arb_tick)
            if alerts:
                await manager.broadcast({
                    "type": "arb_alerts",
                    "data": alerts,
                    "time": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
                })
            await asyncio.sleep(ARB_MONITOR_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"套利监控任务异常: {e}")
            await asyncio.sleep(10)


async def auto_download_task():
    """每个交易日定时自动下载K线数据"""
    last_attempt_at: datetime | None = None
    last_auto_start_date = ""
    first_check = True
    while True:
        try:
            if first_check:
                first_check = False
            else:
                next_check_at = now_beijing() + timedelta(seconds=AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS)
                set_auto_download_schedule_status(
                    check_interval_seconds=AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS,
                    next_check_at=next_check_at.strftime("%Y-%m-%d %H:%M:%S"),
                )
                await asyncio.sleep(AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS)
            settings = await asyncio.to_thread(db.get_scan_settings)
            # 15点下载窗口/交易日判断锚定北京时间,避免服务器时区非 Asia/Shanghai
            # 时整天错过下载窗口(本地时钟只用于与 last_attempt_at 做时间差)
            now = now_beijing()
            today_str = now.strftime("%Y-%m-%d")
            target_hour = _normalize_auto_download_hour(settings.get("auto_download_hour", AUTO_DOWNLOAD_START_HOUR))
            # today_done 是"当天自动下载已成功完成"的事实标志,不能每轮例行检查
            # 都清零:15:11 下载完成放行收盘扫描后,15:2x 的下一轮检查会把它翻回
            # False,收盘挂起闸门随之整晚误报"尚未下载完成"(开关也点不开)。
            # 这里保留同一天已完成的标志;跨天/重启后自然归位,由下面的 coverage
            # 检查或重新下载兜底。
            done_today = is_auto_download_done_today(today_str)
            set_auto_download_schedule_status(
                enabled=bool(settings.get("auto_download_enabled")),
                hour=target_hour,
                check_interval_seconds=AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS,
                last_checked_at=now.strftime("%Y-%m-%d %H:%M:%S"),
                next_check_at=(now + timedelta(seconds=AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS)).strftime("%Y-%m-%d %H:%M:%S"),
                today=today_str,
                today_started=(last_auto_start_date == today_str),
                today_done=done_today,
                status="completed" if done_today else "checking",
            )

            # 检查是否是交易日
            is_trading = await asyncio.to_thread(akshare_data.is_trading_date, today_str)
            if not is_trading:
                set_auto_download_schedule_status(status="not_trading_day")
                continue

            # 检查是否到达设定的下载时间
            if now.hour < target_hour:
                set_auto_download_schedule_status(status="before_window")
                continue

            if not settings.get("auto_download_enabled"):
                logger.info("15:00自动下载未开启跳过")
                set_auto_download_schedule_status(status="disabled")
                continue

            # 当天已成功完成过自动下载:保持完成态,不再整点重跑。
            # coverage 对停牌股永远到不了 100%(放宽后也有零星掉队),若无此
            # 护栏,每个整点的全量重跑都会把收盘挂起文案再刷回来一遍。
            if done_today:
                set_auto_download_schedule_status(status="completed", today_done=True)
                continue

            coverage = await asyncio.to_thread(_get_daily_kline_update_coverage, today_str)
            if coverage.get("updated"):
                logger.info(
                    "15:00自动下载跳过：%s 日线已更新完成 %s/%s",
                    today_str,
                    coverage.get("updated_count", 0),
                    coverage.get("total_count", 0),
                )
                set_auto_download_schedule_status(status="already_updated", today_done=True)
                continue

            if last_attempt_at and now - last_attempt_at < timedelta(seconds=AUTO_DOWNLOAD_RETRY_INTERVAL_SECONDS):
                set_auto_download_schedule_status(status="retry_wait")
                continue

            # 检查是否已有下载任务在运行
            dl_status = await asyncio.to_thread(get_history_download_status)
            if dl_status.get("running"):
                set_auto_download_schedule_status(status="download_running")
                continue

            append_history_log(
                "15:00自动下载开始：%s %s，当前日线覆盖 %s/%s，强制覆盖=%s"
                % (
                    today_str,
                    now.strftime("%H:%M:%S"),
                    coverage.get("updated_count", 0),
                    coverage.get("total_count", 0),
                    "是" if settings.get("kline_force_refresh") else "否",
                )
            )
            logger.info(
                "15:00自动下载开始：%s %s，当前日线覆盖 %s/%s，强制覆盖=%s",
                today_str,
                now.strftime("%H:%M:%S"),
                coverage.get("updated_count", 0),
                coverage.get("total_count", 0),
                "是" if settings.get("kline_force_refresh") else "否",
            )
            last_attempt_at = now
            last_auto_start_date = today_str
            set_auto_download_schedule_status(status="started", today_started=True)
            scan_period = normalize_scan_period(settings.get("scan_period"))
            download_periods = list(dict.fromkeys(["daily", scan_period]))
            await asyncio.to_thread(
                start_history_download,
                periods=download_periods,
                force_refresh=bool(settings.get("kline_force_refresh")),
                source="auto",
            )
        except Exception as e:
            logger.error(f"自动下载任务异常: {e}")
            set_auto_download_schedule_status(status="error")
            await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event():
    ensure_runtime_db_ready()
    try:
        settings = await asyncio.to_thread(db.get_scan_settings)
        set_auto_download_schedule_status(
            enabled=bool(settings.get("auto_download_enabled")),
            hour=_normalize_auto_download_hour(settings.get("auto_download_hour", AUTO_DOWNLOAD_START_HOUR)),
            check_interval_seconds=AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS,
            next_check_at=(now_beijing() + timedelta(seconds=AUTO_DOWNLOAD_CHECK_INTERVAL_SECONDS)).strftime("%Y-%m-%d %H:%M:%S"),
            status="waiting",
        )
    except Exception:
        logger.exception("初始化自动下载状态失败")
    asyncio.create_task(realtime_push_task())
    asyncio.create_task(auto_scan_task())
    asyncio.create_task(arb_monitor_task())
    asyncio.create_task(auto_download_task())
    asyncio.create_task(asyncio.to_thread(pytdx_data.reconnect))
    asyncio.create_task(pi_node_health_task())
    logger.info("证券辅助决策终端启动")


@app.on_event("shutdown")
async def shutdown_event():
    pytdx_data.disconnect()
    logger.info("证券辅助决策终端关闭")


@app.get("/")
async def root():
    return {"name": "证券辅助决策终端", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health_check():
    try:
        stock_pool_count = await asyncio.to_thread(db.count_stock_pool)
    except Exception as exc:
        logger.warning("Health check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {
        "status": "ok",
        "time": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
        "stock_pool_count": stock_pool_count,
    }


@app.get("/api/health")
async def api_health_check():
    return await health_check()


def _resolve_frontend_entry() -> Path | None:
    index_file = FRONTEND_DIST_DIR / "index.html"
    return index_file if index_file.exists() else None


def _serve_frontend_file(relative_path: str = ""):
    index_file = _resolve_frontend_entry()
    if index_file is None:
        raise HTTPException(status_code=404, detail="frontend build not found")

    requested = (FRONTEND_DIST_DIR / relative_path).resolve()
    dist_root = FRONTEND_DIST_DIR.resolve()
    if not str(requested).startswith(str(dist_root)):
        raise HTTPException(status_code=404, detail="invalid path")

    if requested.is_file():
        media_type, _ = mimetypes.guess_type(str(requested))
        return FileResponse(requested, media_type=media_type)

    return FileResponse(index_file, media_type="text/html")


@app.get("/TrendZen")
async def trendzen_root_redirect():
    return _serve_frontend_file("index.html")


@app.get("/TrendZen/")
async def trendzen_root():
    return _serve_frontend_file("index.html")


@app.get("/TrendZen/{full_path:path}")
async def trendzen_assets(full_path: str):
    return _serve_frontend_file(full_path)

