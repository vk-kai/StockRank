from fastapi import APIRouter, HTTPException, Query, Request
import logging

from backend import auth_service
from backend import db
from backend.backtest.runtime import (
    build_full_backtest_stock_detail,
    get_backtest_status,
    start_backtest_job,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["backtest"])

@router.post("/start")
async def start_backtest_api(
    request: Request,
    code: str = Query(..., description="证券代码"),
    name: str = Query("", description="证券名称提示"),
    strategy: str = Query("MA_BULL_PULLBACK_BOLL", description="策略名称"),
    start_date: str = Query("20240101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("", description="结束日期 YYYYMMDD"),
    cash: float = Query(100000.0, description="初始资金"),
    period: str = Query("daily", description="K线周期"),
    mode: str = Query("single", description="回测模式 single/full"),
):
    try:
        user = auth_service.get_current_user_from_request(request)
        try:
            auth_service.require_operable_user(user, "临时账号不能运行回测，请先开通 VIP 后再操作")
        except auth_service.StrategyAccessDenied as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        access = auth_service.get_strategy_access(strategy, user)
        if not access["allowed"]:
            raise HTTPException(status_code=int(access["status_code"]), detail=str(access["message"]))
        owner_username = auth_service.get_visible_owner_username(user)
        # 保存回测设置
        db.update_backtest_settings(
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            cash=cash,
            period=period,
            mode=mode,
        )
        return start_backtest_job(
            code=code,
            name=name,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            cash=cash,
            period=period,
            mode=mode,
            owner_username=owner_username,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回测失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/status")
async def get_backtest_runtime_status(request: Request):
    data = get_backtest_status()
    result = data.get("result") or {}
    strategy_name = str(result.get("strategy_name") or "")
    if strategy_name:
        user = auth_service.get_current_user_from_request(request)
        if not auth_service.can_access_owner(result.get("owner_username"), user):
            data = {**data, "result": None}
    return {"success": True, "data": data}


@router.get("/full/history")
async def list_full_backtest_history(
    request: Request,
    strategy_name: str = Query("", description="策略名称"),
    limit: int = Query(20, description="返回条数"),
):
    try:
        user = auth_service.get_current_user_from_request(request)
        items = db.list_full_backtest_runs(
            strategy_name=strategy_name or None,
            limit=limit,
            owner_username=auth_service.get_visible_owner_username(user),
        )
        items = [
            item for item in items
            if auth_service.can_view_strategy_result(str(item.get("strategy_name") or ""), user)
        ]
        return {"success": True, "data": items}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取全量回测历史失败: {e}")
        return {"success": False, "message": str(e), "data": []}


@router.get("/full/history/{run_id}")
async def get_full_backtest_history_detail(request: Request, run_id: int):
    try:
        item = db.get_full_backtest_run(run_id)
        if not item:
            return {"success": False, "message": "未找到对应的全量回测结果"}
        user = auth_service.get_current_user_from_request(request)
        if not auth_service.can_access_owner(item.get("owner_username"), user):
            raise HTTPException(status_code=403, detail="无权查看该回测结果")
        if not auth_service.can_view_strategy_result(str(item.get("strategy_name") or ""), user):
            raise HTTPException(status_code=403, detail="无权查看该策略结果")
        return {"success": True, "data": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取全量回测详情失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/full/history/{run_id}")
async def delete_full_backtest_history(request: Request, run_id: int):
    try:
        item = db.get_full_backtest_run(run_id)
        if not item:
            return {"success": False, "message": "鏈壘鍒板搴旂殑鍏ㄩ噺鍥炴祴缁撴灉"}
        user = auth_service.get_current_user_from_request(request)
        try:
            auth_service.require_operable_user(user, "临时账号不能删除回测结果，请先开通 VIP 后再操作")
        except auth_service.StrategyAccessDenied as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        if not auth_service.can_access_owner(item.get("owner_username"), user):
            raise HTTPException(status_code=403, detail="无权删除该回测结果")
        deleted = db.delete_full_backtest_run(run_id)
        if not deleted:
            return {"success": False, "message": "未找到对应的全量回测结果"}
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除全量回测详情失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/full/history/{run_id}/stock/{code}")
async def get_full_backtest_history_stock_detail(request: Request, run_id: int, code: str):
    try:
        item = db.get_full_backtest_run(run_id)
        if not item:
            return {"success": False, "message": "未找到对应的回测记录"}
        user = auth_service.get_current_user_from_request(request)
        if not auth_service.can_access_owner(item.get("owner_username"), user):
            raise HTTPException(status_code=403, detail="无权查看该回测结果")
        if not auth_service.can_view_strategy_result(str(item.get("strategy_name") or ""), user):
            raise HTTPException(status_code=403, detail="无权查看该策略结果")
        detail = build_full_backtest_stock_detail(run_id, code)
        if not detail:
            return {"success": False, "message": "未找到对应股票的回测详情"}
        return {"success": True, "data": detail}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取全量回测个股详情失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/settings")
async def get_backtest_settings_api(request: Request):
    try:
        settings = db.get_backtest_settings()
        return {"success": True, "data": settings}
    except Exception as e:
        logger.error(f"获取回测设置失败: {e}")
        return {"success": False, "message": str(e)}
