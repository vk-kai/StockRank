from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import traceback
import requests
import json
import urllib3
from config import DAILY_DIR, REALTIME_DIR, is_dev_mode
from data_processor import (
    get_sector_flow_data, load_recent_daily_data, load_recent_realtime_data,
    load_recent_daily_data_with_accumulation, load_daily_data, 
    load_realtime_data, error_logger, get_market_overview, get_accumulated_top_sectors,
    get_top5_comparison_data, get_random_user_agent
)
import data_processor
from data_collector import is_trading_day, is_trading_time, is_morning_close, is_afternoon_close
from logger import get_logger

flow_bp = Blueprint('flow', __name__, url_prefix='/api/flow')
system_logger = get_logger('system')

SECTOR_STOCKS_URL = "https://push2.eastmoney.com/api/qt/clist/get"

MOCK_SECTORS = [
    {'rank': 1, 'name': '电池', 'flow': 152463.67, 'change': 0.04, 'code': 'BK1033'},
    {'rank': 2, 'name': '小金属', 'flow': 89234.56, 'change': 0.02, 'code': 'BK1027'},
    {'rank': 3, 'name': '能源金属', 'flow': 67890.12, 'change': 0.03, 'code': 'BK1015'},
    {'rank': 4, 'name': '乘用车', 'flow': 56789.34, 'change': -0.01, 'code': 'BK1262'},
    {'rank': 5, 'name': '光伏设备', 'flow': 45678.90, 'change': 0.05, 'code': 'BK1031'},
    {'rank': 6, 'name': '工业金属', 'flow': 34567.89, 'change': 0.01, 'code': 'BK1287'},
    {'rank': 7, 'name': '玻璃玻纤', 'flow': 23456.78, 'change': -0.02, 'code': 'BK0546'},
    {'rank': 8, 'name': '其他电源设备', 'flow': 12345.67, 'change': 0.03, 'code': 'BK1034'},
    {'rank': 9, 'name': '电网设备', 'flow': 9876.54, 'change': 0.01, 'code': 'BK0457'},
    {'rank': 10, 'name': '塑料', 'flow': 8765.43, 'change': -0.01, 'code': 'BK0454'},
]

MOCK_STOCKS = [
    {'code': '300750', 'name': '宁德时代', 'market': 'SZ', 'price': 445.0, 'change_percent': 0.04, 'main_flow': 1524636672, 'main_flow_ratio': 0.15},
    {'code': '002709', 'name': '天赐材料', 'market': 'SZ', 'price': 59.32, 'change_percent': 0.10, 'main_flow': 1252487728, 'main_flow_ratio': 0.12},
    {'code': '300014', 'name': '亿纬锂能', 'market': 'SZ', 'price': 74.1, 'change_percent': 0.05, 'main_flow': 633076016, 'main_flow_ratio': 0.08},
    {'code': '300390', 'name': '天华新能', 'market': 'SZ', 'price': 110.5, 'change_percent': 0.19, 'main_flow': 526194944, 'main_flow_ratio': 0.06},
    {'code': '002340', 'name': '格林美', 'market': 'SZ', 'price': 9.64, 'change_percent': 0.08, 'main_flow': 472792832, 'main_flow_ratio': 0.05},
]

SECTOR_DATA_URL = "https://push2.eastmoney.com/api/qt/clist/get"

def fetch_sector_code_from_api(sector_name):
    params = {
        'pn': 1,
        'pz': 200,
        'po': 1,
        'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2,
        'invt': 2,
        'fid': 'f62',
        'fs': 'm:90+s:4',
        'fields': 'f12,f14'
    }
    
    try:
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Cookie': 'qgqp_b_id=9849bf5ba6a612557a93f8f340e0b20a; st_nvi=X0SuRmE-CSfugODoeQ9Ha5c08; st_pvi=00084442657277; st_sp=2025-08-17%2023%3A35%3A44; st_inirUrl=https%3A%2F%2Fcn.bing.com%2F',
            'Referer': 'https://data.eastmoney.com/',
            'sec-ch-ua': '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
        }
        response = requests.get(SECTOR_DATA_URL, params=params, headers=headers, timeout=10)
        data = response.json()
        
        if 'data' in data and 'diff' in data['data']:
            for item in data['data']['diff']:
                name = item.get('f14', '')
                if name == sector_name:
                    return item.get('f12', '')
    except Exception as e:
        error_logger.error(f"获取板块代码失败: {e}")
    
    return ''

@flow_bp.route('/current', methods=['GET'])
def get_current_flow():
    try:
        if is_dev_mode():
            return jsonify({
                'success': True,
                'data': MOCK_SECTORS,
                'timestamp': datetime.now().astimezone().isoformat(),
                'message': 'DEV模式 - Mock数据'
            })
        
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
                if data_processor.latest_data:
                    return jsonify({
                        'success': True,
                        'data': data_processor.latest_data,
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
        
        if not data_processor.latest_data:
            data = get_sector_flow_data()
        else:
            data = data_processor.latest_data
        
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

@flow_bp.route('/mock-sectors', methods=['GET'])
def get_mock_sectors():
    return jsonify({
        'success': True,
        'data': MOCK_SECTORS,
        'message': 'MOCK板块数据，用于开发调试'
    })

@flow_bp.route('/sector-stocks', methods=['GET'])
def get_sector_stocks():
    sector = request.args.get('sector', '')
    sector_code = request.args.get('code', '')
    
    if not sector_code and sector:
        for item in data_processor.latest_data:
            if item.get('name') == sector:
                sector_code = item.get('code', '')
                break
        
        if not sector_code:
            sector_code = fetch_sector_code_from_api(sector)
    
    if not sector_code:
        available_names = [item.get('name') for item in data_processor.latest_data[:10]] if data_processor.latest_data else []
        return jsonify({
            'success': False,
            'message': f'未找到板块 "{sector}" 对应的代码',
            'available_sectors': available_names
        }), 400
    
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
    
    last_error = None
    data = None
    
    from urllib.parse import urlencode
    from data_processor import get_random_user_agent
    
    full_url = f"{SECTOR_STOCKS_URL}?{urlencode(params)}"
    
    for attempt in range(3):
        try:
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Accept-Language': 'zh-CN,zh;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6',
                'Cache-Control': 'max-age=0',
                'Connection': 'keep-alive',
                'Cookie': 'qgqp_b_id=9849bf5ba6a612557a93f8f340e0b20a; st_nvi=X0SuRmE-CSfugODoeQ9Ha5c08; st_pvi=00084442657277; st_sp=2025-08-17%2023%3A35%3A44; st_inirUrl=https%3A%2F%2Fcn.bing.com%2F',
                'Referer': 'https://data.eastmoney.com/',
                'sec-ch-ua': '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
            }
            response = requests.get(SECTOR_STOCKS_URL, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                break
            else:
                last_error = f'HTTP状态码错误: {response.status_code}'
        except requests.exceptions.RequestException as e:
            last_error = f'请求错误: {str(e)}'
            import time
            time.sleep(1)
        except Exception as e:
            last_error = f'请求异常: {str(e)}'
    
    if data is None:
        system_logger.error(f"API错误 [/api/flow/sector-stocks]: 获取板块 {sector_code} 个股数据失败 - {last_error}")
        return jsonify({
            'success': False,
            'message': f'获取数据失败: {last_error}',
            'request_url': full_url
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
        
        return jsonify({
            'success': True,
            'data': {
                'stocks': stocks,
                'total': len(stocks)
            },
            'timestamp': datetime.now().astimezone().isoformat()
        })
        
    except Exception as e:
        system_logger.error(f"API错误 [/api/flow/sector-stocks]: 解析板块 {sector_code} 数据失败 - {str(e)}")
        return jsonify({
            'success': False,
            'message': f'解析数据失败: {str(e)}'
        }), 500

