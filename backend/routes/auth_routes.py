from flask import Blueprint, jsonify, request, session

auth_bp = Blueprint('auth', __name__, url_prefix='/api')

USERNAME = 'vk'
PASSWORD = 'vk666'

def verify_password(password):
    return password == PASSWORD


def is_authenticated():
    return session.get('stockrank_user') == USERNAME


def install_auth_guard(app):
    @app.before_request
    def require_login():
        if request.method == 'OPTIONS':
            return None

        path = request.path or ''
        if path.startswith('/api/auth/'):
            return None

        protected = path.startswith('/api/') or path == '/health'
        if protected and not is_authenticated():
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
