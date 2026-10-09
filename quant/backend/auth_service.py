from __future__ import annotations

import hashlib
import html
import hmac
import base64
import json
import sqlite3
import secrets
import string
from datetime import datetime, timedelta

from backend.time_utils import now_beijing
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from backend import db
from backend.config import (
    ACCOUNT_PURCHASE_PLANS,
    ALIPAY_APP_ID,
    ALIPAY_GATEWAY,
    ALIPAY_NOTIFY_URL,
    ALIPAY_PRIVATE_KEY,
    ALIPAY_PUBLIC_KEY,
    ALIPAY_RETURN_URL,
    PAYMENT_MOCK_ENABLED,
)
from backend.daily_password import verify_password as verify_daily_password
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from backend import gateway


SESSION_COOKIE_NAME = "trendzen_session"
SESSION_DAYS = 7
TEMP_SESSION_MINUTES = 10
PUBLIC_DEFAULT_STRATEGY = "MACD_Cross"
VK_USERNAME = "vk"

_VK_ONLY_STRATEGIES = {"MA_BULL_PULLBACK_BOLL"}

_LOGIN_REQUIRED_STRATEGIES = {
    "MACD_CHAN_DIVERGENCE",
    "MACD_CHAN_THIRD_BUY",
}


class StrategyAccessDenied(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    # 会话/验证码过期全部以 naive 北京墙钟存储与比较(_dt_text/_parse_dt 均为 naive),
    # 返回去掉 tzinfo 的北京 now,避免 naive/aware 混比、也避免服务器本地时区漂移
    return now_beijing().replace(tzinfo=None)


def _dt_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _hash_secret(value: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def _verify_secret(value: str, stored_hash: str) -> bool:
    try:
        algo, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "sha256":
        return False
    expected = _hash_secret(value, salt).split("$", 2)[2]
    return hmac.compare_digest(expected, digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _public_user() -> Optional[dict]:
    return None


def is_vk_user(user: Optional[dict]) -> bool:
    return bool(user and str(user.get("username") or "").strip().lower() == VK_USERNAME)


def is_active_user(user: Optional[dict]) -> bool:
    if not user:
        return False
    if str(user.get("status") or "active").lower() != "active":
        return False
    expires_at = _parse_dt(user.get("expires_at"))
    return expires_at is None or expires_at > _now()


def is_trial_user(user: Optional[dict]) -> bool:
    return bool(user and str(user.get("role") or "").strip().lower() == "trial")


def is_operable_user(user: Optional[dict]) -> bool:
    return is_active_user(user) and not is_trial_user(user)


def _validate_username(username: str) -> bool:
    return 3 <= len(username) <= 24 and all(ch.isalnum() or ch in {"_", "-"} for ch in username)


def require_active_user(user: Optional[dict], message: str = "请先登录后再操作"):
    if not is_active_user(user):
        raise StrategyAccessDenied(message, 401)


def require_operable_user(user: Optional[dict], message: str = "临时账号只能开通 VIP、查看账单或登录登出，请先开通 VIP 后再操作"):
    if not is_active_user(user):
        raise StrategyAccessDenied("请先登录后再操作", 401)
    if is_trial_user(user):
        raise StrategyAccessDenied(message, 403)


def sanitize_user(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    role = row.get("role") or "user"
    expires_at = row.get("expires_at")
    if str(role).lower() == "trial":
        created_at = _parse_dt(row.get("created_at"))
        if created_at:
            trial_expires_at = _dt_text(created_at + timedelta(minutes=TEMP_SESSION_MINUTES))
            original_expires_at = _parse_dt(expires_at)
            if original_expires_at is None or original_expires_at > _parse_dt(trial_expires_at):
                expires_at = trial_expires_at
    return {
        "username": row.get("username"),
        "role": role,
        "expires_at": expires_at,
        "status": row.get("status") or "active",
        "must_change_credentials": bool(row.get("must_change_credentials")),
    }


def sanitize_admin_user(row: Optional[dict]) -> Optional[dict]:
    user = sanitize_user(row)
    if not user or not row:
        return user
    user.update(
        {
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "last_login_at": row.get("last_login_at"),
        }
    )
    return user


def ensure_default_users():
    db.upsert_auth_user(
        username=VK_USERNAME,
        password_hash=_hash_secret("VK666"),
        role="admin",
        expires_at=None,
        status="active",
    )


def create_captcha() -> dict:
    code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    captcha_id = secrets.token_urlsafe(18)
    expires_at = _dt_text(_now() + timedelta(minutes=5))
    db.create_auth_captcha(captcha_id, _hash_secret(code.lower()), expires_at)
    safe_code = html.escape(code)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="36" viewBox="0 0 96 36">'
        '<rect width="96" height="36" rx="6" fill="#151b2d"/>'
        '<path d="M6 25 C24 4, 48 34, 90 10" stroke="#f0b90b" stroke-width="1.4" fill="none" opacity=".55"/>'
        f'<text x="48" y="24" text-anchor="middle" font-size="18" font-family="monospace" '
        f'font-weight="700" fill="#f6d365" letter-spacing="3">{safe_code}</text>'
        "</svg>"
    )
    return {"captcha_id": captcha_id, "image_svg": svg, "expires_in": 300}


def _consume_captcha(captcha_id: str, code: str) -> bool:
    row = db.consume_auth_captcha(captcha_id)
    if not row:
        return False
    expires_at = _parse_dt(row.get("expires_at"))
    if expires_at is None or expires_at <= _now():
        return False
    return _verify_secret(str(code or "").strip().lower(), row.get("code_hash") or "")


def get_active_user_by_username(username: Optional[str]) -> Optional[dict]:
    username = str(username or "").strip().lower()
    if not username:
        return _public_user()
    user = sanitize_user(db.get_auth_user(username))
    return user if is_active_user(user) else None


def get_visible_owner_username(user: Optional[dict]) -> str:
    if is_active_user(user):
        return str(user.get("username") or VK_USERNAME).strip().lower()
    return VK_USERNAME


def can_access_owner(owner_username: Optional[str], user: Optional[dict]) -> bool:
    owner = str(owner_username or "").strip().lower()
    viewer = get_visible_owner_username(user)
    if viewer == VK_USERNAME:
        return owner in {"", VK_USERNAME}
    return owner == viewer


def get_current_user_from_request(request) -> Optional[dict]:
    # gateway 模式:鉴权由 StockRank 统一门禁承担,应用内返回合成用户
    # (已登录→管理员 vk;仅过门禁未登录→游客 guest,只读)
    gateway_user = gateway.gateway_user_if_enabled(request)
    if gateway_user is not None:
        return gateway_user
    db.delete_expired_auth_records()
    token = request.cookies.get(SESSION_COOKIE_NAME) if request is not None else None
    if not token:
        return _public_user()
    row = db.get_auth_session(_token_hash(token))
    if not row:
        return _public_user()
    expires_at = _parse_dt(row.get("expires_at"))
    if expires_at is None or expires_at <= _now():
        db.delete_auth_session(_token_hash(token))
        return _public_user()
    user = get_active_user_by_username(row.get("username"))
    if not user:
        return _public_user()
    db.touch_auth_session(_token_hash(token), _dt_text(_now()))
    return user


def login(username: str, password: str, captcha_id: str, captcha_code: str) -> dict:
    db.delete_expired_auth_records()
    if not _consume_captcha(captcha_id, captcha_code):
        return {"success": False, "message": "验证码错误或已过期"}
    normalized = str(username or "").strip().lower()
    row = db.get_auth_user(normalized)
    if not row:
        return {"success": False, "message": "账号或密码错误"}
    if normalized == VK_USERNAME:
        # vk 账号使用每日动态密码（vk666 + 北京时间月日），不再校验库里的静态哈希
        if not verify_daily_password(str(password or "")):
            return {"success": False, "message": "账号或密码错误"}
    elif not _verify_secret(str(password or ""), row.get("password_hash") or ""):
        return {"success": False, "message": "账号或密码错误"}
    user = sanitize_user(row)
    if not is_active_user(user):
        return {"success": False, "message": "账号已过期，请重新购买"}
    token = secrets.token_urlsafe(32)
    expires_at = _dt_text(_now() + timedelta(days=SESSION_DAYS))
    db.create_auth_session(_token_hash(token), normalized, expires_at)
    db.mark_auth_user_login(normalized, _dt_text(_now()))
    return {"success": True, "token": token, "user": user, "expires_at": expires_at, "max_age": SESSION_DAYS * 24 * 60 * 60}


def _create_session_for_user(username: str, expires_at: str) -> dict:
    token = secrets.token_urlsafe(32)
    db.create_auth_session(_token_hash(token), username, expires_at)
    db.mark_auth_user_login(username, _dt_text(_now()))
    user = sanitize_user(db.get_auth_user(username))
    return {
        "success": True,
        "token": token,
        "user": user,
        "expires_at": expires_at,
        "max_age": max(60, int((_parse_dt(expires_at) - _now()).total_seconds())) if _parse_dt(expires_at) else SESSION_DAYS * 24 * 60 * 60,
    }


def quick_register(captcha_id: str, captcha_code: str) -> dict:
    db.delete_expired_auth_records()
    if not _consume_captcha(captcha_id, captcha_code):
        return {"success": False, "message": "验证码错误或已过期"}
    for _ in range(20):
        username, password = _generate_account_credentials(prefix="tmp")
        expires_at = _dt_text(_now() + timedelta(minutes=TEMP_SESSION_MINUTES))
        try:
            db.create_auth_user(
                username=username,
                password_hash=_hash_secret(password),
                role="trial",
                expires_at=expires_at,
                must_change_credentials=False,
            )
            break
        except sqlite3.IntegrityError:
            continue
    else:
        return {"success": False, "message": "临时账号生成失败，请稍后重试"}
    return {
        "success": True,
        "data": {
            "account": {
                "username": username,
                "password": password,
                "expires_at": expires_at,
            },
        },
    }


def change_credentials(current_user: Optional[dict], new_username: str, new_password: str, captcha_id: str, captcha_code: str) -> dict:
    require_active_user(current_user, "请先登录后再修改账号")
    if not _consume_captcha(captcha_id, captcha_code):
        return {"success": False, "message": "验证码错误或已过期"}
    normalized = str(new_username or "").strip().lower()
    if not (3 <= len(normalized) <= 24) or not all(ch.isalnum() or ch in {"_", "-"} for ch in normalized):
        return {"success": False, "message": "用户名需为 3-24 位字母、数字、下划线或短横线"}
    if len(str(new_password or "")) < 6:
        return {"success": False, "message": "密码至少 6 位"}
    old_username = str(current_user.get("username") or "").strip().lower()
    existing = db.get_auth_user(normalized)
    if existing and str(existing.get("username") or "").lower() != old_username:
        return {"success": False, "message": "用户名已存在，请换一个"}
    user = db.update_auth_user_credentials(old_username, normalized, _hash_secret(new_password))
    if not user:
        return {"success": False, "message": "账号不存在"}
    sanitized = sanitize_user(user)
    return {
        "success": True,
        "data": {
            "user": sanitized,
            "default_strategy": get_default_strategy_for_user(sanitized),
        },
    }


def logout_token(token: Optional[str]):
    if not token:
        return
    token_hash = _token_hash(token)
    session = db.get_auth_session(token_hash)
    db.delete_auth_session(token_hash)
    if not session:
        return
    username = str(session.get("username") or "").strip().lower()
    user = db.get_auth_user(username)
    if user and str(user.get("role") or "").lower() == "trial":
        db.delete_trial_user(username)


def get_default_strategy_for_user(user: Optional[dict]) -> str:
    return "MA_BULL_PULLBACK_BOLL" if is_vk_user(user) else PUBLIC_DEFAULT_STRATEGY


def list_admin_users(current_user: Optional[dict]) -> dict:
    if not is_vk_user(current_user):
        return {"success": False, "message": "仅管理员可查看用户管理"}
    db.delete_expired_auth_records()
    return {"success": True, "data": [sanitize_admin_user(row) for row in db.list_auth_users_for_admin()]}


def update_admin_user(current_user: Optional[dict], username: str, expires_at: Optional[str], banned: bool) -> dict:
    if not is_vk_user(current_user):
        return {"success": False, "message": "仅管理员可修改用户"}
    normalized = str(username or "").strip().lower()
    if not normalized:
        return {"success": False, "message": "用户名不能为空"}
    if normalized == VK_USERNAME and banned:
        return {"success": False, "message": "不能封禁管理员账号"}

    expiry_text = str(expires_at or "").strip() or None
    if expiry_text:
        parsed = _parse_dt(expiry_text)
        if not parsed:
            return {"success": False, "message": "过期时间格式需为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS"}
        expiry_text = _dt_text(parsed)
    status = "banned" if banned else "active"
    user = db.update_auth_user_admin(normalized, expiry_text, status)
    if not user:
        return {"success": False, "message": "用户不存在"}
    return {"success": True, "data": sanitize_admin_user(user)}


def _normalize_admin_expiry(expires_at: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    expiry_text = str(expires_at or "").strip() or None
    if not expiry_text:
        return None, None
    parsed = _parse_dt(expiry_text)
    if not parsed:
        return None, "过期时间格式需要为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS"
    return _dt_text(parsed), None


def create_admin_user(current_user: Optional[dict], username: str, password: str, expires_at: Optional[str]) -> dict:
    if not is_vk_user(current_user):
        return {"success": False, "message": "仅管理员可以新增用户"}
    normalized = str(username or "").strip().lower()
    if not _validate_username(normalized):
        return {"success": False, "message": "用户名需为 3-24 位字母、数字、下划线或短横线"}
    if len(str(password or "")) < 6:
        return {"success": False, "message": "密码至少 6 位"}
    if db.get_auth_user(normalized):
        return {"success": False, "message": "用户名已存在，请换一个"}
    expiry_text, error = _normalize_admin_expiry(expires_at)
    if error:
        return {"success": False, "message": error}
    try:
        user = db.create_auth_user(
            username=normalized,
            password_hash=_hash_secret(str(password or "")),
            role="vip",
            expires_at=expiry_text,
            must_change_credentials=False,
        )
    except sqlite3.IntegrityError:
        return {"success": False, "message": "用户名已存在，请换一个"}
    return {"success": True, "data": sanitize_admin_user(user)}


def update_admin_user(
    current_user: Optional[dict],
    username: str,
    expires_at: Optional[str],
    banned: bool,
    new_username: Optional[str] = None,
    new_password: Optional[str] = None,
) -> dict:
    if not is_vk_user(current_user):
        return {"success": False, "message": "仅管理员可以修改用户"}
    normalized = str(username or "").strip().lower()
    if not normalized:
        return {"success": False, "message": "用户名不能为空"}
    target_username = str(new_username or normalized).strip().lower()
    if not _validate_username(target_username):
        return {"success": False, "message": "用户名需为 3-24 位字母、数字、下划线或短横线"}
    if normalized == VK_USERNAME and banned:
        return {"success": False, "message": "不能封禁管理员账号"}
    if normalized == VK_USERNAME and target_username != VK_USERNAME:
        return {"success": False, "message": "不能修改管理员账号用户名"}
    existing = db.get_auth_user(target_username)
    if existing and str(existing.get("username") or "").lower() != normalized:
        return {"success": False, "message": "用户名已存在，请换一个"}
    password_hash = None
    if new_password is not None and str(new_password) != "":
        if len(str(new_password)) < 6:
            return {"success": False, "message": "密码至少 6 位"}
        password_hash = _hash_secret(str(new_password))
    expiry_text, error = _normalize_admin_expiry(expires_at)
    if error:
        return {"success": False, "message": error}
    status = "banned" if banned else "active"
    user = db.update_auth_user_admin(normalized, expiry_text, status, target_username, password_hash)
    if not user:
        return {"success": False, "message": "用户不存在"}
    return {"success": True, "data": sanitize_admin_user(user)}


def delete_admin_user(current_user: Optional[dict], username: str) -> dict:
    if not is_vk_user(current_user):
        return {"success": False, "message": "仅管理员可以删除用户"}
    normalized = str(username or "").strip().lower()
    if not normalized:
        return {"success": False, "message": "用户名不能为空"}
    if normalized == VK_USERNAME:
        return {"success": False, "message": "不能删除管理员账号"}
    if not db.get_auth_user(normalized):
        return {"success": False, "message": "用户不存在"}
    if not db.delete_auth_user_for_admin(normalized):
        return {"success": False, "message": "删除用户失败"}
    return {"success": True, "data": {"username": normalized}}


def get_strategy_access(strategy_name: str, user: Optional[dict]) -> dict:
    name = str(strategy_name or "").strip() or PUBLIC_DEFAULT_STRATEGY
    if is_trial_user(user):
        return {
            "allowed": False,
            "status_code": 403,
            "message": "临时账号只能开通 VIP 和查看账单，请先开通 VIP 后再使用策略",
        }
    if name in _VK_ONLY_STRATEGIES:
        if is_vk_user(user):
            return {"allowed": True}
        return {
            "allowed": False,
            "status_code": 403 if is_active_user(user) else 401,
            "message": "该策略仅限管理员使用",
        }
    if name in _LOGIN_REQUIRED_STRATEGIES and not is_operable_user(user):
        return {
            "allowed": False,
            "status_code": 401,
            "message": "请先登录后再使用该策略",
        }
    return {"allowed": True}


def get_strategy_visibility(strategy_name: str, user: Optional[dict]) -> dict:
    name = str(strategy_name or "").strip() or PUBLIC_DEFAULT_STRATEGY
    if name in _VK_ONLY_STRATEGIES and not is_vk_user(user):
        return {"visible": False}
    if name in _LOGIN_REQUIRED_STRATEGIES and not is_operable_user(user):
        return {
            "visible": True,
            "locked": True,
            "lock_message": "临时账号需先开通 VIP 后再使用该策略" if is_trial_user(user) else "请先登录后再使用该策略",
        }
    return {"visible": True, "locked": False}


def can_view_strategy_result(strategy_name: str, user: Optional[dict]) -> bool:
    return True


def filter_strategy_options(strategies: list[dict], user: Optional[dict]) -> list[dict]:
    visible = []
    for item in strategies:
        name = str(item.get("name") or "")
        visibility = get_strategy_visibility(name, user)
        if not visibility.get("visible"):
            continue
        visible.append(
            {
                **item,
                "vk_only": name in _VK_ONLY_STRATEGIES,
                "requires_login": name in _LOGIN_REQUIRED_STRATEGIES,
                "locked": bool(visibility.get("locked")),
                "lock_message": visibility.get("lock_message"),
            }
        )
    return visible


def _generate_account_credentials(prefix: str = "u") -> tuple[str, str]:
    suffix = "".join(secrets.choice(string.digits) for _ in range(8))
    username = f"{prefix}{suffix}"
    while db.get_auth_user(username):
        suffix = "".join(secrets.choice(string.digits) for _ in range(8))
        username = f"{prefix}{suffix}"
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(10))
    return username, password


def list_purchase_plans() -> list[dict]:
    return [
        {
            "key": key,
            "label": plan["label"],
            "price": float(plan["price"]),
            "duration_days": int(plan["duration_days"]),
        }
        for key, plan in ACCOUNT_PURCHASE_PLANS.items()
    ]


def _format_amount(value: float) -> str:
    return f"{float(value):.2f}"


def _is_alipay_configured() -> bool:
    return all([ALIPAY_APP_ID, ALIPAY_PRIVATE_KEY, ALIPAY_PUBLIC_KEY, ALIPAY_GATEWAY])


def _load_private_key():
    text = str(ALIPAY_PRIVATE_KEY or "").strip()
    if not text:
        raise ValueError("ALIPAY_PRIVATE_KEY is empty")
    if "BEGIN" in text:
        return serialization.load_pem_private_key(text.replace("\\n", "\n").encode("utf-8"), password=None)
    return serialization.load_der_private_key(base64.b64decode(text), password=None)


def _load_public_key():
    text = str(ALIPAY_PUBLIC_KEY or "").strip()
    if not text:
        raise ValueError("ALIPAY_PUBLIC_KEY is empty")
    if "BEGIN" in text:
        return serialization.load_pem_public_key(text.replace("\\n", "\n").encode("utf-8"))
    return serialization.load_der_public_key(base64.b64decode(text))


def _build_sign_content(params: dict, include_sign_type: bool = True) -> str:
    filtered = {
        str(key): str(value)
        for key, value in params.items()
        if value not in (None, "") and key != "sign" and (include_sign_type or key != "sign_type")
    }
    return "&".join(f"{key}={filtered[key]}" for key in sorted(filtered))


def _alipay_sign(params: dict) -> str:
    signature = _load_private_key().sign(
        _build_sign_content(params).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def verify_alipay_notify(params: dict) -> bool:
    sign = str(params.get("sign") or "")
    if not sign:
        return False
    try:
        _load_public_key().verify(
            base64.b64decode(sign),
            _build_sign_content(params, include_sign_type=False).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _build_alipay_page_pay_url(order_id: str, plan: dict) -> str:
    if not _is_alipay_configured():
        return ""
    params = {
        "app_id": ALIPAY_APP_ID,
        "method": "alipay.trade.page.pay",
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": _dt_text(_now()),
        "version": "1.0",
        "notify_url": ALIPAY_NOTIFY_URL,
        "return_url": ALIPAY_RETURN_URL,
        "biz_content": json.dumps(
            {
                "out_trade_no": order_id,
                "product_code": "FAST_INSTANT_TRADE_PAY",
                "total_amount": _format_amount(float(plan["price"])),
                "subject": f"TrendZen {plan['label']}",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    params["sign"] = _alipay_sign(params)
    return f"{ALIPAY_GATEWAY}?{urlencode(params)}"


def _alipay_gateway_request(method: str, biz_content: dict) -> dict:
    if not _is_alipay_configured():
        return {}
    params = {
        "app_id": ALIPAY_APP_ID,
        "method": method,
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": _dt_text(_now()),
        "version": "1.0",
        "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
    }
    params["sign"] = _alipay_sign(params)
    data = urlencode(params).encode("utf-8")
    request = UrlRequest(
        ALIPAY_GATEWAY,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        payload = response.read().decode("utf-8", errors="ignore")
    return json.loads(payload)


def _sync_alipay_order_status(order: dict) -> dict:
    if PAYMENT_MOCK_ENABLED or not _is_alipay_configured():
        return {"success": True, "paid": False}
    order_id = str(order.get("id") or "")
    try:
        payload = _alipay_gateway_request("alipay.trade.query", {"out_trade_no": order_id})
    except Exception as exc:
        return {"success": False, "paid": False, "message": f"支付宝查单失败：{exc}"}

    response = payload.get("alipay_trade_query_response") or {}
    code = str(response.get("code") or "")
    if code != "10000":
        return {
            "success": False,
            "paid": False,
            "message": str(response.get("sub_msg") or response.get("msg") or "支付宝订单未支付"),
        }

    if str(response.get("trade_status") or "") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return {"success": True, "paid": False}

    paid_amount = _format_amount(float(response.get("total_amount") or 0))
    expected_amount = _format_amount(float(order.get("amount") or 0))
    if paid_amount != expected_amount:
        return {"success": False, "paid": False, "message": "支付宝支付金额与订单金额不一致"}

    result = complete_purchase_order(order_id, provider_trade_no=str(response.get("trade_no") or ""))
    return {"success": bool(result.get("success")), "paid": bool(result.get("success")), **result}


def _serialize_order(order: dict, include_pay_url: bool = True) -> dict:
    data = {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "mock": PAYMENT_MOCK_ENABLED,
        "plan": {
            "key": order.get("plan_key"),
            "label": order.get("plan_label"),
            "price": float(order.get("amount") or 0),
            "duration_days": int(order.get("duration_days") or 0),
        },
        "created_at": order.get("created_at"),
        "paid_at": order.get("paid_at"),
        "expires_at": order.get("expires_at"),
    }
    if include_pay_url and order.get("status") == "pending" and not PAYMENT_MOCK_ENABLED:
        data["pay_url"] = _build_alipay_page_pay_url(
            str(order.get("id") or ""),
            {
                "label": order.get("plan_label"),
                "price": float(order.get("amount") or 0),
            },
        )
    return data


def create_purchase_order(plan_key: str, current_user: Optional[dict]) -> dict:
    require_active_user(current_user, "请先一键注册或登录后再开通 VIP")
    buyer_username = str(current_user.get("username") or "").strip().lower()
    existing = db.get_pending_payment_order_for_buyer(buyer_username)
    if existing:
        return {
            "success": False,
            "message": "当前账号已有一笔待支付订单，请先支付或取消后再创建新订单",
            "data": _serialize_order(existing),
        }
    plan = ACCOUNT_PURCHASE_PLANS.get(str(plan_key or ""))
    if not plan:
        return {"success": False, "message": "未知的购买套餐"}
    if not PAYMENT_MOCK_ENABLED and not _is_alipay_configured():
        return {"success": False, "message": "Alipay is not configured"}
    order_id = f"TZ{now_beijing().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(3).upper()}"
    db.create_payment_order(
        order_id=order_id,
        plan_key=plan_key,
        plan_label=str(plan["label"]),
        amount=float(plan["price"]),
        duration_days=int(plan["duration_days"]),
        provider="alipay",
        buyer_username=buyer_username,
    )
    return {
        "success": True,
        "data": _serialize_order(db.get_payment_order(order_id) or {}, include_pay_url=True),
    }


def _can_access_order(order: dict, current_user: Optional[dict]) -> bool:
    if not is_active_user(current_user):
        return False
    buyer = str(order.get("buyer_username") or "").strip().lower()
    viewer = str(current_user.get("username") or "").strip().lower()
    return not buyer or buyer == viewer or is_vk_user(current_user)


def get_purchase_order_status(order_id: str, current_user: Optional[dict] = None) -> dict:
    order = db.get_payment_order(order_id)
    if not order:
        return {"success": False, "message": "订单不存在"}
    if current_user is not None and not _can_access_order(order, current_user):
        return {"success": False, "message": "无权查看该订单"}
    if order.get("status") == "pending":
        sync_result = _sync_alipay_order_status(order)
        if not sync_result.get("success"):
            return {"success": False, "message": sync_result.get("message") or "查询支付宝订单失败"}
        if sync_result.get("paid"):
            order = db.get_payment_order(order_id) or order
    data = _serialize_order(order)
    if order.get("status") == "paid" and order.get("username"):
        data["user"] = sanitize_user(db.get_auth_user(str(order.get("username") or "")))
    return {"success": True, "data": data}


def list_purchase_orders(current_user: Optional[dict]) -> dict:
    require_active_user(current_user, "请先登录后查看账单")
    username = str(current_user.get("username") or "").strip().lower()
    orders = db.list_payment_orders_for_buyer(username)
    return {"success": True, "data": [_serialize_order(order, include_pay_url=True) for order in orders]}


def cancel_purchase_order(order_id: str, current_user: Optional[dict]) -> dict:
    require_active_user(current_user, "请先登录后取消订单")
    ok = db.cancel_pending_payment_order(order_id, str(current_user.get("username") or ""))
    if not ok:
        return {"success": False, "message": "只能取消当前账号的未支付订单"}
    return {"success": True}


def mock_complete_purchase_order(order_id: str, current_user: Optional[dict] = None) -> dict:
    if not PAYMENT_MOCK_ENABLED:
        return {"success": False, "message": "模拟支付未开启"}
    if not is_vk_user(current_user):
        return {"success": False, "message": "模拟支付只允许管理员操作"}
    order = db.get_payment_order(order_id)
    if not order:
        return {"success": False, "message": "订单不存在"}
    if current_user is not None and not _can_access_order(order, current_user):
        return {"success": False, "message": "无权操作该订单"}
    return complete_purchase_order(order_id, provider_trade_no=f"MOCK-{order_id}")


def complete_alipay_notify(params: dict) -> dict:
    if not verify_alipay_notify(params):
        return {"success": False, "message": "Alipay signature verification failed"}
    if str(params.get("trade_status") or "") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return {"success": False, "message": "Alipay trade is not paid"}
    order_id = str(params.get("out_trade_no") or "")
    order = db.get_payment_order(order_id)
    if not order:
        return {"success": False, "message": "订单不存在"}
    paid_amount = _format_amount(float(params.get("total_amount") or 0))
    expected_amount = _format_amount(float(order.get("amount") or 0))
    if paid_amount != expected_amount:
        return {"success": False, "message": "Alipay paid amount mismatch"}
    return complete_purchase_order(order_id, provider_trade_no=str(params.get("trade_no") or ""))


def complete_purchase_order(order_id: str, provider_trade_no: str = "") -> dict:
    order = db.get_payment_order(order_id)
    if not order:
        return {"success": False, "message": "订单不存在"}
    if order.get("status") == "paid" and order.get("username"):
        user = sanitize_user(db.get_auth_user(str(order.get("username") or "")))
        return {
            "success": True,
            "data": {
                "user": user,
                "order": _serialize_order(order, include_pay_url=False),
            },
        }
    username = str(order.get("buyer_username") or "").strip().lower()
    if not username:
        return {"success": False, "message": "订单未绑定用户，无法开通 VIP"}
    user_row = db.get_auth_user(username)
    if not user_row:
        return {"success": False, "message": "订单用户不存在"}
    current_expiry = _parse_dt(user_row.get("expires_at"))
    can_stack_expiry = str(user_row.get("role") or "").lower() in {"vip", "admin"}
    base_time = current_expiry if can_stack_expiry and current_expiry and current_expiry > _now() else _now()
    expires_at = _dt_text(base_time + timedelta(days=int(order.get("duration_days") or 1)))
    must_change_credentials = str(user_row.get("role") or "").lower() == "trial"
    db.update_auth_user_vip(
        username=username,
        role="vip",
        expires_at=expires_at,
        must_change_credentials=must_change_credentials,
    )
    db.mark_payment_order_paid(
        order_id=order_id,
        provider_trade_no=provider_trade_no,
        username=username,
        password_plain="",
        expires_at=expires_at,
    )
    paid_order = db.get_payment_order(order_id) or order
    user = sanitize_user(db.get_auth_user(username))
    return {
        "success": True,
        "data": {
            "user": user,
            "order": _serialize_order(paid_order, include_pay_url=False),
        },
    }
