"""
Flask安全中间件
提供请求拦截、攻击检测、IP封禁等功能
"""

from functools import wraps
from flask import request, jsonify, g
import time
import ipaddress

from core.daily_password import verify_password as _verify_daily_password

class SecurityMiddleware:
    def __init__(self, app=None, config=None):
        self.app = app
        self.config = config or {}
        self.checker = None
        self.ip_manager = None
        self.enabled = self.config.get('enabled', True)
        self.whitelist = self.config.get('whitelist', ['127.0.0.1', '::1'])
        self.exempt_routes = self.config.get('exempt_routes', ['/api/health', '/api/ping'])
        # 用户输入会被回显的端点(如小程序弹幕墙):携带有效 X-Auth-Key 的正常请求
        # 豁免全局攻击记录,内容由端点自身防御兜底;无 key 的裸扫描不豁免
        self.trusted_bypass_routes = self.config.get('trusted_bypass_routes', [])
        self.log_func = self.config.get('log_func', None)
        
        if app:
            self.init_app(app)
    
    def _is_ip_in_whitelist(self, ip_str):
        try:
            client_ip = ipaddress.ip_address(ip_str)
            for item in self.whitelist:
                try:
                    if '/' in item:
                        network = ipaddress.ip_network(item, strict=False)
                        if client_ip in network:
                            return True
                    else:
                        if client_ip == ipaddress.ip_address(item):
                            return True
                except ValueError:
                    if ip_str == item:
                        return True
            return False
        except ValueError:
            return ip_str in self.whitelist
    
    def _trusted_key_bypass(self, request):
        """trusted_bypass_routes 内的端点且携带有效 X-Auth-Key 时返回 True。
        校验链路异常按"不豁免"处理——宁可让端点自身防御兜底也不放过扫描。"""
        if not self.trusted_bypass_routes:
            return False
        if not any(request.path.startswith(p) for p in self.trusted_bypass_routes):
            return False
        try:
            from routes.mp_sec_routes import has_valid_auth_key
            return has_valid_auth_key()
        except Exception as e:
            self._log('warning', f'可信请求校验异常(按不豁免处理): {e}')
            return False

    def init_app(self, app, checker=None, ip_manager=None):
        from .security import SecurityChecker
        from .ip_manager import IPManager
        
        self.app = app
        self.checker = checker or SecurityChecker(self.config)
        self.ip_manager = ip_manager or IPManager(self.config)
        
        @app.before_request
        def security_check():
            try:
                if not self.enabled:
                    return None
                
                for exempt in self.exempt_routes:
                    if request.path.startswith(exempt):
                        return None
                
                client_ip = self._get_client_ip()
                
                if self._is_ip_in_whitelist(client_ip):
                    return None
                
                if request.method == 'GET' and not request.args and not request.data:
                    return None
                
                if self.ip_manager.is_banned(client_ip):
                    ban_info = self.ip_manager.get_ban_info(client_ip)
                    remaining = int(ban_info.get('ban_until', 0) - time.time())
                    
                    return jsonify({
                        'success': False,
                        'error': 'access_denied',
                        'message': '您的IP已被封禁',
                        'details': {
                            'reason': ban_info.get('attack_type', '安全违规'),
                            'remaining_seconds': max(0, remaining),
                        }
                    }), 403
                
                attack_result = self.checker.check_request(request)

                # 弹幕墙等回显端点:携带有效 X-Auth-Key 的小程序正常请求即使文字
                # 撞上攻击正则也不计入攻击记录(自有敏感词/内容安全防御兜底);
                # 无 key 的裸扫描不满足条件,照常记录并计入封禁
                if attack_result and self._trusted_key_bypass(request):
                    self._log('info', f"可信请求豁免攻击记录: {request.path} ({attack_result.get('type', 'unknown')})")
                    return None

                if attack_result:
                    attack_type = attack_result.get('type', 'unknown')
                    attack_name = self.checker.get_attack_type_name(attack_type)
                    
                    security_details = {
                        'type': 'attack_attempt',
                        'ip': client_ip,
                        'attack_type': attack_type,
                        'attack_name': attack_name,
                        'api_path': request.path,
                        'method': request.method,
                        'field': attack_result.get('field', 'unknown'),
                        'keyword': attack_result.get('matched', 'unknown')[:100],
                    }
                    
                    attempt_count = self.ip_manager.record_attempt(
                        client_ip,
                        attack_type,
                        security_details
                    )
                    
                    attempts_left = self.ip_manager.max_attempts - attempt_count
                    
                    return jsonify({
                        'success': False,
                        'error': 'security_violation',
                        'message': f'检测到危险操作，您的IP已被记录',
                        'details': {
                            'attack_type': attack_name,
                            'attempts_left': max(0, attempts_left),
                            'ip': client_ip,
                            'api_path': request.path,
                            'keyword': attack_result.get('matched', 'unknown')[:50],
                        }
                    }), 400
                
                return None
            except Exception as e:
                self._log('error', f'安全检查异常: {e}')
                import traceback
                traceback.print_exc()
                return jsonify({
                    'success': False,
                    'error': 'security_check_error',
                    'message': '安全检查异常'
                }), 500
        
        @app.after_request
        def add_security_headers(response):
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:;"
            return response
    
    def _get_client_ip(self):
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        elif request.headers.get('X-Real-IP'):
            return request.headers.get('X-Real-IP')
        return request.remote_addr or '0.0.0.0'
    
    def _log(self, level, message):
        if self.log_func:
            self.log_func(level, message)
        else:
            print(f"[Jarvis][{level.upper()}] {message}")
    
    def ban_ip(self, ip, reason='manual', duration=None):
        return self.ip_manager.ban_ip(ip, reason, duration)
    
    def unban_ip(self, ip):
        return self.ip_manager.unban_ip(ip)
    
    def get_banned_ips(self):
        return self.ip_manager.get_all_banned()
    
    def get_security_events(self, limit=100):
        return self.ip_manager.get_events(limit)
    
    def exempt(self, f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)
        decorated_function._jarvis_exempt = True
        return decorated_function
    
    def get_stats(self):
        return {
            'enabled': self.enabled,
            'banned_count': len(self.ip_manager.get_all_banned()),
            'total_events': len(self.ip_manager.get_events(1000)),
        }


def create_security_blueprint(middleware):
    from flask import Blueprint
    
    bp = Blueprint('jarvis', __name__, url_prefix='/api/jarvis')
    
    @bp.route('/stats', methods=['GET'])
    def get_stats():
        return jsonify({
            'success': True,
            'data': middleware.get_stats()
        })
    
    @bp.route('/banned', methods=['GET'])
    def get_banned():
        return jsonify({
            'success': True,
            'data': middleware.get_banned_ips()
        })
    
    @bp.route('/events', methods=['GET'])
    def get_events():
        limit = request.args.get('limit', 100, type=int)
        return jsonify({
            'success': True,
            'data': middleware.get_security_events(limit)
        })
    
    @bp.route('/ban', methods=['POST'])
    def ban_ip():
        data = request.json
        ip = data.get('ip')
        reason = data.get('reason', 'manual')
        duration = data.get('duration')
        
        if not ip:
            return jsonify({'success': False, 'message': 'IP地址不能为空'}), 400
        
        middleware.ban_ip(ip, reason, duration)
        return jsonify({'success': True, 'message': f'已封禁IP: {ip}'})
    
    @bp.route('/unban', methods=['POST'])
    def unban_ip():
        data = request.json
        ip = data.get('ip')
        password = data.get('password')
        
        if not ip:
            return jsonify({'success': False, 'message': 'IP地址不能为空'}), 400
        
        if not _verify_daily_password(password):
            return jsonify({'success': False, 'message': '密码错误'}), 403
        
        if middleware.unban_ip(ip):
            return jsonify({'success': True, 'message': f'已解封IP: {ip}'})
        return jsonify({'success': False, 'message': 'IP未被封禁'}), 400
    
    return bp
