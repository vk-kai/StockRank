from flask import Blueprint, jsonify, request, session

from daily_password import verify_password as _verify_daily_password
from otp_service import is_otp_enabled, load_otp_config, verify_code

auth_bp = Blueprint('auth', __name__, url_prefix='/api')

USERNAME = 'vk'


def verify_password(password):
    """校验是否等于今日动态密码（vk666 + 北京时间月日，如 vk6660710）"""
    return _verify_daily_password(password)


def is_authenticated():
    return session.get('stockrank_user') == USERNAME


def is_service_push_request():
    """量化系统推送大盘云图的 POST 请求无需鉴权，直接放行。
    仅对 POST /api/flow/market-map-push 生效；同路径的 GET/DELETE 仍需登录态。
    """
    return request.method == 'POST' and (request.path or '') == '/api/flow/market-map-push'


# 健康检查必须放行：docker healthcheck 用 curl 打 /health 判定容器存活，
# 若要求登录 → backend 永不健康 → nginx(service_healthy) 永不启动
PUBLIC_EXACT_PATHS = {'/health'}
# 登录/登出/会话查询本身必须放行，否则无法完成登录
PUBLIC_PATH_PREFIXES = ('/api/auth/',)


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

        # 仅 /api/ 开头的业务接口需要登录；静态资源、前端路由等一律不拦截
        if path.startswith('/api/') and not is_authenticated():
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
    return jsonify({
        'success': True,
        'authenticated': True,
        'username': USERNAME,
    })


@auth_bp.route('/auth/logout', methods=['POST'])
def logout():
    session.pop('stockrank_user', None)
    return jsonify({'success': True, 'authenticated': False})


@auth_bp.route('/auth/session', methods=['GET'])
def auth_session():
    authed = is_authenticated()
    return jsonify({
        'success': True,
        'authenticated': authed,
        'username': USERNAME if authed else '',
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
