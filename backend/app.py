from flask import Flask, jsonify, request
from flask_cors import CORS
from config import DATA_DIR, DAILY_DIR, REALTIME_DIR, LOG_DIR
from data_processor import (
    get_sector_flow_data, load_recent_daily_data, load_recent_realtime_data, 
    latest_data, generate_daily_summary, load_daily_data, error_logger, data_logger, system_logger
)
from data_collector import data_collection_thread
import threading
from datetime import datetime

app = Flask(__name__)
CORS(app)

# API路由
@app.route('/api/flow/current', methods=['GET'])
def get_current_flow():
    try:
        if not latest_data:
            data = get_sector_flow_data()
        else:
            data = latest_data
        
        return jsonify({
            'success': True,
            'data': data,
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/current 异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@app.route('/api/flow/history', methods=['GET'])
def get_history():
    try:
        days = request.args.get('days', '7', type=int)
        days = min(days, 30)
        
        # 加载历史每日数据（已完成的交易日）
        history = load_recent_daily_data(days)
        print(history)
        # 检查今天的数据
        today = datetime.now().strftime('%Y-%m-%d')
        today_daily_record = load_daily_data(today)
        today_last_data=get_sector_flow_data()
        # 如果今天已有每日数据（交易日已结束），使用每日数据
        if today_daily_record and 'data' in today_daily_record:
            history[today] = today_daily_record['data']
        # 如果今天没有每日数据（交易进行中），使用实时数据
        elif today_last_data:
            history[today] = today_last_data[:10]
        
        return jsonify({
            'success': True,
            'data': history
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/history 异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@app.route('/api/flow/minute', methods=['GET'])
def get_minute_data():
    try:
        hours = request.args.get('hours', '24', type=int)
        hours = min(hours, 24)
        
        minute_data = load_recent_realtime_data(hours)
        
        return jsonify({
            'success': True,
            'data': minute_data
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/minute 异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    try:
        system_logger.info("启动A股资金流入服务...")
        
        # 获取最新板块资金流入数据
        system_logger.info("获取最新板块资金流入数据...")
        initial_data = get_sector_flow_data()
        if initial_data:
            today = datetime.now().strftime('%Y-%m-%d')
            current_minute = datetime.now().strftime('%H:%M')
            from data_processor import save_realtime_data
            success = save_realtime_data(today, current_minute, initial_data)
            if success:
                system_logger.info(f"已获取 {len(initial_data)} 个板块的数据")
            else:
                system_logger.error("保存初始数据失败")
        
        # 启动数据采集线程
        collection_thread = threading.Thread(target=data_collection_thread, daemon=True)
        collection_thread.start()
        
        # 启动Flask服务
        system_logger.info("启动Flask服务...")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        error_logger.error(f"服务启动失败: {e}")
        raise
