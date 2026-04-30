from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import traceback
from config import DAILY_DIR, REALTIME_DIR
from data_processor import (
    get_sector_flow_data, load_recent_daily_data, load_recent_realtime_data,
    load_recent_daily_data_with_accumulation, latest_data, load_daily_data, 
    load_realtime_data, error_logger, get_market_overview, get_accumulated_top_sectors,
    get_top5_comparison_data, get_sector_stocks
)
from data_collector import is_trading_day, is_trading_time, is_morning_close, is_afternoon_close
from logger import get_logger

flow_bp = Blueprint('flow', __name__, url_prefix='/api/flow')
system_logger = get_logger('system')

@flow_bp.route('/current', methods=['GET'])
def get_current_flow():
    try:
        now = datetime.now().astimezone()
        
        if not is_trading_day(now) or not is_trading_time(now):
            today = datetime.now().strftime('%Y-%m-%d')
            
            if is_afternoon_close(now):
                today_daily_record = load_daily_data(today)
                if today_daily_record and 'data' in today_daily_record:
                    return jsonify({
                        'success': True,
                        'data': today_daily_record['data'],
                        'timestamp': today_daily_record.get('timestamp', datetime.now().astimezone().isoformat()),
                        'message': '下午收盘后，返回今日每日汇总数据'
                    })
                
                realtime_data = load_realtime_data(today)
                if realtime_data:
                    time_keys = sorted(realtime_data.keys(), reverse=True)
                    if time_keys:
                        last_time_key = time_keys[0]
                        last_record = realtime_data[last_time_key]
                        if last_record and 'data' in last_record:
                            return jsonify({
                                'success': True,
                                'data': last_record['data'],
                                'timestamp': last_record.get('timestamp', datetime.now().astimezone().isoformat()),
                                'message': f'下午收盘后，返回今日最新数据({last_time_key})'
                            })
            
            elif is_morning_close(now):
                today_daily_record = load_daily_data(today)
                if today_daily_record and 'data' in today_daily_record:
                    return jsonify({
                        'success': True,
                        'data': today_daily_record['data'],
                        'timestamp': today_daily_record.get('timestamp', datetime.now().astimezone().isoformat()),
                        'message': '上午收盘后，返回今日上午汇总数据'
                    })
                
                realtime_data = load_realtime_data(today)
                if realtime_data:
                    time_keys = sorted(realtime_data.keys(), reverse=True)
                    if time_keys:
                        last_time_key = time_keys[0]
                        last_record = realtime_data[last_time_key]
                        if last_record and 'data' in last_record:
                            return jsonify({
                                'success': True,
                                'data': last_record['data'],
                                'timestamp': last_record.get('timestamp', datetime.now().astimezone().isoformat()),
                                'message': f'上午收盘后，返回今日上午数据({last_time_key})'
                            })
            
            else:
                if latest_data:
                    return jsonify({
                        'success': True,
                        'data': latest_data,
                        'timestamp': datetime.now().astimezone().isoformat(),
                        'message': '非交易时间，返回缓存数据'
                    })
            
            recent_history = load_recent_daily_data(7)
            if recent_history:
                dates_sorted = sorted(recent_history.keys(), reverse=True)
                if dates_sorted:
                    latest_date = dates_sorted[0]
                    latest_record = recent_history[latest_date]
                    if latest_record and isinstance(latest_record, list) and len(latest_record) > 0:
                        return jsonify({
                            'success': True,
                            'data': latest_record,
                            'timestamp': datetime.now().astimezone().isoformat(),
                            'message': f'非交易时间，返回最近历史数据({latest_date})'
                        })
            
            return jsonify({
                'success': True,
                'data': [],
                'timestamp': datetime.now().astimezone().isoformat(),
                'message': '非交易时间，暂无数据'
            })
        
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
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/current]: {str(e)}")
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
        
        now = datetime.now().astimezone()
        if is_trading_day(now) and is_trading_time(now):
            today_last_data = get_sector_flow_data()
        else:
            today_last_data = None
        
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
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/history]: {str(e)}")
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
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/minute]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/market', methods=['GET'])
def get_market():
    try:
        market_data = get_market_overview()
        
        if market_data:
            return jsonify({
                'success': True,
                'data': market_data,
                'timestamp': datetime.now().astimezone().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'message': '获取大盘数据失败'
            }), 500
    except Exception as e:
        error_logger.error(f"API /api/flow/market 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/market]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/accumulated', methods=['GET'])
def get_accumulated_flow():
    try:
        days = request.args.get('days', '7', type=int)
        days = min(days, 30)
        
        top_sectors = get_accumulated_top_sectors(days)
        
        return jsonify({
            'success': True,
            'data': top_sectors,
            'days': days,
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/accumulated 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/accumulated]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/daily-report', methods=['GET'])
def get_daily_report():
    try:
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        # 获取当日数据
        today_data = load_daily_data(date_str)
        if not today_data or 'data' not in today_data:
            return jsonify({
                'success': False,
                'message': f'未找到{date_str}的数据'
            }), 404
        
        # 获取TOP5对比数据
        comparison_data = get_top5_comparison_data(date_str)
        
        # 获取昨日数据用于对比
        yesterday = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_data = load_daily_data(yesterday)
        
        return jsonify({
            'success': True,
            'data': {
                'date': date_str,
                'today': today_data['data'],
                'comparison': comparison_data,
                'yesterday_exists': yesterday_data is not None
            },
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/flow/daily-report 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/daily-report]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@flow_bp.route('/sector-stocks', methods=['GET'])
def get_sector_stocks_api():
    try:
        sector_url = request.args.get('url', '')
        
        if not sector_url:
            return jsonify({
                'success': False,
                'message': '缺少板块URL参数'
            }), 400
        
        stocks = get_sector_stocks(sector_url)
        
        if stocks:
            return jsonify({
                'success': True,
                'data': stocks,
                'timestamp': datetime.now().astimezone().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'message': '获取个股数据失败'
            }), 500
    except Exception as e:
        error_logger.error(f"API /api/flow/sector-stocks 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/flow/sector-stocks]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
