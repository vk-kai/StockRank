import time

from flask import Blueprint, jsonify, request, session

from core.daily_password import verify_password as _verify_daily_password
from core.otp_service import is_otp_enabled, load_otp_config, verify_code
from core.config import load_jarvis_token, TZ_GATE_COOKIE, TZ_GATE_SECRET
from core import redemption_code

auth_bp = Blueprint('auth', __name__, url_prefix='/api')

USERNAME = 'vk'


def _grant_tz_gate(response):
    """登录/兑换成功后下发量化区门禁 cookie(nginx 据此放行量化路由)。"""
    response.set_cookie(
        TZ_GATE_COOKIE, TZ_GATE_SECRET,
        max_age=30 * 24 * 3600, path='/',
        secure=True, httponly=True, samesite='Lax',
    )
    return response


def verify_password(password):
    """校验是否等于今日动态密码（vk666 + 北京时间月日，如 vk6660710）"""
    return _verify_daily_password(password)


def is_authenticated():
    return session.get('stockrank_user') == USERNAME


def is_redeem_session_valid():
    """兑换码会话是否有效：session 里有 redeem_code，且 session 内记录的过期时间未到，
    且对应码本身仍未过期/被撤销（双保险：防止撤销后旧会话仍放行）。
    """
    code = (session.get('redeem_code') or '').strip().upper()
    if not code:
        return False
    # session 内记录的过期时间先判（快路径，无需查 JSON）
    if time.time() > float(session.get('redeem_expire', 0) or 0):
        return False
    # 再校验码本身状态（被 vk 撤销/删除 → 失效）
    return not redemption_code.is_code_expired(code)


def is_service_push_request():
    """量化系统推送大盘云图的 POST 请求无需鉴权，直接放行。
    仅对 POST /api/flow/market-map-push 生效；同路径的 GET/DELETE 仍需登录态。
    """
    return request.method == 'POST' and (request.path or '') == '/api/flow/market-map-push'


def is_jarvis_request():
    """Jarvis 手机管家 app 的请求免登录放行：app 在请求头带 X-Jarvis-Token，
    与 config/jarvis_token.json 的共享密钥匹配则放行（绕过每日密码/OTP）。
    配置缺失/为空则不启用，回退到常规登录鉴权。"""
    expected = load_jarvis_token()
    if not expected:
        return False
    provided = (request.headers.get('X-Jarvis-Token') or '').strip()
    return bool(provided) and provided == expected


# 健康检查必须放行：docker healthcheck 用 curl 打 /health 判定容器存活，
# 若要求登录 → backend 永不健康 → nginx(service_healthy) 永不启动
PUBLIC_EXACT_PATHS = {'/health'}
# 登录/登出/会话查询本身必须放行，否则无法完成登录
# /api/mp/ 是微信小程序专用接口(内容安全代理 sec + 游戏化 game)：小程序端无登录态，
# 接口自带 X-Auth-Key 共享密钥校验，sec 的 callback 由微信服务器调用(仅签名校验)，均不走本站登录
# /api/demo/ 是演示模式：未登录访客只读固定历史快照(收盘后固化，永不含实时数据)
PUBLIC_PATH_PREFIXES = ('/api/auth/', '/api/mp/', '/api/demo/')


def is_monitor_request():
    """线程监控进程(monitor.py,独立进程)的重启请求免登录放行：
    请求头 X-Monitor-Key 携带每日动态密码(vk666+MMDD,与登录同源同强度)。
    仅对 POST /api/system/restart 生效；OTP 开启时监控进程无法走 session 登录，
    用此通道保证"线程真挂了能自动拉起"的兜底能力。"""
    if request.method != 'POST' or (request.path or '') != '/api/system/restart':
        return False
    provided = (request.headers.get('X-Monitor-Key') or '').strip()
    return bool(provided) and verify_password(provided)


def install_auth_guard(app):
    @app.before_request
    def require_login():
        if request.method == 'OPTIONS':
            return None

        path = request.path or ''

        # 放行：健康检查 + 登录认证接口
        if path in PUBLIC_EXACT_PATHS or path.startswith(PUBLIC_PATH_PREFIXES):
            return None

        # 放行：量化系统通过共享密钥推送大盘云图股票
        if is_service_push_request():
            return None

        # 放行：Jarvis 手机管家 app 带 X-Jarvis-Token 共享密钥的请求
        if is_jarvis_request():
            return None

        # 放行：线程监控进程带 X-Monitor-Key(每日密码)调用重启接口
        if is_monitor_request():
            return None

        # 仅 /api/ 开头的业务接口需要登录；静态资源、前端路由等一律不拦截
        # 放行条件：vk 已登录，或持有效兑换码会话（体验访问，全站可看数据，但不能改配置/生成码）
        if path.startswith('/api/') and not (is_authenticated() or is_redeem_session_valid()):
            return jsonify({
                'success': False,
                'error': 'auth_required',
                'message': '请先登录后查看数据'
            }), 401

        return None


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    otp_code = str(data.get('otp_code') or '').strip()

    # 1) 账号密码先过（仍是 vk / vk666+月日）
    if not (username == USERNAME and verify_password(password)):
        return jsonify({
            'success': False,
            'authenticated': False,
            'error': 'invalid_credentials',
            'message': '账号或密码错误'
        }), 401

    # 2) 若已开启 OTP 动态口令，必须再校验一次口令，缺失/错误一律不建立会话
    if is_otp_enabled():
        cfg = load_otp_config()
        if not verify_code(cfg.get('secret', ''), otp_code):
            return jsonify({
                'success': False,
                'authenticated': False,
                'error': 'otp_required',
                'message': '请输入动态口令'
            }), 401

    session['stockrank_user'] = USERNAME
    session.permanent = True
    return _grant_tz_gate(jsonify({
        'success': True,
        'authenticated': True,
        'username': USERNAME,
    }))


@auth_bp.route('/auth/redeem', methods=['POST'])
def redeem():
    """兑换体验码（无需登录，已被 PUBLIC_PATH_PREFIXES 放行）。

    一次性核销：成功则建立兑换码会话（session 写 redeem_code/redeem_expire），
    返回 expire_at + 落地页 page。失败返回模糊错误（不区分 used/invalid，防枚举探测）。
    """
    data = request.get_json(silent=True) or {}
    code = str(data.get('code') or '').strip()
    if not code:
        return jsonify({'success': False, 'message': '请输入兑换码'}), 400

    result = redemption_code.redeem(code, request.remote_addr or '')
    if result.get('success'):
        session['redeem_code'] = code.upper()
        session['redeem_expire'] = result['expire_at']
        session.permanent = True
        return _grant_tz_gate(jsonify(result)), 200
    # 失败：统一 400
    return jsonify(result), 400


@auth_bp.route('/auth/logout', methods=['POST'])
def logout():
    session.pop('stockrank_user', None)
    session.pop('redeem_code', None)
    session.pop('redeem_expire', None)
    resp = jsonify({'success': True, 'authenticated': False})
    # 同步撤销量化区门禁 cookie
    resp.delete_cookie(TZ_GATE_COOKIE, path='/')
    return resp


@auth_bp.route('/auth/session', methods=['GET'])
def auth_session():
    authed = is_authenticated()
    redeem_active = is_redeem_session_valid()
    # 兑换码会话也算"已认证可看数据"；但 is_admin 只对 vk 登录态为 True
    # （凭码体验者不能进入体验码管理/改配置）。
    redeem_label = None
    if redeem_active:
        rec = redemption_code.find_in_used((session.get('redeem_code') or '').upper())
        if rec:
            redeem_label = rec.get('label')
    return jsonify({
        'success': True,
        'authenticated': authed or redeem_active,
        'username': USERNAME if authed else ('体验码' if redeem_active else ''),
        'is_admin': authed,
        'redeem_label': redeem_label,
        'redeem_expire': session.get('redeem_expire') if redeem_active else None,
    })


@auth_bp.route('/auth/otp-required', methods=['GET'])
def auth_otp_required():
    """公开接口：告诉前端登录时是否需要 OTP 动态口令输入框。
    位于 /api/auth/ 下，已被 install_auth_guard 放行（无需登录）。
    """
    return jsonify({
        'success': True,
        'otp_required': is_otp_enabled(),
    })
