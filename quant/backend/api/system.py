from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from backend.node_state import get_node_status_snapshot, reset_node_state
from backend.config import set_pi_node_enabled
from backend.system_utils import get_system_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/stats")
async def system_stats():
    """实时系统资源占用（CPU / 内存 / GPU），跨平台 Win/Linux。
    供前端右下角监控组件轮询。采集可能涉及子进程（nvidia-smi），放到线程池避免阻塞事件循环。"""
    try:
        data = await asyncio.to_thread(get_system_stats)
    except Exception as exc:
        logger.warning("采集系统资源占用失败: %s", exc)
        return {"success": False, "message": str(exc), "data": None}
    return {"success": True, "data": data}


@router.get("/node-status")
async def node_status():
    """树莓派边缘节点状态（online/offline/cooldown/disabled），供导航栏徽章轮询。

    状态由后台 ``pi_node_health_task`` 周期性刷新，这里只读快照，无网络往返。
    公开端点（与 /stats、/health 一致），未登录也能在导航栏展示。
    """
    try:
        data = await asyncio.to_thread(get_node_status_snapshot)
    except Exception as exc:
        logger.warning("读取节点状态失败: %s", exc)
        return {"success": False, "message": str(exc), "data": None}
    return {"success": True, "data": data}


class NodeToggleReq(BaseModel):
    enabled: bool


@router.post("/node-toggle")
async def node_toggle(req: NodeToggleReq):
    """运行时开启/关闭 Pi 节点卸载，持久化到 .env。"""
    set_pi_node_enabled(req.enabled)
    if not req.enabled:
        reset_node_state()
    logger.info("Pi 节点卸载已%s", "开启" if req.enabled else "关闭")
    return {"success": True, "data": {"enabled": req.enabled}}
