from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import traceback
import requests
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

SECTOR_CODE_MAP = {
    '电力行业': 'BK0428',
    '光伏设备': 'BK0415',
    '汽车整车': 'BK0488',
    '化学制药': 'BK0440',
    '电池': 'BK1033',
    '锂电池': 'BK1033',
    '小金属': 'BK0556',
    '医疗器械': 'BK0444',
    '半导体': 'BK0872',
    '电子元件': 'BK0722',
    '软件开发': 'BK0733',
    '互联网服务': 'BK0734',
    '通信设备': 'BK0730',
    '消费电子': 'BK0822',
    '光学光电子': 'BK0821',
    '汽车零部件': 'BK0489',
    '专用设备': 'BK0438',
    '通用设备': 'BK0437',
    '有色金属': 'BK0478',
    '钢铁行业': 'BK0421',
    '煤炭行业': 'BK0430',
    '石油行业': 'BK0431',
    '化学制品': 'BK0442',
    '化肥行业': 'BK0443',
    '农药兽药': 'BK0444',
    '塑料橡胶': 'BK0445',
    '玻璃玻纤': 'BK0446',
    '水泥建材': 'BK0447',
    '装修建材': 'BK0448',
    '房地产': 'BK0451',
    '银行': 'BK0473',
    '保险': 'BK0474',
    '证券': 'BK0475',
    '多元金融': 'BK0476',
    '航空航天': 'BK0435',
    '船舶制造': 'BK0436',
    '仪器仪表': 'BK0439',
    '电机': 'BK0441',
    '电网设备': 'BK0449',
    '风电设备': 'BK0450',
    '燃气': 'BK0452',
    '水务': 'BK0453',
    '环保行业': 'BK0454',
    '工程建设': 'BK0455',
    '工程咨询': 'BK0456',
    '专业服务': 'BK0457',
    '旅游酒店': 'BK0458',
    '航空机场': 'BK0459',
    '港口航运': 'BK0460',
    '物流行业': 'BK0461',
    '商业百货': 'BK0462',
    '贸易行业': 'BK0463',
    '酿酒行业': 'BK0470',
    '食品饮料': 'BK0468',
    '农牧饲渔': 'BK0469',
    '中药': 'BK0471',
    '生物制品': 'BK0472',
    '医疗美容': 'BK0477',
    '教育': 'BK0464',
    '文化传媒': 'BK0465',
    '游戏': 'BK0466',
    '家电行业': 'BK0467',
}

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
    sector_code = request.args.get('code', '')
    
    if not sector and not sector_code:
        return jsonify({
            'success': False,
            'message': '板块名称或代码不能为空'
        }), 400
    
    if sector_code:
        pass
    elif sector.startswith('BK'):
        sector_code = sector
    else:
        sector_code = SECTOR_CODE_MAP.get(sector)
        if not sector_code:
            return jsonify({
                'success': False,
                'message': f'未找到板块 {sector} 的代码映射'
            }), 404
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://data.eastmoney.com/',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
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
    
    for attempt in range(max_retries):
        try:
            response = requests.get(SECTOR_STOCKS_URL, params=params, headers=headers, timeout=15)
            data = response.json()
            break
        except requests.exceptions.ConnectionError as e:
            last_error = f'网络连接错误: {str(e)}'
            if attempt < max_retries - 1:
                import time
                time.sleep(1)
                continue
        except requests.exceptions.Timeout as e:
            last_error = f'请求超时: {str(e)}'
            if attempt < max_retries - 1:
                import time
                time.sleep(1)
                continue
        except Exception as e:
            last_error = f'请求异常: {str(e)}'
            break
    else:
        # 临时返回请求URL
        import urllib.parse
        full_url = f"{SECTOR_STOCKS_URL}?{urllib.parse.urlencode(params)}"
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
