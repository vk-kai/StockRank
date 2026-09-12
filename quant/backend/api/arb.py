# -*- coding: utf-8 -*-
"""套利背离监控 REST 接口(鉴权/Query-POST 惯用法与 api/market.py 一致)。

- GET  /api/market/benchmark/trends   分时叠加图数据(短缓存)
- GET  /api/market/benchmark/search   板块基准关键词解析
- GET  /api/market/arb/status         设置 + 运行态 + 每对快照 + 近期告警
- POST /api/market/arb/pairs          action=add|remove|toggle
- POST /api/market/arb/settings       总开关
- POST /api/market/arb/read           告警标已读
- GET  /api/market/arb/feed           免鉴权:给 StockRank 拉走的未投递告警(拉取即打 delivered)
- POST /api/market/arb/feed/ack       免鉴权:StockRank 展示+微信推送成功后回执 → TrendZen 侧变已读
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from cachetools import TTLCache

from backend import auth_service, db
from backend.arb import engine
from backend.config import ARB_MAX_PAIRS
from backend.market import benchmark_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["arb"])

_bench_trends_cache: TTLCache = TTLCache(maxsize=64, ttl=6)

_BENCH_CODE_PATTERNS = {
    "em_index": re.compile(r"^\d{6}$"),
    "em_board": re.compile(r"^BK\d{4,6}$"),
    "em_global": re.compile(r"^[A-Z0-9]{2,10}$"),
    "tdx_board": re.compile(r"^88\d{4}$"),
}


def _bench_code_valid(kind: str, code: str) -> bool:
    pattern = _BENCH_CODE_PATTERNS.get(kind)
    return bool(pattern and pattern.match(str(code or "").strip().upper()))


@router.get("/benchmark/trends")
def benchmark_trends(
    kind: str = Query(..., description="基准类型: em_index|em_board|em_global|tdx_board"),
    code: str = Query(..., description="基准代码"),
    label: str = Query("", description="板块名称(em_board 兜底找880孪生码用)"),
):
    key = f"{kind}|{code}|{label}"
    cached = _bench_trends_cache.get(key)
    if cached is not None:
        return {"success": True, "data": cached}
    payload = benchmark_data.get_benchmark_trends(kind, code, label=label or None)
    if not payload:
        return {"success": False, "message": "基准分时数据暂不可用"}
    _bench_trends_cache[key] = payload
    return {"success": True, "data": payload}


@router.get("/benchmark/search")
def benchmark_search(keyword: str = Query(..., min_length=1, description="板块名称关键词")):
    try:
        items = benchmark_data.resolve_board_code(keyword)
    except Exception as exc:
        logger.warning("板块基准搜索异常 %s: %s", keyword, exc)
        items = []
    return {"success": True, "data": items}


@router.get("/arb/status")
def arb_status():
    settings = db.get_arb_settings()
    alerts = db.list_arb_alerts(limit=50)
    return {
        "success": True,
        "data": {
            "settings": settings,
            "runtime": engine.get_runtime_status(),
            "alerts": alerts,
        },
    }


# 与 App.tsx DIRECTION_LABELS 一致的中文方向名,推给微信直接可用
_FEED_DIRECTION_LABELS = {
    "buy": "滞涨买点",
    "sell": "抗跌卖点",
    "preopen_buy": "盘前偏多",
    "preopen_sell": "盘前偏空",
}


@router.get("/arb/feed")
def arb_feed(limit: int = Query(50, ge=1, le=100)):
    """给 StockRank 异动预警用的免鉴权投递口:返回尚未拉取过的告警,拉取即打 delivered 标记。

    - delivered 防"重复拉取→重复推微信";is_read 由 /arb/feed/ack 在下游
      展示+微信推送成功后回执,两标记独立(ack 丢失只影响本侧已读态,不会重推);
    - 返回按 id 升序(先产生的先推),direction_label 已翻成中文。
    """
    alerts = db.list_undelivered_arb_alerts(limit=limit)
    if alerts:
        db.mark_arb_alerts_delivered([item["id"] for item in alerts])
    for item in alerts:
        item["direction_label"] = _FEED_DIRECTION_LABELS.get(str(item.get("direction")), str(item.get("direction")))
    return {"success": True, "data": alerts, "count": len(alerts)}


@router.post("/arb/feed/ack")
def arb_feed_ack(ids: str = Query(..., description="逗号分隔的告警ID")):
    """StockRank 侧闭环回执(已展示且微信推送成功):对应告警在 TrendZen 变已读。免鉴权。"""
    id_list: list[int] = []
    for part in str(ids or "").split(","):
        part = part.strip()
        if part.isdigit():
            id_list.append(int(part))
    if not id_list:
        raise HTTPException(status_code=400, detail="缺少有效的 ids")
    updated = db.mark_arb_alerts_read(id_list)
    return {"success": True, "data": {"updated": int(updated)}}


@router.post("/arb/pairs")
def arb_pairs_action(
    request: Request,
    action: str = Query(..., description="add|remove|toggle"),
    pair_id: Optional[int] = Query(None, description="remove/toggle 用的配对ID"),
    stock_code: str = Query("", description="add: A股个股代码"),
    stock_name: str = Query("", description="add: 个股名称"),
    bench_kind: str = Query("", description="add: em_index|em_board|em_global|tdx_board"),
    bench_code: str = Query("", description="add: 基准代码"),
    bench_label: str = Query("", description="add: 基准显示名"),
    preopen_enabled: bool = Query(True, description="add: 是否启用盘前KOSPI提示"),
    enabled: Optional[bool] = Query(None, description="toggle: 目标状态"),
):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能配置套利监控，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    owner = auth_service.get_visible_owner_username(user)

    if action == "add":
        code = str(stock_code or "").strip()
        if not re.match(r"^\d{6}$", code):
            raise HTTPException(status_code=400, detail="个股代码必须是6位数字")
        kind = str(bench_kind or "").strip()
        bench = str(bench_code or "").strip().upper()
        if kind not in benchmark_data.BENCH_KINDS:
            raise HTTPException(status_code=400, detail=f"基准类型必须是 {','.join(benchmark_data.BENCH_KINDS)}")
        if not _bench_code_valid(kind, bench):
            raise HTTPException(status_code=400, detail=f"基准代码格式不符合类型 {kind}")
        if db.count_arb_pairs(owner) >= ARB_MAX_PAIRS:
            raise HTTPException(status_code=400, detail=f"每个用户最多 {ARB_MAX_PAIRS} 对监控")
        pair = db.add_arb_pair(
            stock_code=code,
            stock_name=str(stock_name or code).strip(),
            bench_kind=kind,
            bench_code=bench,
            bench_label=str(bench_label or bench).strip(),
            owner_username=owner,
            preopen_enabled=preopen_enabled,
        )
        return {"success": True, "data": pair, "existed": bool(pair.get("existed"))}

    if action in ("remove", "toggle"):
        if not pair_id:
            raise HTTPException(status_code=400, detail="缺少 pair_id")
        if action == "remove":
            ok = db.remove_arb_pair(int(pair_id), owner)
            engine.runtime["pairs"].pop(int(pair_id), None)
        else:
            if enabled is None:
                raise HTTPException(status_code=400, detail="toggle 需要 enabled 参数")
            ok = db.set_arb_pair_enabled(int(pair_id), bool(enabled), owner)
        if not ok:
            raise HTTPException(status_code=404, detail="配对不存在或无权操作")
        return {"success": True, "data": {"pair_id": int(pair_id)}}

    raise HTTPException(status_code=400, detail="action 必须是 add|remove|toggle")


@router.post("/arb/settings")
def arb_settings_action(
    request: Request,
    enabled: bool = Query(..., description="监控总开关"),
):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能修改套利监控设置，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    data = db.update_arb_settings(enabled=bool(enabled))
    return {"success": True, "data": data}


@router.post("/arb/read")
def arb_alerts_read(
    request: Request,
    ids: str = Query("", description="逗号分隔的告警ID;all=全部已读"),
):
    user = auth_service.get_current_user_from_request(request)
    owner = auth_service.get_visible_owner_username(user)
    if str(ids).strip().lower() == "all":
        targets = [int(item["id"]) for item in db.list_arb_alerts(limit=200, owner_username=owner)]
    else:
        targets = [int(item) for item in str(ids).split(",") if item.strip().isdigit()]
    if not targets:
        return {"success": True, "data": {"updated": 0}}
    updated = db.mark_arb_alerts_read(targets, owner)
    return {"success": True, "data": {"updated": updated}}
