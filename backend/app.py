from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import threading
import multiprocessing
import os
import traceback

from config import DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR
from data_processor import error_logger, system_logger
from data_collector import data_collection_thread as data_collection_func
from news_collector import news_collection_thread as news_collection_func, init_news_data
from health_checker import get_health_status, load_health_status, get_crawler_status, load_crawler_status, start_health_checker
from routes import flow_bp, news_bp, config_bp, log_bp, house_bp
from thread_monitor import get_all_status, register_thread
from monitor import monitor_loop
from Jarvis import SecurityMiddleware
from Jarvis.middleware import create_security_blueprint
from Jarvis.config import get_config as get_jarvis_config

data_collection_thread = threading.Thread(target=data_collection_func, daemon=True)
news_collection_thread = threading.Thread(target=news_collection_func, daemon=True)

def create_app():
    app = Flask(__name__)
    
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
    
    app.register_blueprint(flow_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(log_bp)
    app.register_blueprint(house_bp)
    
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
        
        global data_collection_thread, news_collection_thread
        
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
        
        else:
            return jsonify({'success': False, 'message': f'未知的线程名称: {thread_name}'}), 400
    
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
        
        # 启动时自动执行健康检测（获取可用请求头 + 启动定时检测）
        start_health_checker()
        system_logger.info("健康检测已启动")
        
        monitor_process = multiprocessing.Process(target=monitor_loop, daemon=True)
        monitor_process.start()
        system_logger.info("监控进程已启动")
        
        system_logger.info("Flask服务器启动")
        app.run(host='0.0.0.0', port=5000, debug=False)
        
    except KeyboardInterrupt:
        system_logger.info("服务器正在关闭...")
    except Exception as e:
        error_logger.error(f"服务器启动失败: {e}")
