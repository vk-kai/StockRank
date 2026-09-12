from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional
import logging

from backend import auth_service
from backend.trading.account import (
    load_account, execute_buy, execute_sell, get_t1_sellable_quantity, reset_account, update_position_prices
)
from backend.security_service import get_etf_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trading", tags=["trading"])


@router.get("/account")
def get_account(request: Request):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能使用模拟交易，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    account = load_account()
    return {"success": True, "data": account.to_dict()}


@router.post("/order")
def place_order(
    request: Request,
    code: str = Query(..., description="证券代码"),
    direction: str = Query(..., description="buy/sell"),
    price: float = Query(..., description="价格"),
    quantity: int = Query(..., description="数量(股)"),
):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能模拟下单，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    account = load_account()

    etf_info = get_etf_info(code)
    name = etf_info["name"] if etf_info else code

    if direction == "buy":
        result = execute_buy(account, code, name, price, quantity)
    elif direction == "sell":
        result = execute_sell(account, code, name, price, quantity)
    else:
        return {"success": False, "message": "方向无效，请使用 buy 或 sell"}

    return result


@router.post("/reset")
def reset(request: Request):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能重置账户，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    account = reset_account()
    return {"success": True, "data": account.to_dict()}


@router.get("/positions")
def get_positions(request: Request):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能查看模拟持仓，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    account = load_account()
    positions = []
    for code, pos in account.positions.items():
        positions.append({
            "code": pos.code,
            "name": pos.name,
            "quantity": pos.quantity,
            "available_quantity": get_t1_sellable_quantity(account, code),
            "avg_cost": round(pos.avg_cost, 3),
            "current_price": round(pos.current_price, 3),
            "market_value": round(pos.market_value, 2),
            "profit": round(pos.profit, 2),
            "profit_pct": pos.profit_pct,
        })
    return {"success": True, "data": positions}


@router.get("/history")
def get_trade_history(request: Request, limit: int = Query(50, description="返回条数")):
    user = auth_service.get_current_user_from_request(request)
    try:
        auth_service.require_operable_user(user, "临时账号不能查看交易记录，请先开通 VIP 后再操作")
    except auth_service.StrategyAccessDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    account = load_account()
    trades = account.trades[-limit:]
    return {"success": True, "data": [t.__dict__ for t in trades]}
