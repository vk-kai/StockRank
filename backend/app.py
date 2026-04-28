from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR
from data_processor import error_logger, system_logger
from data_collector import data_collection_thread as data_collection_func
from news_collector import news_collection_thread as news_collection_func, init_news_data
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
        'data_dir': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'jarvis'),
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
    
    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            'status': 'ok',
            'threads': get_all_status()
        })
    
    @app.route('/api/system/restart', methods=['POST', 'OPTIONS'])
    def restart_thread():
        if request.method == 'OPTIONS':
            return jsonify({'success': True})
        
        global data_collection_thread, news_collection_thread
        
        data = request.get_json() or {}
        thread_name = data.get('thread', '')
        
        system_logger.info(f"[重启] 收到重启请求: {thread_name}")
        
        if thread_name == 'data_collector':
            if data_collection_thread.is_alive():
                system_logger.warning("[重启] 数据采集线程仍在运行，跳过重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})
            
            data_collection_thread = threading.Thread(target=data_collection_func, daemon=True)
            data_collection_thread.start()
            register_thread('data_collector')
            system_logger.info("[重启] 数据采集线程已重启")
            return jsonify({'success': True, 'message': '数据采集线程已重启'})
        
        elif thread_name == 'news_collector':
            if news_collection_thread.is_alive():
                system_logger.warning("[重启] 新闻采集线程仍在运行，跳过重启")
                return jsonify({'success': True, 'message': '线程仍在运行'})
            
            news_collection_thread = threading.Thread(target=news_collection_func, daemon=True)
            news_collection_thread.start()
            register_thread('news_collector')
            system_logger.info("[重启] 新闻采集线程已重启")
            return jsonify({'success': True, 'message': '新闻采集线程已重启'})
        
        return jsonify({'success': False, 'message': f'未知线程: {thread_name}'}), 400
    
    return app

app = create_app()

if __name__ == '__main__':
    try:
        for directory in [DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR]:
            os.makedirs(directory, exist_ok=True)
        
        init_news_data()
        
        if not data_collection_thread.is_alive():
            data_collection_thread.start()
        
        if not news_collection_thread.is_alive():
            news_collection_thread.start()
        
        monitor_process = multiprocessing.Process(target=monitor_loop, daemon=True)
        monitor_process.start()
        system_logger.info("监控进程已启动")
        
        system_logger.info("Flask服务器启动")
        app.run(host='0.0.0.0', port=5000, debug=False)
        
    except KeyboardInterrupt:
        system_logger.info("服务器正在关闭...")
    except Exception as e:
        error_logger.error(f"服务器启动失败: {e}")
