from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qsl

from pydantic import BaseModel
from fastapi import APIRouter, Request, Response

from backend import auth_service
from backend import gateway


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str
    password: str
    captcha_id: str
    captcha_code: str


class PurchasePayload(BaseModel):
    plan_key: str


class ChangeCredentialsPayload(BaseModel):
    username: str
    password: str
    captcha_id: str
    captcha_code: str


class QuickRegisterPayload(BaseModel):
    captcha_id: str
    captcha_code: str


class AdminUserUpdatePayload(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    expires_at: Optional[str] = None
    banned: bool = False


class AdminUserCreatePayload(BaseModel):
    username: str
    password: str
    expires_at: Optional[str] = None


@router.get("/captcha")
def get_captcha():
    return {"success": True, "data": auth_service.create_captcha()}


@router.get("/session")
def get_session(request: Request):
    user = auth_service.get_current_user_from_request(request)
    return {
        "success": True,
        "data": {
            "user": user,
            "default_strategy": auth_service.get_default_strategy_for_user(user),
            "gateway": gateway.is_gateway_mode(),
        },
    }


@router.post("/login")
def login(payload: LoginPayload, response: Response):
    result = auth_service.login(
        username=payload.username,
        password=payload.password,
        captcha_id=payload.captcha_id,
        captcha_code=payload.captcha_code,
    )
    if not result.get("success"):
        response.status_code = 401
        return result

    response.set_cookie(
        auth_service.SESSION_COOKIE_NAME,
        str(result["token"]),
        max_age=int(result.get("max_age") or auth_service.SESSION_DAYS * 24 * 60 * 60),
        httponly=True,
        samesite="lax",
    )
    return {
        "success": True,
        "data": {
            "user": result["user"],
            "expires_at": result["expires_at"],
            "default_strategy": auth_service.get_default_strategy_for_user(result["user"]),
        },
    }


@router.post("/quick-register")
def quick_register(payload: QuickRegisterPayload, response: Response):
    result = auth_service.quick_register(
        captcha_id=payload.captcha_id,
        captcha_code=payload.captcha_code,
    )
    if not result.get("success"):
        response.status_code = 400
        return result
    return result


@router.post("/change-credentials")
def change_credentials(payload: ChangeCredentialsPayload, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.change_credentials(
        current_user=user,
        new_username=payload.username,
        new_password=payload.password,
        captcha_id=payload.captcha_id,
        captcha_code=payload.captcha_code,
    )
    if not result.get("success"):
        response.status_code = 400
    return result


@router.get("/admin/users")
def list_admin_users(request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.list_admin_users(user)
    if not result.get("success"):
        response.status_code = 403
    return result


@router.post("/admin/users")
def create_admin_user(payload: AdminUserCreatePayload, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.create_admin_user(
        current_user=user,
        username=payload.username,
        password=payload.password,
        expires_at=payload.expires_at,
    )
    if not result.get("success"):
        response.status_code = 400 if auth_service.is_vk_user(user) else 403
    return result


@router.patch("/admin/users/{username}")
def update_admin_user(username: str, payload: AdminUserUpdatePayload, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.update_admin_user(
        current_user=user,
        username=username,
        new_username=payload.username,
        new_password=payload.password,
        expires_at=payload.expires_at,
        banned=payload.banned,
    )
    if not result.get("success"):
        response.status_code = 400 if auth_service.is_vk_user(user) else 403
    return result


@router.delete("/admin/users/{username}")
def delete_admin_user(username: str, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.delete_admin_user(user, username)
    if not result.get("success"):
        response.status_code = 400 if auth_service.is_vk_user(user) else 403
    return result


@router.post("/logout")
def logout(request: Request, response: Response):
    auth_service.logout_token(request.cookies.get(auth_service.SESSION_COOKIE_NAME))
    response.delete_cookie(auth_service.SESSION_COOKIE_NAME, samesite="lax")
    return {
        "success": True,
        "data": {
            "user": None,
            "default_strategy": auth_service.PUBLIC_DEFAULT_STRATEGY,
        },
    }


@router.post("/register")
def register(response: Response):
    response.status_code = 403
    return {"success": False, "message": "账号需要购买开通，目前不接受自行注册"}


@router.get("/purchase/plans")
def purchase_plans():
    return {"success": True, "data": auth_service.list_purchase_plans()}


@router.post("/purchase")
def create_purchase(payload: PurchasePayload, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.create_purchase_order(payload.plan_key, user)
    if not result.get("success"):
        response.status_code = 400
    return result


@router.get("/purchase")
def list_purchase(request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.list_purchase_orders(user)
    if not result.get("success"):
        response.status_code = 401
    return result


@router.get("/purchase/{order_id}")
def get_purchase(order_id: str, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.get_purchase_order_status(order_id, user)
    if not result.get("success"):
        response.status_code = 404
    return result


@router.post("/purchase/{order_id}/cancel")
def cancel_purchase(order_id: str, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.cancel_purchase_order(order_id, user)
    if not result.get("success"):
        response.status_code = 400
    return result


@router.post("/purchase/{order_id}/mock-complete")
def mock_complete_purchase(order_id: str, request: Request, response: Response):
    user = auth_service.get_current_user_from_request(request)
    result = auth_service.mock_complete_purchase_order(order_id, user)
    if not result.get("success"):
        response.status_code = 400
    return result


@router.post("/alipay/notify")
async def alipay_notify(request: Request):
    body = (await request.body()).decode("utf-8", errors="ignore")
    params = {str(key): str(value) for key, value in parse_qsl(body, keep_blank_values=True)}
    result = auth_service.complete_alipay_notify(params)
    return "success" if result.get("success") else "fail"
