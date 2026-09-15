from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import emit
from werkzeug.exceptions import HTTPException
import threading
import os
import traceback

from core.config import DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR
from data.data_processor import error_logger, system_logger
from data.data_collector import data_collection_thread as data_collection_func
from data.news_collector import news_collection_thread as news_collection_func, init_news_data
from data.margin_collector import margin_collection_thread as margin_collection_func
from monitors.health_checker import get_health_status, load_health_status, get_crawler_status, load_crawler_status, start_health_checker
from routes import flow_bp, news_bp, config_bp, log_bp, house_bp, auth_bp, jarvis_app_bp, mp_sec_bp, mp_game_bp, mp_admin_bp, mp_vpay_bp, demo_bp
from routes.auth_routes import install_auth_guard
from core.session_secret import load_session_secret
from monitors.thread_monitor import get_all_status, register_thread
from monitors.monitor import monitor_loop
from data.market_map_snapshot import market_map_snapshot_thread
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

# 可重启的长睡眠线程句柄(/api/system/restart 用;__main__ 启动时赋值)。
# 原先这三个线程启动后丢弃句柄,重启接口无法拉起它们——真挂了只能人工重启容器。
trendzen_arb_thread = None
quant_signal_thread = None
vpay_checker_thread = None
stock_pulse_thread = None

def create_app():
    app = Flask(__name__)
    # 会话密钥：优先用持久化文件（开启 OTP 时旋转过），其次环境变量，最后默认值。
    # 旋转持久化密钥可让所有已登录会话立即失效（强制重新登录）。
    app.secret_key = load_session_secret('stockrank-vk-local-session')
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
        # 弹幕墙留言会被原样回显,正常用户文字撞上攻击正则会被误封:
        # 携带有效 X-Auth-Key 的小程序请求豁免攻击记录(端点自有敏感词/内容安全防御),
        # 无 key 的裸扫描不豁免,照常记录封禁
        'trusted_bypass_routes': ['/api/mp/game/echo'],
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
    app.register_blueprint(jarvis_app_bp)
    app.register_blueprint(mp_sec_bp)
    app.register_blueprint(mp_game_bp)
    app.register_blueprint(mp_admin_bp)
    app.register_blueprint(mp_vpay_bp)
    app.register_blueprint(demo_bp)
    install_auth_guard(app)
    
    # ==================== SocketIO 事件 ====================
    @socketio.on('connect')
    def on_connect():
        register_client()
        # 仅在调试模式下记录连接日志
        # system_logger.info(f"SocketIO客户端已连接: {request.sid}")
        emit('push', {'type': 'connected', 'data': {'sid': request.sid}})

    @socketio.on('disconnect')
    def on_disconnect():
        unregister_client()
        # 仅在调试模式下记录断开日志
        # system_logger.info(f"SocketIO客户端断开: {request.sid}")

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
            from monitors.health_checker import run_full_health_check
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
        
        from monitors.health_checker import set_crawler_idle
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
        global trendzen_arb_thread, quant_signal_thread, vpay_checker_thread, stock_pulse_thread
        
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

        elif thread_name == 'trendzen_arb_monitor':
            if trendzen_arb_thread is not None and trendzen_arb_thread.is_alive():
                system_logger.info(f"[重启] trendzen_arb_monitor 线程仍在运行(疑似心跳误报)，无需重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})

            from monitors.trendzen_arb_monitor import trendzen_arb_loop
            trendzen_arb_thread = threading.Thread(target=trendzen_arb_loop, daemon=True)
            trendzen_arb_thread.start()
            system_logger.info(f"[重启] trendzen_arb_monitor 线程已重新启动")
            return jsonify({'success': True, 'message': 'trendzen_arb_monitor 线程已重启'})

        elif thread_name == 'quant_signal_bridge':
            if quant_signal_thread is not None and quant_signal_thread.is_alive():
                system_logger.info(f"[重启] quant_signal_bridge 线程仍在运行(疑似心跳误报)，无需重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})

            from monitors.quant_signal_bridge import quant_signal_bridge_loop
            quant_signal_thread = threading.Thread(target=quant_signal_bridge_loop, daemon=True)
            quant_signal_thread.start()
            system_logger.info(f"[重启] quant_signal_bridge 线程已重新启动")
            return jsonify({'success': True, 'message': 'quant_signal_bridge 线程已重启'})

        elif thread_name == 'vpay_pending_checker':
            if vpay_checker_thread is not None and vpay_checker_thread.is_alive():
                system_logger.info(f"[重启] vpay_pending_checker 线程仍在运行(疑似心跳误报)，无需重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})

            from routes.mp_vpay_routes import vpay_check_loop
            vpay_checker_thread = threading.Thread(target=vpay_check_loop, daemon=True)
            vpay_checker_thread.start()
            system_logger.info(f"[重启] vpay_pending_checker 线程已重新启动")
            return jsonify({'success': True, 'message': 'vpay_pending_checker 线程已重启'})

        elif thread_name == 'stock_pulse':
            if stock_pulse_thread is not None and stock_pulse_thread.is_alive():
                system_logger.info(f"[重启] stock_pulse 线程仍在运行(疑似心跳误报)，无需重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})

            from analysis.stock_pulse import stock_pulse_loop
            stock_pulse_thread = threading.Thread(target=stock_pulse_loop, daemon=True)
            stock_pulse_thread.start()
            system_logger.info(f"[重启] stock_pulse 线程已重新启动")
            return jsonify({'success': True, 'message': 'stock_pulse 线程已重启'})

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
                from analysis.anomaly_detector import build_baseline
                build_baseline()
                system_logger.info("异动检测基线预热完成")
            except Exception as _e:
                system_logger.warning(f"异动基线预热失败: {_e}")
        threading.Thread(target=_preload_anomaly_baseline, daemon=True).start()

        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()
        system_logger.info("监控线程已启动")

        from monitors.stock_price_monitor import stock_price_loop
        threading.Thread(target=stock_price_loop, daemon=True).start()
        system_logger.info("价格异动监控线程已启动")

        # 个股异动监控:盘中每5分钟采样全A涨跌幅,检测板块聚集/涨停/大幅拉升跳水(analysis/stock_pulse.py)
        from analysis.stock_pulse import stock_pulse_loop
        stock_pulse_thread = threading.Thread(target=stock_pulse_loop, daemon=True)
        stock_pulse_thread.start()
        system_logger.info("个股异动监控线程已启动")

        # TrendZen 套利背离告警接入:轮询 feed → 微信推送 → 入库 → ack 回执闭环
        from monitors.trendzen_arb_monitor import trendzen_arb_loop
        trendzen_arb_thread = threading.Thread(target=trendzen_arb_loop, daemon=True)
        trendzen_arb_thread.start()
        system_logger.info("TrendZen套利背离接入线程已启动")

        # 量化扫描信号桥:水位线轮询 quant /scan/feed → 入库 → 统一总线 push_event('tz_signal')
        from monitors.quant_signal_bridge import quant_signal_bridge_loop
        quant_signal_thread = threading.Thread(target=quant_signal_bridge_loop, daemon=True)
        quant_signal_thread.start()
        system_logger.info("量化扫描信号桥线程已启动")

        # 重大事件日历预热:启动即拉百度/ForexFactory,之后每30分钟刷新(宏观层面,归首页后端)
        from data.event_calendar import event_calendar_loop
        threading.Thread(target=event_calendar_loop, daemon=True).start()
        system_logger.info("重大事件日历预热线程已启动")

        # 演示模式快照:每个交易日收盘后固化首页+云图数据,未登录访客只读这份快照
        from data.demo_snapshot import demo_snapshot_loop
        threading.Thread(target=demo_snapshot_loop, daemon=True).start()
        system_logger.info("演示快照线程已启动")

        # 虚拟支付兜底查单线程:每5分钟扫描 pending 订单,推送丢失时补发货
        from routes.mp_vpay_routes import vpay_check_loop
        vpay_checker_thread = threading.Thread(target=vpay_check_loop, daemon=True)
        vpay_checker_thread.start()
        system_logger.info("虚拟支付兜底查单线程已启动")

        system_logger.info("Flask-SocketIO服务器启动")
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
        
    except KeyboardInterrupt:
        system_logger.info("服务器正在关闭...")
    except Exception as e:
        error_logger.error(f"服务器启动失败: {e}")
