"""TrendZen 边缘节点 FastAPI worker（跑在树莓派上）。

端点契约（与服务器端 ``backend/backtest/remote.py`` 对应）：

- ``GET /health``                          → 握手 + 版本上报，供服务器健康探测。
- ``POST /run/backtest``                   → 单股回测（df 以 parquet+base64 下发）。
- ``POST /run/backtest-batch``             → 全量分块批量回测（一次一批 candidate）。

worker 只负责"解码 df → 跑 run_backtest"，不取数、不碰 DB。
批量结果 item 采用最小 shape（code/name + run_backtest 结果字段），
bar_count/period/range_start/range_end 由服务器用自己持有的 df 补齐，保证与本地路径一致。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import pickle
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional

import pandas as pd
import psutil
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from backend.backtest.engine import run_backtest
from backend.backtest.strategies import BACKTEST_STRATEGY_MAP

# 预热 cpu_percent 基线，使首次 /health 即可返回非 0 负载
psutil.cpu_percent(interval=None)
psutil.virtual_memory()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("edge_node")

_TOKEN = os.getenv("PI_NODE_TOKEN", "")
_WORKERS = max(int(os.getenv("EDGE_NODE_WORKERS", "0") or 0), 1) or max(
    (os.cpu_count() or 2) - 1, 1
)
_BPOOL = ProcessPoolExecutor(max_workers=_WORKERS)

# 运行中任务计数（线程安全），供 /health 上报当前负载
_active_tasks = 0
_active_tasks_lock = asyncio.Lock()

app = FastAPI(title="TrendZen Edge Node")


# --------------------------------------------------------------------------- #
# 共享核心：解码 df → 跑 run_backtest（单股 / 批量都用它）
# --------------------------------------------------------------------------- #
def _b64_to_df(df_b64: str) -> pd.DataFrame:
    """pickle+zlib+base64 解码（与服务器 remote.df_to_b64 对应，dtype 完全保真）。"""
    if not df_b64:
        return pd.DataFrame()
    return pickle.loads(zlib.decompress(base64.b64decode(df_b64)))


def run_on_df_b64(
    df_b64: str,
    *,
    strategy_name: str,
    cash: float,
    commission: float = 0.0001,
    lightweight: bool = False,
    include_equity_curve: bool = False,
    period: str = "daily",
) -> dict:
    """返回 run_backtest 的结果 dict（success 或 业务失败都算）。"""
    try:
        df = _b64_to_df(df_b64)
    except Exception as exc:
        return {"success": False, "message": f"df 解码失败: {exc}"}
    if df is None or df.empty:
        return {"success": False, "message": "选定区间内暂无可用数据"}
    return run_backtest(
        df,
        strategy_name=strategy_name,
        cash=float(cash),
        commission=float(commission),
        progress_callback=None,
        lightweight=bool(lightweight),
        include_equity_curve=bool(include_equity_curve),
        period=str(period or "daily"),
    )


# --------------------------------------------------------------------------- #
# ProcessPool 子进程入口（必须为模块级函数以可 pickle）
# --------------------------------------------------------------------------- #
def _single_task(payload: dict) -> dict:
    return run_on_df_b64(
        payload.get("df_b64", ""),
        strategy_name=payload["strategy"],
        cash=payload["cash"],
        commission=payload.get("commission", 0.0001),
        lightweight=payload.get("lightweight", False),
        include_equity_curve=payload.get("include_equity_curve", False),
        period=payload.get("period", "daily"),
    )


def _batch_task(task: dict, common: dict) -> dict:
    """返回结构与服务器 _run_full_backtest_worker 对齐（item 用最小 shape）。"""
    code = str(task.get("code", "")).zfill(6)
    name = str(task.get("name", "") or code)
    index = int(task.get("index", 0))
    result = run_on_df_b64(
        task.get("df_b64", ""),
        strategy_name=common["strategy"],
        cash=common["cash"],
        commission=common.get("commission", 0.0001),
        lightweight=common.get("lightweight", True),
        include_equity_curve=common.get("include_equity_curve", False),
        period=common.get("period", "daily"),
    )
    if not result.get("success"):
        return {
            "ok": False,
            "index": index,
            "code": code,
            "name": name,
            "message": result.get("message", "回测失败"),
        }
    return {
        "ok": True,
        "index": index,
        "code": code,
        "name": name,
        "item": {"code": code, "name": name, **result},
    }


def _run_batch_sync(tasks: list[dict], common: dict) -> list[dict]:
    results: list[dict] = []
    future_map = {_BPOOL.submit(_batch_task, t, common): t.get("index") for t in tasks}
    for future in as_completed(future_map):
        index = future_map[future]
        try:
            results.append(future.result())
        except Exception as exc:  # pragma: no cover - 子进程崩溃兜底
            results.append(
                {"ok": False, "index": index, "code": "", "name": "", "message": f"Pi worker 崩溃: {exc}"}
            )
    return results


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #
class SingleReq(BaseModel):
    strategy: str
    cash: float
    commission: float = 0.0001
    lightweight: bool = False
    include_equity_curve: bool = False
    period: str = "daily"
    df_b64: str


class BatchTask(BaseModel):
    index: int
    code: str
    name: str = ""
    df_b64: str


class BatchReq(BaseModel):
    strategy: str
    cash: float
    commission: float = 0.0001
    lightweight: bool = True
    include_equity_curve: bool = False
    period: str = "daily"
    tasks: list[BatchTask]


def _auth(x_node_token: Optional[str]) -> None:
    if _TOKEN and x_node_token != _TOKEN:
        raise HTTPException(status_code=401, detail="invalid node token")


# --------------------------------------------------------------------------- #
# 端点
# --------------------------------------------------------------------------- #
@app.get("/health")
async def health():
    """健康探测 + 版本上报 + 节点负载；服务器据此校验版本并把负载透传给前端。"""
    try:
        import backtrader

        bt_version = str(getattr(backtrader, "__version__", "") or "")
    except Exception:
        bt_version = ""

    try:
        vm = psutil.virtual_memory()
        load = {
            "cpu_percent": round(float(psutil.cpu_percent(interval=None)), 1),
            "cpu_count": int(psutil.cpu_count(logical=True) or 0),
            "memory_percent": round(float(vm.percent), 1),
            "memory_total_bytes": int(vm.total),
            "memory_used_bytes": int(vm.used),
        }
    except Exception:
        load = {}

    return {
        "status": "ok",
        "node": "trendzen-edge",
        "workers": _WORKERS,
        "active_tasks": _active_tasks,
        "python": ".".join(map(str, sys.version_info[:3])),
        "backtrader": bt_version,
        "strategies": sorted(BACKTEST_STRATEGY_MAP.keys()),
        "load": load,
    }


@app.post("/run/backtest")
async def run_single(req: SingleReq, x_node_token: Optional[str] = Header(None)):
    global _active_tasks
    _auth(x_node_token)
    async with _active_tasks_lock:
        _active_tasks += 1
    try:
        result = await asyncio.to_thread(_single_task, req.model_dump())
    finally:
        async with _active_tasks_lock:
            _active_tasks = max(0, _active_tasks - 1)
    if result.get("success"):
        return {"success": True, "result": result}
    return {"success": False, "message": result.get("message", "远端回测失败")}


@app.post("/run/backtest-batch")
async def run_batch(req: BatchReq, x_node_token: Optional[str] = Header(None)):
    global _active_tasks
    _auth(x_node_token)
    common = {
        "strategy": req.strategy,
        "cash": req.cash,
        "commission": req.commission,
        "lightweight": req.lightweight,
        "include_equity_curve": req.include_equity_curve,
        "period": req.period,
    }
    tasks = [t.model_dump() for t in req.tasks]
    async with _active_tasks_lock:
        _active_tasks += len(tasks)
    try:
        results = await asyncio.to_thread(_run_batch_sync, tasks, common)
    finally:
        async with _active_tasks_lock:
            _active_tasks = max(0, _active_tasks - len(tasks))
    return {"results": results}
