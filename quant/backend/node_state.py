"""树莓派边缘节点健康状态与探测。

仿照 pytdx 的双层探活（``_probe_server``，短超时 + 真实业务样本）与
akshare 的时间戳阻塞门（``_retry_blocked_until``）：节点失败后短暂冷却，
冷却期内直接视为不可用，避免每个回测任务都去撞一次挂掉的隧道。

状态由后台协程 ``pi_node_health_task`` 周期性刷新（挂在 FastAPI startup，
见 ``main.py``），``runtime`` / API 通过 ``is_node_available`` /
``get_node_status_snapshot`` 读取，避免在回测热路径里发 HTTP。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime

from backend.time_utils import now_beijing
from typing import Optional

import requests

from backend.config import (
    PI_NODE_COOLDOWN,
    PI_NODE_ENABLED,
    PI_NODE_HEALTH_INTERVAL,
    PI_NODE_PROBE_TIMEOUT,
    PI_NODE_TOKEN,
    PI_NODE_URL,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_node_state: dict = {
    "enabled": False,
    "online": False,
    "state": "offline",          # online | offline | cooldown | disabled
    "last_seen": "",
    "last_seen_ts": 0.0,
    "latency_ms": None,
    "cooldown_until_ts": 0.0,
    "last_error": "",
    "url": "",
    "workers": None,
    "node_backtrader": "",
    "version_match": True,
    "load": {},
    "active_tasks": 0,
}

_LOCAL_BT_VERSION: Optional[str] = None


def _local_backtrader_version() -> str:
    """惰性读取本机 backtrader 版本，用于和节点上报版本比对。"""
    global _LOCAL_BT_VERSION
    if _LOCAL_BT_VERSION is None:
        try:
            import backtrader  # noqa: WPS433（惰性 import，避免模块加载期开销）

            _LOCAL_BT_VERSION = str(getattr(backtrader, "__version__", "") or "")
        except Exception as exc:  # pragma: no cover - 依赖理应存在
            logger.warning("读取本机 backtrader 版本失败: %s", exc)
            _LOCAL_BT_VERSION = ""
    return _LOCAL_BT_VERSION


def _now_ts() -> float:
    return time.time()


def _now_text() -> str:
    return now_beijing().strftime("%Y-%m-%d %H:%M:%S")


def _in_cooldown_locked() -> bool:
    return _now_ts() < _node_state["cooldown_until_ts"]


def is_node_available() -> bool:
    """回测派发前调用：节点是否可用来卸载。"""
    if not PI_NODE_ENABLED:
        return False
    with _lock:
        if not _node_state["online"]:
            return False
        return not _in_cooldown_locked()


def mark_node_success(latency_ms: Optional[float] = None) -> None:
    with _lock:
        _node_state.update(
            online=True,
            state="online",
            last_seen=_now_text(),
            last_seen_ts=_now_ts(),
            cooldown_until_ts=0.0,
            last_error="",
            enabled=True,
            url=PI_NODE_URL,
        )
        if latency_ms is not None:
            _node_state["latency_ms"] = round(float(latency_ms), 1)


def mark_node_failure(reason: str) -> None:
    """传输失败/超时/健康检测失败：进入冷却。"""
    with _lock:
        _node_state.update(
            online=False,
            state="cooldown",
            last_error=str(reason),
            cooldown_until_ts=_now_ts() + max(0, PI_NODE_COOLDOWN),
            latency_ms=None,
        )


def reset_node_state() -> None:
    """节点禁用时重置状态，让前端立即反映。"""
    with _lock:
        _node_state.update(
            online=False,
            state="offline",
            cooldown_until_ts=0.0,
            latency_ms=None,
            last_error="",
        )


def _record_probe_body(body: dict, latency_ms: float) -> None:
    """握手成功后记录节点上报的元信息（workers / 版本 / 活跃任务），并做版本一致性校验。"""
    node_bt = str(body.get("backtrader", "") or "")
    local_bt = _local_backtrader_version()
    version_match = bool(node_bt) and (not local_bt or node_bt == local_bt)
    with _lock:
        _node_state["workers"] = body.get("workers")
        _node_state["node_backtrader"] = node_bt
        _node_state["version_match"] = version_match
        _node_state["load"] = body.get("load") or {}
        _node_state["active_tasks"] = body.get("active_tasks", 0)
    mark_node_success(latency_ms)
    if not version_match:
        logger.warning(
            "Pi 节点 backtrader 版本与本机不一致（节点=%s 本机=%s），结果可能漂移",
            node_bt or "?",
            local_bt or "?",
        )


def _probe_once() -> None:
    headers = {"X-Node-Token": PI_NODE_TOKEN} if PI_NODE_TOKEN else {}
    start = time.perf_counter()
    try:
        resp = requests.get(
            f"{PI_NODE_URL}/health",
            headers=headers,
            timeout=PI_NODE_PROBE_TIMEOUT,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        if resp.status_code != 200:
            mark_node_failure(f"health HTTP {resp.status_code}")
            return
        body = resp.json() or {}
        if body.get("status") != "ok":
            mark_node_failure(f"health 状态异常: {body.get('status')}")
            return
        _record_probe_body(body, latency_ms)
    except Exception as exc:
        mark_node_failure(str(exc))


def get_node_status_snapshot() -> dict:
    """供 ``/api/system/node-status`` 返回；state 已归一为四态。"""
    with _lock:
        remaining = max(0.0, _node_state["cooldown_until_ts"] - _now_ts())
        if not PI_NODE_ENABLED:
            state = "disabled"
        elif remaining > 0:
            state = "cooldown"
        elif _node_state["online"]:
            state = "online"
        else:
            state = "offline"
        return {
            "enabled": bool(PI_NODE_ENABLED),
            "online": bool(_node_state["online"]),
            "state": state,
            "latency_ms": _node_state["latency_ms"],
            "last_seen": _node_state["last_seen"],
            "last_error": _node_state["last_error"],
            "url": PI_NODE_URL,
            "workers": _node_state["workers"],
            "node_backtrader": _node_state["node_backtrader"],
            "version_match": _node_state["version_match"],
            "load": _node_state["load"],
            "active_tasks": _node_state.get("active_tasks", 0),
            "cooldown_remaining_seconds": round(remaining, 0),
        }


async def pi_node_health_task() -> None:
    """后台健康检测协程，仿 ``auto_scan_task``（main.py）。同步探测用 to_thread 包裹。"""
    if not PI_NODE_ENABLED:
        logger.info("Pi 节点卸载未启用（PI_NODE_ENABLED=false），跳过健康检测")
        return
    # 启动时立即探一次，让前端尽快拿到真实状态
    while True:
        try:
            await asyncio.to_thread(_probe_once)
        except Exception as exc:  # pragma: no cover - to_thread 内部已捕获
            logger.error("Pi 节点健康检测异常: %s", exc)
        await asyncio.sleep(max(1, PI_NODE_HEALTH_INTERVAL))
