from flask import Blueprint, jsonify, request, session

auth_bp = Blueprint('auth', __name__, url_prefix='/api')

USERNAME = 'vk'
PASSWORD = 'vk666'


def verify_password(password):
    return password == PASSWORD


def is_authenticated():
    return session.get('stockrank_user') == USERNAME


def is_service_push_request():
    """检查是否是量化系统推送大盘云图的请求（请求体携带账号密码）"""
    if request.method != 'POST':
        return False
    path = request.path or ''
    if path != '/api/flow/market-map-push':
        return False
    try:
        data = request.get_json(silent=True) or {}
        auth_username = str(data.get('auth_username') or '').strip()
        auth_password = str(data.get('auth_password') or '').strip()
        return auth_username == USERNAME and auth_password == PASSWORD
    except Exception:
        return False


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

    if username == USERNAME and verify_password(password):
        session['stockrank_user'] = USERNAME
        session.permanent = True
        return jsonify({
            'success': True,
            'authenticated': True,
            'username': USERNAME,
        })

    return jsonify({
        'success': False,
        'authenticated': False,
        'error': 'invalid_credentials',
        'message': '账号或密码错误'
    }), 401


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
