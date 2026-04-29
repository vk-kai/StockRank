from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import traceback
import requests
import json
import urllib3
from config import DAILY_DIR, REALTIME_DIR
from data_processor import (
    get_sector_flow_data, load_recent_daily_data, load_recent_realtime_data,
    load_recent_daily_data_with_accumulation, latest_data, load_daily_data, 
    load_realtime_data, error_logger, get_market_overview, get_accumulated_top_sectors,
    get_top5_comparison_data, get_random_user_agent
)
from data_collector import is_trading_day, is_trading_time, is_morning_close, is_afternoon_close
from logger import get_logger

flow_bp = Blueprint('flow', __name__, url_prefix='/api/flow')
system_logger = get_logger('system')

SECTOR_STOCKS_URL = "https://push2.eastmoney.com/api/qt/clist/get"

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
        
        today_data = load_daily_data(date_str)
        if not today_data or 'data' not in today_data:
            return jsonify({
                'success': False,
                'message': f'未找到{date_str}的数据，请确保当天有数据采集'
            }), 404
        
        comparison_data = get_top5_comparison_data(date_str)
        if not comparison_data:
            comparison_data = {
                'date': date_str,
                'time': datetime.now().strftime('%H:%M'),
                'top5': []
            }
        
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
def get_sector_stocks():
    sector = request.args.get('sector', '')
    sector_code = ''
    
    if sector:
        for item in latest_data:
            if item.get('name') == sector:
                sector_code = item.get('code', '')
                break
        
        if not sector_code:
            return jsonify({
                'success': False,
                'message': f'未找到板块 "{sector}" 对应的代码'
            }), 400
    
    if not sector_code:
        return jsonify({
            'success': False,
            'message': '板块代码不能为空，请传递sector参数'
        }), 400
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://data.eastmoney.com/',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    }
    
    params = {
        'fid': 'f62',
        'po': '1',
        'pz': '50',
        'pn': '1',
        'np': '1',
        'fltt': '2',
        'invt': '2',
        'ut': '8dec03ba335b81bf4ebdf7b29ec27d15',
        'fs': f'b:{sector_code}',
        'fields': 'f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124,f1,f13'
    }
    
    max_retries = 3
    last_error = None
    data = None
    
    from urllib.parse import urlencode
    
    full_url = f"{SECTOR_STOCKS_URL}?{urlencode(params)}"
    
    try:
        response = requests.get(SECTOR_STOCKS_URL, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
        else:
            last_error = f'HTTP状态码错误: {response.status_code}'
    except requests.exceptions.RequestException as e:
        last_error = f'请求错误: {str(e)}'
    except Exception as e:
        last_error = f'请求异常: {str(e)}'
    
    if data is None:
        # 临时返回请求URL
        import urllib.parse
        system_logger.error(f"API错误 [/api/flow/sector-stocks]: 获取板块 {sector_code} 个股数据失败 - {last_error}")
        return jsonify({
            'success': False,
            'message': f'获取数据失败: {last_error}',
            'request_url': full_url  # 临时添加
        }), 500
    
    stocks = []
    try:
        if 'data' in data and 'diff' in data['data']:
            for item in data['data']['diff']:
                code = item.get('f12', '')
                name = item.get('f14', '')
                price = item.get('f2', 0)
                change_percent = item.get('f3', 0)
                main_flow = item.get('f62', 0)
                main_flow_ratio = item.get('f184', 0)
                super_flow = item.get('f66', 0)
                super_ratio = item.get('f69', 0)
                big_flow = item.get('f72', 0)
                big_ratio = item.get('f75', 0)
                mid_flow = item.get('f78', 0)
                mid_ratio = item.get('f81', 0)
                small_flow = item.get('f84', 0)
                small_ratio = item.get('f87', 0)
                
                if price == '-' or price is None:
                    price = 0
                if change_percent == '-' or change_percent is None:
                    change_percent = 0
                if main_flow == '-' or main_flow is None:
                    main_flow = 0
                if main_flow_ratio == '-' or main_flow_ratio is None:
                    main_flow_ratio = 0
                
                market = 'SH' if item.get('f13') == 1 else 'SZ'
                
                stocks.append({
                    'code': code,
                    'name': name,
                    'market': market,
                    'price': float(price) if price else 0,
                    'change_percent': float(change_percent) / 100 if change_percent else 0,
                    'main_flow': float(main_flow) if main_flow else 0,
                    'main_flow_ratio': float(main_flow_ratio) if main_flow_ratio else 0,
                    'super_flow': float(super_flow) if super_flow else 0,
                    'super_ratio': float(super_ratio) if super_ratio else 0,
                    'big_flow': float(big_flow) if big_flow else 0,
                    'big_ratio': float(big_ratio) if big_ratio else 0,
                    'mid_flow': float(mid_flow) if mid_flow else 0,
                    'mid_ratio': float(mid_ratio) if mid_ratio else 0,
                    'small_flow': float(small_flow) if small_flow else 0,
                    'small_ratio': float(small_ratio) if small_ratio else 0,
                })
        
        stocks.sort(key=lambda x: x['main_flow'], reverse=True)
        
        # 临时返回请求的URL
        import urllib.parse
        full_url = f"{SECTOR_STOCKS_URL}?{urllib.parse.urlencode(params)}"
        
        return jsonify({
            'success': True,
            'data': {
                'sector_name': sector,
                'sector_code': sector_code,
                'stocks': stocks,
                'total': len(stocks),
                'request_url': full_url  # 临时添加
            },
            'timestamp': datetime.now().astimezone().isoformat()
        })
        
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/sector-stocks]: 解析板块 {sector_code} 数据失败 - {str(e)}")
        return jsonify({
            'success': False,
            'message': f'解析数据失败: {str(e)}'
        }), 500

@flow_bp.route('/test-network', methods=['GET'])
def test_network():
    from urllib.parse import urlencode
    
    test_url = "https://push2.eastmoney.com/api/qt/clist/get"
    test_params = {
        'fid': 'f62',
        'po': '1',
        'pz': '5',
        'pn': '1',
        'np': '1',
        'fltt': '2',
        'invt': '2',
        'ut': '8dec03ba335b81bf4ebdf7b29ec27d15',
        'fs': 'b:BK1033',
        'fields': 'f12,f14,f2,f3,f62'
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/',
    }
    
    results = {
        'test_url': f"{test_url}?{urlencode(test_params)}",
        'tests': []
    }
    
    # 测试1: urllib3方式
    try:
        http = urllib3.PoolManager(
            retries=urllib3.Retry(total=3, backoff_factor=0.5),
            timeout=urllib3.Timeout(connect=10.0, read=10.0)
        )
        full_url = f"{test_url}?{urlencode(test_params)}"
        response = http.request('GET', full_url, headers=headers)
        http.clear()
        
        results['tests'].append({
            'method': 'urllib3',
            'status': 'success',
            'status_code': response.status,
            'data_length': len(response.data)
        })
    except Exception as e:
        results['tests'].append({
            'method': 'urllib3',
            'status': 'failed',
            'error': str(e)
        })
    
    # 测试2: requests方式
    try:
        response = requests.get(test_url, params=test_params, headers=headers, timeout=10, verify=False)
        results['tests'].append({
            'method': 'requests.get',
            'status': 'success',
            'status_code': response.status_code,
            'response_time': response.elapsed.total_seconds()
        })
    except Exception as e:
        results['tests'].append({
            'method': 'requests.get',
            'status': 'failed',
            'error': str(e)
        })
    
    return jsonify(results)
