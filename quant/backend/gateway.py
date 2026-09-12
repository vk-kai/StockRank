# -*- coding: utf-8 -*-
"""统一门禁的网关模式(合并进 StockRank 后的运行形态)。

背景:量化后端原有一套独立的 用户名密码+验证码+订阅支付 体系,合并后全部下线,
鉴权统一由 StockRank 登录门禁承担:nginx 只把通过 StockRank 门禁的请求
(携带 tz_gate cookie)转发进来。本模块在应用内做第二道同源校验(纵深防御)。

两种模式:
  standalone(默认,不设 QUANT_GATE_MODE):行为与合并前完全一致,本地开发零影响;
  gateway(QUANT_GATE_MODE=1):
    - 请求须携带有效凭证:cookie tz_gate == QUANT_GATE_SECRET,
      或头 X-Internal-Token == QUANT_GATE_SECRET(供 Flask 侧服务间调用);
    - 登录/注册/验证码/订阅支付/用户管理等端点直接 410(入口已关闭);
    - auth_service.get_current_user_from_request 返回合成管理员(vk/admin),
      所有策略权限随之全开;模拟账户照常工作。

QUANT_GATE_SECRET 与 StockRank nginx 的 tz_gate SECRET 保持一致。
"""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# 已下线的端点前缀(统一走 StockRank 门禁后不再需要)
_DISABLED_PREFIXES = (
    "/api/auth/login",
    "/api/auth/quick-register",
    "/api/auth/change-credentials",
    "/api/auth/register",
    "/api/auth/captcha",
    "/api/auth/purchase",
    "/api/auth/admin",
    "/api/alipay",
)

# 不做门禁校验的路径(健康检查 + Flask 侧带内部令牌轮询的套利 feed 与扫描信号 feed)
_OPEN_PREFIXES = (
    "/health",
    "/api/market/arb/feed",
    "/api/market/scan/feed",
)

GATEWAY_USER = {
    "username": "vk",
    "role": "admin",
    "expires_at": None,
    "status": "active",
    "must_change_credentials": False,
}


def is_gateway_mode() -> bool:
    return os.environ.get("QUANT_GATE_MODE", "").strip() in ("1", "true", "yes", "on")


def gate_secret() -> str:
    return os.environ.get("QUANT_GATE_SECRET", "").strip()


def gateway_user_if_enabled():
    """gateway 模式下返回合成管理员;standalone 模式返回 None(走原鉴权)。"""
    return dict(GATEWAY_USER) if is_gateway_mode() else None


def has_gate_credential(request) -> bool:
    """cookie tz_gate 或头 X-Internal-Token 命中即通过(与 nginx 判定同源)。"""
    secret = gate_secret()
    if not secret:
        # 未配置密钥时不拦请求(网关层由 nginx 兜底),避免配置遗漏导致服务不可用
        return True
    if request.headers.get("X-Internal-Token") == secret:
        return True
    cookie = request.cookies.get("tz_gate")
    return cookie == secret


class GatewayMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not is_gateway_mode():
            return await call_next(request)

        path = request.url.path
        for prefix in _DISABLED_PREFIXES:
            if path.startswith(prefix):
                return JSONResponse(
                    {
                        "success": False,
                        "message": "该入口已并入 StockRank 统一门禁,请从作战台进入",
                    },
                    status_code=410,
                )
        for prefix in _OPEN_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        if not has_gate_credential(request):
            return JSONResponse(
                {"success": False, "message": "未通过统一门禁,请从作战台进入"},
                status_code=401,
            )
        return await call_next(request)


def websocket_gate_ok(websocket) -> bool:
    """WebSocket 握手前的门禁校验(HTTP 中间件覆盖不到 ws)。"""
    if not is_gateway_mode():
        return True
    secret = gate_secret()
    if not secret:
        return True
    return websocket.cookies.get("tz_gate") == secret
