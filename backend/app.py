from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import multiprocessing
import os
import ssl
import socket
from datetime import datetime

from config import DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR
from data_processor import error_logger, system_logger
from data_collector import data_collection_thread as data_collection_func
from news_collector import news_collection_thread as news_collection_func, init_news_data
from routes import flow_bp, news_bp, config_bp, log_bp
from thread_monitor import get_all_status, register_thread
from monitor import monitor_loop

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
    
    app.register_blueprint(flow_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(log_bp)
    
    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            'status': 'ok',
            'threads': get_all_status()
        })
    
    @app.route('/api/system/ssl-status', methods=['GET'])
    def ssl_status():
        try:
            cert_path = '/etc/letsencrypt/live/0vk.top/fullchain.pem'
            
            if not os.path.exists(cert_path):
                return jsonify({
                    'success': True,
                    'data': {
                        'enabled': False,
                        'message': 'SSL证书未配置'
                    }
                })
            
            context = ssl.create_default_context()
            with socket.create_connection(('0vk.top', 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname='0vk.top') as ssock:
                    cert = ssock.getpeercert()
            
            not_after = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            days_remaining = (not_after - datetime.utcnow()).days
            
            issuer = dict(x[0] for x in cert['issuer'])
            
            return jsonify({
                'success': True,
                'data': {
                    'enabled': True,
                    'domain': '0vk.top',
                    'issuer': issuer.get('organizationName', 'Unknown'),
                    'valid_from': cert['notBefore'],
                    'valid_to': cert['notAfter'],
                    'days_remaining': days_remaining,
                    'is_valid': days_remaining > 0,
                    'message': f'证书有效，剩余 {days_remaining} 天' if days_remaining > 0 else '证书已过期'
                }
            })
        except Exception as e:
            return jsonify({
                'success': True,
                'data': {
                    'enabled': False,
                    'message': f'SSL检测失败: {str(e)}'
                }
            })
    
    @app.route('/api/system/restart', methods=['POST'])
    def restart_thread():
        global data_collection_thread, news_collection_thread
        
        data = request.get_json() or {}
        thread_name = data.get('thread', '')
        
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
            system_logger.info("数据采集线程已启动")
        
        if not news_collection_thread.is_alive():
            news_collection_thread.start()
            system_logger.info("新闻采集线程已启动")
        
        monitor_process = multiprocessing.Process(target=monitor_loop, daemon=True)
        monitor_process.start()
        system_logger.info("监控进程已启动")
        
        system_logger.info("Flask服务器启动")
        app.run(host='0.0.0.0', port=5000, debug=False)
        
    except KeyboardInterrupt:
        system_logger.info("服务器正在关闭...")
    except Exception as e:
        error_logger.error(f"服务器启动失败: {e}")
