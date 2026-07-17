from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import emit
from werkzeug.exceptions import HTTPException
import threading
import os
import traceback

from config import DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR
from data_processor import error_logger, system_logger
from data_collector import data_collection_thread as data_collection_func
from news_collector import news_collection_thread as news_collection_func, init_news_data
from margin_collector import margin_collection_thread as margin_collection_func
from health_checker import get_health_status, load_health_status, get_crawler_status, load_crawler_status, start_health_checker
from routes import flow_bp, news_bp, config_bp, log_bp, house_bp, auth_bp
from routes.auth_routes import install_auth_guard
from thread_monitor import get_all_status, register_thread
from monitor import monitor_loop
from market_map_snapshot import market_map_snapshot_thread
from Jarvis import SecurityMiddleware
from Jarvis.middleware import create_security_blueprint
from Jarvis.config import get_config as get_jarvis_config

# ==================== SocketIO 实例（全局单例，定义在 ws.py） ====================
# socketio / push_event 由 ws.py 统一提供：保证 `python app.py` 启动时，
# 后台线程 `from ws import push_event` 拿到的是正在服务的同一实例，
# 不会因 __main__ 与 app 两个模块各 new 一个 SocketIO 而把推送发到无人连接的影子实例。
from ws import (
    socketio,
    push_event,
    register_client,
    unregister_client,
    record_push_pong,
    send_push_test,
)

data_collection_thread = threading.Thread(target=data_collection_func, daemon=True)
news_collection_thread = threading.Thread(target=news_collection_func, daemon=True)
margin_collection_thread = threading.Thread(target=margin_collection_func, daemon=True)
mm_snapshot_thread = threading.Thread(target=market_map_snapshot_thread, daemon=True)

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('STOCKRANK_SECRET_KEY', 'stockrank-vk-local-session')
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 365 * 100,
    )
    
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    jarvis_config = get_jarvis_config({
        'enabled': True,
        'ban_duration': 3600,
        'max_attempts': 5,
        'attempt_window': 300,
        'whitelist': ['127.0.0.1', '::1'],
        'exempt_routes': ['/health', '/api/jarvis'],
        'data_dir': os.path.join(DATA_DIR, 'jarvis'),
        'log_dir': LOG_DIR,
        'log_func': lambda level, msg: system_logger.info(f"[Jarvis] {msg}") if level == 'info' else system_logger.warning(f"[Jarvis] {msg}")
    })
    
    security = SecurityMiddleware(app, jarvis_config)
    
    jarvis_bp = create_security_blueprint(security)
    app.register_blueprint(jarvis_bp)
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(flow_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(log_bp)
    app.register_blueprint(house_bp)
    install_auth_guard(app)
    
    # ==================== SocketIO 事件 ====================
    @socketio.on('connect')
    def on_connect():
        register_client()
        system_logger.info(f"SocketIO客户端已连接: {request.sid}")
        emit('push', {'type': 'connected', 'data': {'sid': request.sid}})

    @socketio.on('disconnect')
    def on_disconnect():
        unregister_client()
        system_logger.info(f"SocketIO客户端断开: {request.sid}")

    @socketio.on('push_pong')
    def on_push_pong(data):
        # 前端对 push_ping 的静默回执（不弹通知）。仅记录 nonce 命中。
        try:
            record_push_pong((data or {}).get('nonce'))
        except Exception:
            pass
    
    @app.route('/health', methods=['GET', 'POST', 'OPTIONS'])
    def health():
        if request.method == 'OPTIONS':
            return jsonify({'success': True})
        
        if request.method == 'POST':
            from health_checker import run_full_health_check
            run_full_health_check()
        
        return jsonify({
            'status': 'ok',
            'threads': get_all_status(),
            'health': get_health_status(),
            'crawler': get_crawler_status()
        })
    
    @app.route('/api/crawler/reset', methods=['POST', 'OPTIONS'])
    def reset_crawler():
        if request.method == 'OPTIONS':
            return jsonify({'success': True})
        
        from health_checker import set_crawler_idle
        data = request.get_json() or {}
        crawler_name = data.get('crawler', '')
        
        if crawler_name:
            set_crawler_idle(crawler_name)
            system_logger.info(f"[重置] 爬虫状态已重置: {crawler_name}")
            return jsonify({'success': True, 'message': f'{crawler_name} 状态已重置'})
        
        return jsonify({'success': False, 'message': '缺少 crawler 参数'}), 400
    
    @app.route('/api/system/restart', methods=['POST', 'OPTIONS'])
    def restart_thread():
        if request.method == 'OPTIONS':
            return jsonify({'success': True})
        
        data = request.get_json() or {}
        thread_name = data.get('thread', '')
        
        if not thread_name:
            return jsonify({'success': False, 'message': '缺少 thread 参数'}), 400
        
        global data_collection_thread, news_collection_thread, margin_collection_thread
        
        if thread_name == 'data_collector':
            if data_collection_thread.is_alive():
                system_logger.info(f"[重启] data_collector 线程仍在运行，无需重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})
            
            data_collection_thread = threading.Thread(target=data_collection_func, daemon=True)
            data_collection_thread.start()
            system_logger.info(f"[重启] data_collector 线程已重新启动")
            return jsonify({'success': True, 'message': 'data_collector 线程已重启'})
        
        elif thread_name == 'news_collector':
            if news_collection_thread.is_alive():
                system_logger.info(f"[重启] news_collector 线程仍在运行，无需重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})
            
            news_collection_thread = threading.Thread(target=news_collection_func, daemon=True)
            news_collection_thread.start()
            system_logger.info(f"[重启] news_collector 线程已重新启动")
            return jsonify({'success': True, 'message': 'news_collector 线程已重启'})

        elif thread_name == 'margin_collector':
            if margin_collection_thread.is_alive():
                system_logger.info(f"[重启] margin_collector 线程仍在运行，无需重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})

            margin_collection_thread = threading.Thread(target=margin_collection_func, daemon=True)
            margin_collection_thread.start()
            system_logger.info(f"[重启] margin_collector 线程已重新启动")
            return jsonify({'success': True, 'message': 'margin_collector 线程已重启'})

        else:
            return jsonify({'success': False, 'message': f'未知的线程名称: {thread_name}'}), 400

    @app.route('/api/system/push-test', methods=['POST', 'OPTIONS'])
    def push_test():
        """手动测试消息推送服务：走真实 WebSocket 通道发一条测试消息，前端弹桌面通知。"""
        if request.method == 'OPTIONS':
            return jsonify({'success': True})
        try:
            send_push_test()
            return jsonify({'success': True, 'message': '测试消息已通过 WebSocket 发出'})
        except Exception as e:
            error_logger.error(f"推送测试失败: {e}")
            return jsonify({'success': False, 'message': f'推送测试失败: {e}'}), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            if e.code and e.code >= 500:
                error_logger.error(f"HTTP异常 {e.code}: {e}\n{traceback.format_exc()}")
            else:
                error_logger.warning(f"HTTP请求异常 {e.code}: {request.method} {request.path} - {e}")

            return jsonify({
                'success': False,
                'error': e.description,
                'code': e.code
            }), e.code

        error_logger.error(f"未捕获的异常: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
    # 初始化SocketIO
    socketio.init_app(app)
    return app

app = create_app()

if __name__ == '__main__':
    try:
        for directory in [DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR]:
            os.makedirs(directory, exist_ok=True)
        
        init_news_data()
        load_health_status()
        load_crawler_status()
        
        if not data_collection_thread.is_alive():
            data_collection_thread.start()
        
        if not news_collection_thread.is_alive():
            news_collection_thread.start()

        if not margin_collection_thread.is_alive():
            margin_collection_thread.start()

        if not mm_snapshot_thread.is_alive():
            mm_snapshot_thread.start()
        system_logger.info("大盘云图快照线程已注册启动")
        
        start_health_checker()
        system_logger.info("健康检测已启动")

        def _preload_anomaly_baseline():
            try:
                from anomaly_detector import build_baseline
                build_baseline()
                system_logger.info("异动检测基线预热完成")
            except Exception as _e:
                system_logger.warning(f"异动基线预热失败: {_e}")
        threading.Thread(target=_preload_anomaly_baseline, daemon=True).start()

        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()
        system_logger.info("监控线程已启动")

        from stock_price_monitor import stock_price_loop
        threading.Thread(target=stock_price_loop, daemon=True).start()
        system_logger.info("价格异动监控线程已启动")
        
        system_logger.info("Flask-SocketIO服务器启动")
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
        
    except KeyboardInterrupt:
        system_logger.info("服务器正在关闭...")
    except Exception as e:
        error_logger.error(f"服务器启动失败: {e}")
