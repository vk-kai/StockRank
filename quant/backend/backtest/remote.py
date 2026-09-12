"""Pi 边缘节点卸载的传输与序列化层（不含业务聚合）。

职责：
- DataFrame <-> parquet(base64) 编解码；
- 向 Pi worker 发 HTTP（单股 / 批量），成功/失败上报节点状态（``node_state``）；
- 返回值约定：
  * ``None``  → 节点不可用 / 传输失败 / 超时 / df 过大，**调用方应回落本机**；
  * ``dict``  → 节点真正跑了 ``run_backtest``（成功或业务失败都算），按结果处理，**不回落**。

批量端点的结果列表与 ``runtime._run_full_backtest_worker`` 的返回结构严格对齐，
使得 ``runtime`` 的聚合逻辑（``as_completed`` 那段）可被原样复用。
"""
from __future__ import annotations

import base64
import logging
import pickle
import zlib
from typing import Optional

import pandas as pd
import requests

from backend.config import (
    PI_NODE_BATCH_TIMEOUT,
    PI_NODE_ENABLED,
    PI_NODE_MAX_DF_KB,
    PI_NODE_OFFLOAD_MODE,
    PI_NODE_SINGLE_TIMEOUT,
    PI_NODE_TOKEN,
    PI_NODE_URL,
)
from backend.node_state import is_node_available, mark_node_failure, mark_node_success

logger = logging.getLogger(__name__)


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if PI_NODE_TOKEN:
        headers["X-Node-Token"] = PI_NODE_TOKEN
    return headers


def df_to_b64(df: Optional[pd.DataFrame]) -> str:
    """DataFrame -> pickle(protocol=4) -> zlib -> base64。

    用 pickle 而非 parquet：dtype 完全保真；且与 ProcessPoolExecutor 内部把 df 送进
    子进程用的是同一套序列化，保证 Pi 路径与本地回落路径数据口径一致。
    信任前提：df 为服务器自身生成，经 SSH 加密隧道发给受信 Pi，反序列化安全。
    """
    if df is None or df.empty:
        return ""
    blob = pickle.dumps(df, protocol=4)
    return base64.b64encode(zlib.compress(blob, level=6)).decode("ascii")


def b64_to_df(b64: str) -> pd.DataFrame:
    if not b64:
        return pd.DataFrame()
    return pickle.loads(zlib.decompress(base64.b64decode(b64)))


def _b64_size_kb(b64: str) -> int:
    return (len(b64) or 0) // 1024


def offload_enabled_for(target: str) -> bool:
    """target: 'single' | 'full'。按 PI_NODE_ENABLED + 模式 + 节点可用性 综合判断。"""
    if not PI_NODE_ENABLED or not is_node_available():
        return False
    mode = (PI_NODE_OFFLOAD_MODE or "both").strip().lower()
    if mode == "both":
        return True
    if mode == "single_only":
        return target == "single"
    if mode == "full_only":
        return target == "full"
    return True


def run_single_on_node(
    df: pd.DataFrame,
    *,
    strategy_name: str,
    cash: float,
    commission: float = 0.0001,
    lightweight: bool = False,
    include_equity_curve: bool = False,
    period: str = "daily",
) -> Optional[dict]:
    """单股回测卸载。返回 None 表示应回落本机；返回 dict 表示节点已执行。"""
    if not offload_enabled_for("single"):
        return None
    df_b64 = df_to_b64(df)
    if not df_b64:
        return None  # 空数据，交给本机路径按原逻辑报错
    if _b64_size_kb(df_b64) > PI_NODE_MAX_DF_KB:
        logger.info("单股 df 过大（%dKB > %dKB），回落本机", _b64_size_kb(df_b64), PI_NODE_MAX_DF_KB)
        return None
    payload = {
        "strategy": strategy_name,
        "cash": cash,
        "commission": commission,
        "lightweight": lightweight,
        "include_equity_curve": include_equity_curve,
        "period": period,
        "df_b64": df_b64,
    }
    try:
        resp = requests.post(
            f"{PI_NODE_URL}/run/backtest",
            json=payload,
            headers=_headers(),
            timeout=PI_NODE_SINGLE_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json() or {}
    except Exception as exc:
        logger.warning("Pi 单股卸载失败，回落本机: %s", exc)
        mark_node_failure(str(exc))
        return None

    mark_node_success()
    if body.get("success"):
        return body.get("result") or {"success": False, "message": "节点返回空结果"}
    return {"success": False, "message": body.get("message", "远端回测失败")}


def run_batch_on_node(
    tasks_with_df: list[dict],
    *,
    strategy: str,
    cash: float,
    commission: float = 0.0001,
    lightweight: bool = True,
    include_equity_curve: bool = False,
    period: str = "daily",
) -> Optional[list[dict]]:
    """全量分块批量卸载。

    ``tasks_with_df[i]`` = {"index","code","name","df"}。
    返回结果列表（按 index 对齐，顺序可乱）或 None（整 chunk 回落本机）。
    任一 df 超过 PI_NODE_MAX_DF_KB 则整 chunk 回落（保守，保证一致性）。
    """
    if not tasks_with_df or not offload_enabled_for("full"):
        return None

    serialized = []
    for task in tasks_with_df:
        b64 = df_to_b64(task.get("df"))
        if _b64_size_kb(b64) > PI_NODE_MAX_DF_KB:
            logger.info(
                "批量 chunk 内 %s df 过大（%dKB），整 chunk 回落本机",
                task.get("code"),
                _b64_size_kb(b64),
            )
            return None
        serialized.append(
            {
                "index": int(task["index"]),
                "code": str(task.get("code", "")).zfill(6),
                "name": str(task.get("name", "") or task.get("code", "")),
                "df_b64": b64,
            }
        )

    payload = {
        "strategy": strategy,
        "cash": cash,
        "commission": commission,
        "lightweight": lightweight,
        "include_equity_curve": include_equity_curve,
        "period": period,
        "tasks": serialized,
    }
    try:
        resp = requests.post(
            f"{PI_NODE_URL}/run/backtest-batch",
            json=payload,
            headers=_headers(),
            timeout=PI_NODE_BATCH_TIMEOUT,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results", [])
    except Exception as exc:
        logger.warning("Pi 批量卸载失败，整 chunk 回落本机: %s", exc)
        mark_node_failure(str(exc))
        return None

    mark_node_success()
    return results if isinstance(results, list) else None
