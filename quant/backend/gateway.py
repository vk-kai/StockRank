# -*- coding: utf-8 -*-
"""统一门禁的网关模式(合并进 StockRank 后的运行形态)。

背景:量化后端原有一套独立的 用户名密码+验证码+订阅支付 体系,合并后全部下线,
鉴权统一由 StockRank 登录门禁承担:nginx 只把通过 StockRank 门禁的请求
(携带 tz_gate cookie)转发进来。本模块在应用内做第二道同源校验(纵深防御)。

两种模式:
  standalone(默认,不设 QUANT_GATE_MODE):行为与合并前完全一致,本地开发零影响;
  gateway(QUANT_GATE_MODE=1):
    - 请求须携带有效门禁凭证:cookie tz_gate == QUANT_GATE_SECRET,
      或 URL 参数 ?tz_gate= == SECRET(与 nginx 判定同源,覆盖首次进入尚未种 cookie 的请求),
      或头 X-Internal-Token == QUANT_GATE_SECRET(供 Flask 侧服务间调用);
    - 登录/注册/验证码/订阅支付/用户管理等端点直接 410(入口已关闭);
    - 身份分级:
        携带 tz_user cookie(StockRank 登录时下发的 HMAC 签名)或 X-Internal-Token
        → 合成管理员(vk/admin),所有策略权限全开,模拟账户照常;
        否则 → 游客(guest):可查看一切数据,写操作(POST/PUT/PATCH/DELETE)一律 403,
        前端弹"前往 StockRank 登录"引导。少量"查看动作附带的已读上报"接口豁免。

QUANT_GATE_SECRET 与 StockRank nginx 的 tz_gate SECRET 保持一致。
"""
from __future__ import annotations

import hashlib
import hmac
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

# 游客(只读)放行的写接口:均为"查看时上报已读/自身登出",无业务数据变更
_GUEST_MUTATION_EXEMPT_PREFIXES = (
    "/api/market/arb/feed/ack",
    "/api/market/arb/read",
    "/api/market/scan/read",
    "/api/auth/logout",
)

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

GATEWAY_USER = {
    "username": "vk",
    "role": "admin",
    "expires_at": None,
    "status": "active",
    "must_change_credentials": False,
}

# 游客合成用户:status 非 active → get_visible_owner_username 回落到 vk,
# 即游客可见 vk 的全部数据;is_vk_user/is_trial_user 均为 False,权限自然收紧。
GATEWAY_GUEST_USER = {
    "username": "guest",
    "role": "guest",
    "expires_at": None,
    "status": "guest",
    "must_change_credentials": False,
}


def is_gateway_mode() -> bool:
    return os.environ.get("QUANT_GATE_MODE", "").strip() in ("1", "true", "yes", "on")


def gate_secret() -> str:
    return os.environ.get("QUANT_GATE_SECRET", "").strip()


def user_token() -> str:
    """与 StockRank Flask 侧 _tz_user_token 同源:HMAC-SHA256(SECRET, 用户名)。"""
    secret = gate_secret()
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), b"vk", hashlib.sha256).hexdigest()


def gateway_user_if_enabled(request=None):
    """gateway 模式返回合成用户(已登录→管理员,未登录→游客);standalone 返回 None(走原鉴权)。"""
    if not is_gateway_mode():
        return None
    if request is None or is_verified_user(request):
        return dict(GATEWAY_USER)
    return dict(GATEWAY_GUEST_USER)


def has_gate_credential(request) -> bool:
    """cookie tz_gate / URL 参数 ?tz_gate= / 头 X-Internal-Token 命中即通过(与 nginx 判定同源)。"""
    secret = gate_secret()
    if not secret:
        # 未配置密钥时不拦请求(网关层由 nginx 兜底),避免配置遗漏导致服务不可用
        return True
    if request.headers.get("X-Internal-Token") == secret:
        return True
    try:
        if request.query_params.get("tz_gate") == secret:
            return True
    except Exception:
        pass
    cookie = request.cookies.get("tz_gate")
    return cookie == secret


def is_verified_user(request) -> bool:
    """是否"已登录可操作":X-Internal-Token(服务间调用)或 tz_user HMAC 签名 cookie 命中。"""
    secret = gate_secret()
    if not secret:
        return True
    if request.headers.get("X-Internal-Token") == secret:
        return True
    expected = user_token()
    provided = request.cookies.get("tz_user") or ""
    return bool(expected) and hmac.compare_digest(provided, expected)


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
        # 游客只读:写操作一律 403(豁免"查看附带的已读上报"接口)
        if request.method in _MUTATING_METHODS and not is_verified_user(request):
            for prefix in _GUEST_MUTATION_EXEMPT_PREFIXES:
                if path.startswith(prefix):
                    break
            else:
                return JSONResponse(
                    {"success": False, "message": "游客只读模式:请登录 StockRank 后再操作"},
                    status_code=403,
                )
        return await call_next(request)


def websocket_gate_ok(websocket) -> bool:
    """WebSocket 握手前的门禁校验(HTTP 中间件覆盖不到 ws)。"""
    if not is_gateway_mode():
        return True
    secret = gate_secret()
    if not secret:
        return True
    if websocket.query_params.get("tz_gate") == secret:
        return True
    return websocket.cookies.get("tz_gate") == secret
