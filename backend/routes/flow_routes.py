from flask import Blueprint, jsonify, request
from datetime import datetime
from config import DAILY_DIR, REALTIME_DIR
from data_processor import (
    get_sector_flow_data, load_recent_daily_data, load_recent_realtime_data,
    load_recent_daily_data_with_accumulation, latest_data, load_daily_data, error_logger
)

flow_bp = Blueprint('flow', __name__, url_prefix='/api/flow')

@flow_bp.route('/current', methods=['GET'])
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

@flow_bp.route('/history', methods=['GET'])
def get_history():
    try:
        days = request.args.get('days', '7', type=int)
        days = min(days, 30)
        
        history = load_recent_daily_data_with_accumulation(days)
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_daily_record = load_daily_data(today)
        today_last_data = get_sector_flow_data()
        
        if today_daily_record and 'data' in today_daily_record:
            if today not in history:
                history[today] = []
            for i, item in enumerate(today_daily_record['data']):
                history[today].append({
                    'rank': i + 1,
                    'name': item.get('name', ''),
                    'flow': item.get('flow', 0),
                    'change': item.get('change', 0),
                    'total_flow': item.get('flow', 0),
                    'accumulated_change_percent': item.get('change', 0),
                    'appearances': 1
                })
        elif today_last_data:
            if today not in history:
                history[today] = []
            for i, item in enumerate(today_last_data[:10]):
                history[today].append({
                    'rank': i + 1,
                    'name': item.get('name', ''),
                    'flow': item.get('flow', 0),
                    'change': item.get('change', 0),
                    'total_flow': item.get('flow', 0),
                    'accumulated_change_percent': item.get('change', 0),
                    'appearances': 1
                })
        
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

@flow_bp.route('/minute', methods=['GET'])
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
