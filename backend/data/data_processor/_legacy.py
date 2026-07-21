import requests
import json
import re
from datetime import datetime, timedelta
import os
import random
import string
import hashlib
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from bs4 import BeautifulSoup
from core.config import DAILY_DIR, REALTIME_DIR, MAX_DAYS, DATA_URL, THS_SECTOR_URL, THS_SECTOR_NET_IN_URL, THS_SECTOR_NET_OUT_URL, USE_PROXY, get_random_user_agent, get_eastmoney_headers, em_request
from ._common import (
    error_logger, data_logger, system_logger, data_summary_logger,
    _safe_float, _parse_ths_number, _parse_ths_int,
    _parse_json_or_jsonp, _last_list_value, _last_dict_value, _pick_first_number,
    MARKET_INDEX_URL, GLOBAL_INDICES_CACHE_FILE,
)
from .ths_client import generate_random_headers, attach_fresh_ths_cookie

# 获取每日数据文件路径
def get_daily_file_path(date_str):
    return os.path.join(DAILY_DIR, f'{date_str}.json')

# 获取实时数据文件路径（按日期）
def get_realtime_file_path(date_str):
    return os.path.join(REALTIME_DIR, f'{date_str}.json')

# 加载指定日期的每日数据
def load_daily_data(date_str):
    file_path = get_daily_file_path(date_str)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            error_logger.error(f"加载每日数据失败 ({date_str}): {e}")
            return None
    return None

# 保存每日数据
def save_daily_data(date_str, data):
    file_path = get_daily_file_path(date_str)
    try:
        existing_data = load_daily_data(date_str) or {}
        push_status = existing_data.get('push_status', {
            'morning_pushed': False,
            'morning_push_time': None,
            'afternoon_pushed': False,
            'afternoon_push_time': None
        })
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                'date': date_str,
                'timestamp': datetime.now().isoformat(),
                'data': data,
                'push_status': push_status
            }, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        error_logger.error(f"保存每日数据失败 ({date_str}): {e}")
        return False

def update_push_status(date_str, period):
    file_path = get_daily_file_path(date_str)
    try:
        daily_data = load_daily_data(date_str)
        if not daily_data:
            error_logger.error(f"更新推送状态失败：找不到每日数据文件 ({date_str})")
            return False
        
        if 'push_status' not in daily_data:
            daily_data['push_status'] = {
                'morning_pushed': False,
                'morning_push_time': None,
                'afternoon_pushed': False,
                'afternoon_push_time': None
            }
        
        now = datetime.now().isoformat()
        if period == '上午':
            daily_data['push_status']['morning_pushed'] = True
            daily_data['push_status']['morning_push_time'] = now
        elif period == '下午':
            daily_data['push_status']['afternoon_pushed'] = True
            daily_data['push_status']['afternoon_push_time'] = now
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(daily_data, f, ensure_ascii=False, indent=2)
        
        data_logger.info(f"已更新 {date_str} {period}推送状态")
        return True
    except Exception as e:
        error_logger.error(f"更新推送状态失败 ({date_str}): {e}")
        return False

def is_pushed(date_str, period):
    daily_data = load_daily_data(date_str)
    if not daily_data:
        return False
    
    push_status = daily_data.get('push_status', {})
    
    if period == '上午':
        return push_status.get('morning_pushed', False)
    elif period == '下午':
        return push_status.get('afternoon_pushed', False)
    
    return False

# 加载指定日期的实时数据
def load_realtime_data(date_str):
    file_path = get_realtime_file_path(date_str)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    error_logger.warning(f"实时数据文件为空 ({date_str})")
                    return {'_invalid': True, '_reason': 'empty'}
                return json.loads(content)
        except json.JSONDecodeError as e:
            error_logger.error(f"实时数据文件不是有效JSON ({date_str}): {e}")
            return {'_invalid': True, '_reason': 'invalid_json'}
        except Exception as e:
            error_logger.error(f"加载实时数据失败 ({date_str}): {e}")
            return {'_invalid': True, '_reason': 'error'}
    return {}

# 保存实时数据（追加模式）
def save_realtime_data(date_str, minute_key, data):
    file_path = get_realtime_file_path(date_str)
    try:
        realtime_data = load_realtime_data(date_str)
        
        if realtime_data.get('_invalid'):
            realtime_data = {}
        
        realtime_data[minute_key] = {
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(realtime_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        error_logger.error(f"保存实时数据失败 ({date_str}): {e}")
        return False

# 清理过期数据（超过30天的数据）
def cleanup_old_data():
    result = {
        'cleaned': False,
        'daily_deleted': 0,
        'realtime_deleted': 0,
        'freed_bytes': 0,
        'reason': ''
    }
    
    try:
        cutoff_date = (datetime.now() - timedelta(days=MAX_DAYS)).strftime('%Y-%m-%d')
        
        deleted_daily = 0
        deleted_realtime = 0
        freed_bytes = 0
        
        for filename in os.listdir(DAILY_DIR):
            if filename.endswith('.json'):
                date_str = filename.replace('.json', '')
                if date_str < cutoff_date:
                    file_path = os.path.join(DAILY_DIR, filename)
                    try:
                        file_size = os.path.getsize(file_path)
                        os.remove(file_path)
                        deleted_daily += 1
                        freed_bytes += file_size
                    except Exception as e:
                        error_logger.error(f"删除每日数据文件失败 ({filename}): {e}")
        
        for filename in os.listdir(REALTIME_DIR):
            if filename.endswith('.json'):
                date_str = filename.replace('.json', '')
                if date_str < cutoff_date:
                    file_path = os.path.join(REALTIME_DIR, filename)
                    try:
                        file_size = os.path.getsize(file_path)
                        os.remove(file_path)
                        deleted_realtime += 1
                        freed_bytes += file_size
                    except Exception as e:
                        error_logger.error(f"删除实时数据文件失败 ({filename}): {e}")
        
        if deleted_daily > 0 or deleted_realtime > 0:
            result['cleaned'] = True
            result['daily_deleted'] = deleted_daily
            result['realtime_deleted'] = deleted_realtime
            result['freed_bytes'] = freed_bytes
        else:
            result['reason'] = f"当前所有数据文件均在 {MAX_DAYS} 天保留期内"
        
        return result
    except Exception as e:
        error_logger.error(f"清理过期数据失败: {e}")
        result['reason'] = f"清理失败: {str(e)}"
        return result

# 生成当天的每日数据（取最强的10个板块）
def generate_daily_summary():
    today = datetime.now().strftime('%Y-%m-%d')
    realtime_data = load_realtime_data(today)
    
    if not realtime_data:
        data_summary_logger.info(f"当天({today})没有实时数据，无法生成每日汇总")
        return False
    
    try:
        # 获取当天的最后一个时间点的数据
        last_minute = max(realtime_data.keys())
        last_data = realtime_data[last_minute]['data']
        
        # 按最后一次采集到的资金流入排序
        sorted_sectors = sorted(last_data, key=lambda x: x['flow'] if x['flow'] else 0, reverse=True)
        top_10 = sorted_sectors[:10]
        
        # 构建当天的代表数据
        representative_data = []
        for i, item in enumerate(top_10):
            representative_data.append({
                'rank': i + 1,
                'name': item['name'],
                'flow': item['flow'],
                'net_flow': item.get('net_flow', 0),
                'change': item['change']
            })
        
        if representative_data:
            success = save_daily_data(today, representative_data)
            if success:
                data_summary_logger.info(f"已生成并保存当天({today})的每日汇总数据，共{len(representative_data)}个板块")
                return True
            else:
                data_summary_logger.error(f"保存当天({today})的每日汇总数据失败")
                return False
        else:
            data_summary_logger.error(f"无法构建当天({today})的每日汇总数据")
            return False
    except Exception as e:
        error_logger.error(f"生成每日汇总数据失败 ({today}): {e}")
        return False

# 为指定日期生成每日汇总
def generate_daily_summary_for_date(date_str):
    realtime_data = load_realtime_data(date_str)
    
    if not realtime_data:
        data_summary_logger.info(f"日期({date_str})没有实时数据")
        return False
    
    try:
        # 获取当天的最后一个时间点的数据
        last_minute = max(realtime_data.keys())
        last_data = realtime_data[last_minute]['data']
        
        # 按最后一次采集到的资金流入排序
        sorted_sectors = sorted(last_data, key=lambda x: x['flow'] if x['flow'] else 0, reverse=True)
        top_10 = sorted_sectors[:10]
        
        # 构建当天的代表数据
        representative_data = []
        for i, item in enumerate(top_10):
            representative_data.append({
                'rank': i + 1,
                'name': item['name'],
                'flow': item['flow'],
                'net_flow': item.get('net_flow', 0),
                'change': item['change']
            })
        
        if representative_data:
            success = save_daily_data(date_str, representative_data)
            if success:
                data_summary_logger.info(f"已生成并保存日期({date_str})的每日汇总数据，共{len(representative_data)}个板块")
                return True
            else:
                data_summary_logger.error(f"保存日期({date_str})的每日汇总数据失败")
                return False
        else:
            data_summary_logger.error(f"无法构建日期({date_str})的每日汇总数据")
            return False
    except Exception as e:
        error_logger.error(f"生成日期({date_str})的每日汇总失败: {e}")
        return False

# 加载最近N天的每日数据
def _build_daily_summary_from_latest_realtime(date_str):
    realtime_data = load_realtime_data(date_str)
    if not realtime_data or realtime_data.get('_invalid'):
        return None

    time_keys = sorted([key for key in realtime_data.keys() if not key.startswith('_')])
    if not time_keys:
        return None

    latest_record = realtime_data.get(time_keys[-1])
    latest_data = latest_record.get('data') if isinstance(latest_record, dict) else None
    if not isinstance(latest_data, list):
        return None

    sorted_sectors = sorted(
        latest_data,
        key=lambda item: item.get('flow', 0) or 0,
        reverse=True
    )

    summary = []
    for index, item in enumerate(sorted_sectors[:10]):
        summary.append({
            'rank': index + 1,
            'name': item.get('name', ''),
            'flow': item.get('flow', 0) or 0,
            'net_flow': item.get('net_flow', 0) or 0,
            'change': item.get('change', 0) or 0
        })

    return summary or None

def load_recent_daily_data(days):
    try:
        result = {}
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        for filename in os.listdir(DAILY_DIR):
            if filename.endswith('.json'):
                date_str = filename.replace('.json', '')
                if date_str >= cutoff_date:
                    daily_record = load_daily_data(date_str)
                    if daily_record and 'data' in daily_record:
                        result[date_str] = daily_record['data']
        
        today = datetime.now().strftime('%Y-%m-%d')
        if today >= cutoff_date:
            today_summary = _build_daily_summary_from_latest_realtime(today)
            if today_summary:
                result[today] = today_summary
        
        return result
    except Exception as e:
        error_logger.error(f"加载最近每日数据失败: {e}")
        return {}

def load_recent_daily_data_with_accumulation(days):
    try:
        raw_data = load_recent_daily_data(days)
        
        if not raw_data:
            return {}
        
        sector_stats = {}
        
        dates_sorted = sorted(raw_data.keys())
        
        for date_str in dates_sorted:
            daily_data = raw_data[date_str]
            if not isinstance(daily_data, list):
                continue
            
            for item in daily_data:
                sector_name = item.get('name')
                if not sector_name:
                    continue
                
                if sector_name not in sector_stats:
                    sector_stats[sector_name] = {
                        'name': sector_name,
                        'total_flow': 0,
                        'accumulated_change': 1.0,
                        'appearances': 0,
                        'daily_records': []
                    }
                
                flow = item.get('flow', 0) or 0
                change = item.get('change', 0) or 0
                
                sector_stats[sector_name]['total_flow'] += flow
                sector_stats[sector_name]['accumulated_change'] *= (1 + change)
                sector_stats[sector_name]['appearances'] += 1
                sector_stats[sector_name]['daily_records'].append({
                    'date': date_str,
                    'flow': flow,
                    'change': change
                })
        
        for sector_name, stats in sector_stats.items():
            stats['accumulated_change_percent'] = stats['accumulated_change'] - 1
        
        sorted_sectors = sorted(
            sector_stats.values(),
            key=lambda x: x['total_flow'],
            reverse=True
        )
        
        result = {}
        for i, sector in enumerate(sorted_sectors):
            for record in sector['daily_records']:
                date_str = record['date']
                if date_str not in result:
                    result[date_str] = []
                
                result[date_str].append({
                    'rank': i + 1,
                    'name': sector['name'],
                    'flow': record['flow'],
                    'change': record['change'],
                    'total_flow': sector['total_flow'],
                    'accumulated_change_percent': sector['accumulated_change_percent'],
                    'appearances': sector['appearances']
                })
            
            result[date_str].sort(key=lambda x: x['rank'])
        
        return result
    except Exception as e:
        error_logger.error(f"加载累计每日数据失败: {e}")
        return {}

def get_accumulated_top_sectors(days):
    try:
        raw_data = load_recent_daily_data(days)
        
        if not raw_data:
            return []
        
        sector_stats = {}
        
        for date_str, daily_data in raw_data.items():
            if not isinstance(daily_data, list):
                continue
            
            for item in daily_data:
                sector_name = item.get('name')
                if not sector_name:
                    continue
                
                if sector_name not in sector_stats:
                    sector_stats[sector_name] = {
                        'name': sector_name,
                        'total_flow': 0,
                        'accumulated_change': 1.0,
                        'appearances': 0
                    }
                
                flow = item.get('flow', 0) or 0
                change = item.get('change', 0) or 0
                
                sector_stats[sector_name]['total_flow'] += flow
                sector_stats[sector_name]['accumulated_change'] *= (1 + change)
                sector_stats[sector_name]['appearances'] += 1
        
        for sector_name, stats in sector_stats.items():
            stats['accumulated_change_percent'] = stats['accumulated_change'] - 1
        
        sorted_sectors = sorted(
            sector_stats.values(),
            key=lambda x: x['total_flow'],
            reverse=True
        )
        
        top_sectors = []
        for i, sector in enumerate(sorted_sectors[:10]):
            top_sectors.append({
                'rank': i + 1,
                'name': sector['name'],
                'flow': sector['total_flow'],
                'change': sector['accumulated_change_percent'],
                'total_flow': sector['total_flow'],
                'accumulated_change_percent': sector['accumulated_change_percent'],
                'appearances': sector['appearances']
            })
        
        return top_sectors
    except Exception as e:
        error_logger.error(f"获取累计流入TOP板块失败: {e}")
        return []

# 加载最近N小时的实时数据
def load_recent_realtime_data(hours):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        realtime_data = load_realtime_data(today)
        
        if realtime_data.get('_invalid'):
            return {}
        
        result = {}
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        for minute_key, record in realtime_data.items():
            if minute_key.startswith('_'):
                continue
            time_str = f"{today} {minute_key}"
            try:
                record_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                if record_time >= cutoff_time:
                    result[minute_key] = record
            except Exception as e:
                error_logger.error(f"解析时间失败 ({time_str}): {e}")
                continue
        
        return result
    except Exception as e:
        error_logger.error(f"加载最近实时数据失败: {e}")
        return {}

SINA_INDEX_URL = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006"
STOCK_STAT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
THS_INDEX_FLASH_URL = "https://q.10jqka.com.cn/api.php?t=indexflash&"
THS_TURNOVER_MINUTE_URL = "https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data"
JRJ_MARKET_URL = "https://gateway.jrj.com/quot-dc/zdt/market"

latest_market_data = {}
MARKET_SUMMARY_CACHE_FILE = os.path.join(REALTIME_DIR, 'market_summary.json')
MARKET_FAST_REFRESH_SECONDS = 15
MARKET_TURNOVER_REFRESH_SECONDS = 60


def get_eastmoney_market_index_data():
    global latest_market_data
    
    headers = get_eastmoney_headers()
    
    params = {
        'fltt': 2,
        'invt': 2,
        'fields': 'f1,f2,f3,f4,f12,f13,f14',
        'secids': '1.000001,0.399001,0.399006'
    }
    
    try:
        response = em_request(MARKET_INDEX_URL, params=params, headers=headers, timeout=10)
        if response is None:
            raise Exception("东方财富大盘指数请求失败(直连+代理均不可达)")
        response.raise_for_status()
        data = response.json()

        if 'data' in data and 'diff' in data['data']:
            indices = {}
            for item in data['data']['diff']:
                code = item.get('f12', '')
                name = item.get('f14', '')
                price = item.get('f2', 0)
                change = item.get('f3', 0)
                change_amount = item.get('f4', 0)
                
                if price == '-' or price is None:
                    price = 0
                if change == '-' or change is None:
                    change = 0
                if change_amount == '-' or change_amount is None:
                    change_amount = 0
                
                indices[code] = {
                    'code': code,
                    'name': name,
                    'price': float(price) if price else 0,
                    'change': float(change) / 100 if change else 0,
                    'change_amount': float(change_amount) if change_amount else 0
                }
            
            latest_market_data['indices'] = indices
            return indices
        else:
            error_logger.warning(f"东方财富大盘指数数据格式异常: {data}")
    except Exception as e:
        error_logger.warning(f"东方财富大盘指数数据获取失败: {e}")
    
    return None

def get_sina_market_index_data():
    global latest_market_data

    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    code_map = {
        'sh000001': '000001',
        'sz399001': '399001',
        'sz399006': '399006'
    }

    try:
        response = requests.get(SINA_INDEX_URL, headers=headers, timeout=10)
        response.encoding = 'gbk'
        indices = {}

        for part in response.text.split(';'):
            if 'hq_str_' not in part or '="' not in part:
                continue
            raw_code = part.split('hq_str_', 1)[1].split('=', 1)[0]
            code = code_map.get(raw_code)
            if not code:
                continue
            values_text = part.split('="', 1)[1].rstrip('"')
            values = values_text.split(',')
            if len(values) < 4 or not values[0]:
                continue

            name = values[0]
            prev_close = _safe_float(values[2], None)
            price = _safe_float(values[3], None)
            if price in (None, 0) or prev_close in (None, 0):
                continue

            change_amount = price - prev_close
            indices[code] = {
                'code': code,
                'name': name,
                'price': round(price, 2),
                'change': change_amount / prev_close,
                'change_amount': round(change_amount, 2)
            }

        if indices:
            latest_market_data['indices'] = indices
            return indices
        error_logger.warning(f"新浪大盘指数数据格式异常: {response.text[:300]}")
    except Exception as e:
        error_logger.warning(f"新浪大盘指数数据获取失败，准备使用东方财富兜底: {e}")

    return None

def get_market_index_data():
    indices = get_sina_market_index_data()
    if indices:
        return indices

    indices = get_eastmoney_market_index_data()
    if indices:
        return indices

    error_logger.error("大盘指数数据获取失败：新浪与东方财富均不可用")
    return None

# 全球主要股市指数配置：(名称, 东方财富secid, 新浪兜底代码, 纬度, 经度, 国家/地区)
# 注意：同一国家多个指数经纬度需错开，避免地图标签重叠
GLOBAL_INDICES_CONFIG = [
    ('上证指数', '1.000001', 'sh000001', 31.23, 121.47, '中国'),
    ('沪深300', '1.000300', None, 39.90, 116.40, '中国'),
    ('恒生指数', '100.HSI', 'int_hangseng', 22.32, 114.17, '香港'),
    ('台湾加权', '100.TWII', None, 25.03, 121.57, '台湾'),
    ('日经225', '100.N225', 'int_nikkei', 35.68, 139.69, '日本'),
    ('韩国KOSPI', '100.KS11', 'b_KOSPI', 37.57, 126.98, '韩国'),
    ('富时马来西亚', '100.KLSE', None, 3.14, 101.69, '马来西亚'),
    ('印尼综合', '100.JKSE', None, -6.21, 106.85, '印尼'),
    ('越南胡志明', '100.VNINDEX', None, 10.78, 106.70, '越南'),
    ('印度SENSEX', '100.SENSEX', 'b_SENSEX', 19.08, 72.88, '印度'),
    ('澳大利亚ASX200', '100.AS51', None, -33.87, 151.21, '澳大利亚'),
    ('道琼斯', '100.DJIA', 'int_dji', 38.90, -77.04, '美国'),
    ('纳斯达克', '100.NDX', 'int_nasdaq', 40.71, -74.01, '美国'),
    ('标普500', '100.SPX', 'int_sp500', 41.80, -87.65, '美国'),
    ('巴西BOVESPA', '100.BVSP', 'int_bovespa', -23.55, -46.63, '巴西'),
    ('英国富时100', '100.FTSE', 'int_ftse', 51.51, -0.13, '英国'),
    ('德国DAX30', '100.GDAXI', None, 50.11, 8.68, '德国'),
    ('法国CAC40', '100.FCHI', None, 48.86, 2.35, '法国'),
    ('荷兰AEX', '100.AEX', None, 52.37, 4.90, '荷兰'),
    ('瑞士SMI', '100.SSMI', None, 47.37, 8.54, '瑞士'),
    ('俄罗斯RTS', '100.RTS', None, 55.75, 37.62, '俄罗斯'),
]


def get_global_market_indices():
    """获取全球主要股市指数（双源：东方财富为主，新浪兜底）"""
    secids = ','.join(cfg[1] for cfg in GLOBAL_INDICES_CONFIG)
    headers = get_eastmoney_headers()
    params = {
        'fltt': 2,
        'invt': 2,
        'fields': 'f2,f3,f4,f12,f14',
        'secids': secids
    }

    result = {}
    em_ok = False
    try:
        response = em_request(MARKET_INDEX_URL, params=params, headers=headers, timeout=10)
        if response is not None:
            response.raise_for_status()
            data = response.json()
            diff = data.get('data', {}).get('diff', []) if data.get('data') else []
        em_map = {item.get('f12'): item for item in diff}
        for cfg in GLOBAL_INDICES_CONFIG:
            name, secid, sina_code, lat, lng, region = cfg
            em_code = secid.split('.')[-1]
            item = em_map.get(em_code)
            if item and item.get('f2') not in ('-', None):
                result[secid] = {
                    'name': name,
                    'code': secid,
                    'price': float(item.get('f2', 0) or 0),
                    'change': float(item.get('f3', 0) or 0) / 100,
                    'change_amount': float(item.get('f4', 0) or 0),
                    'lat': lat,
                    'lng': lng,
                    'region': region,
                    'source': 'eastmoney'
                }
                em_ok = True
    except Exception as e:
        error_logger.warning(f"东方财富全球指数获取失败，尝试新浪兜底: {e}")

    # 新浪兜底：补齐东方财富未取到的指数
    sina_needed = [cfg for cfg in GLOBAL_INDICES_CONFIG if cfg[2] and cfg[1] not in result]
    if sina_needed:
        try:
            sina_codes = ','.join(cfg[2] for cfg in sina_needed)
            s_headers = {
                'User-Agent': get_random_user_agent(),
                'Referer': 'https://finance.sina.com.cn/'
            }
            s_resp = requests.get("https://hq.sinajs.cn/list=" + sina_codes, headers=s_headers, timeout=10)
            s_resp.encoding = 'gbk'
            for part in s_resp.text.split(';'):
                if 'hq_str_' not in part or '="' not in part:
                    continue
                key = part.split('hq_str_', 1)[1].split('=', 1)[0]
                values_text = part.split('="', 1)[1].rstrip('"')
                values = values_text.split(',')
                if len(values) < 4:
                    continue
                price = None
                change = None
                change_amount = None
                if key.startswith(('sh', 'sz')):
                    # 国内指数(34字段格式)：[2]=昨收 [3]=现价
                    prev_close = _safe_float(values[2], None)
                    p = _safe_float(values[3], None)
                    if p is not None and prev_close not in (None, 0):
                        price = p
                        change_amount = p - prev_close
                        change = change_amount / prev_close
                else:
                    # 国际指数(int_/b_，4字段格式)：[1]=现价 [2]=涨跌额 [3]=涨跌幅%
                    if not values[1]:
                        continue
                    p = _safe_float(values[1], None)
                    cp = _safe_float(values[3], None)
                    if p is not None and cp is not None:
                        price = p
                        change = cp / 100
                        change_amount = p * cp / 100
                if price is None:
                    continue
                for cfg in sina_needed:
                    if cfg[2] == key and cfg[1] not in result:
                        name, secid, _, lat, lng, region = cfg
                        result[secid] = {
                            'name': name,
                            'code': secid,
                            'price': round(price, 2),
                            'change': change,
                            'change_amount': round(change_amount or 0, 2),
                            'lat': lat,
                            'lng': lng,
                            'region': region,
                            'source': 'sina'
                        }
                        break
        except Exception as e:
            error_logger.warning(f"新浪全球指数兜底获取失败: {e}")

    # 兜底缓存：东方财富/新浪偶发缺失某指数时(如韩国KOSPI非其交易时段返回'-')，
    # 用本地"上次成功值"补齐，保证全球地图所有国家始终显示。本次实时值同步刷新缓存。
    try:
        cache = {}
        if os.path.exists(GLOBAL_INDICES_CACHE_FILE):
            with open(GLOBAL_INDICES_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        for cfg in GLOBAL_INDICES_CONFIG:
            secid = cfg[1]
            if secid not in result and secid in cache:
                v = dict(cache[secid])
                v['stale'] = True      # 标记为兜底旧值（非本次实时）
                result[secid] = v
        fresh = {secid: v for secid, v in result.items() if not v.get('stale')}
        if fresh:
            cache.update(fresh)
            with open(GLOBAL_INDICES_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        error_logger.warning(f"全球指数缓存读写失败: {e}")

    if not result:
        error_logger.error("全球指数数据获取失败：东方财富与新浪均不可用")
        return None

    indices = list(result.values())
    indices.sort(key=lambda x: x.get('change', 0), reverse=True)
    return {
        'indices': indices,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'eastmoney' if em_ok else 'sina'
    }


def get_stock_statistics():
    global latest_market_data
    
    headers = get_eastmoney_headers()
    
    params = {
        'pn': 1,
        'pz': 5000,
        'po': 1,
        'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2,
        'invt': 2,
        'fid': 'f3',
        'fs': 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23',
        'fields': 'f1,f2,f3,f12,f13,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87'
    }
    
    try:
        response = em_request(STOCK_STAT_URL, params=params, headers=headers, timeout=10)
        if response is None:
            raise Exception("东方财富个股统计请求失败(直连+代理均不可达)")
        data = response.json()
        
        if 'data' in data and 'diff' in data['data']:
            up_count = 0
            down_count = 0
            flat_count = 0
            total_volume = 0
            limit_up_count = 0
            limit_down_count = 0
            
            for item in data['data']['diff']:
                change = item.get('f3', 0)
                if change == '-' or change is None:
                    change = 0
                else:
                    change = float(change) / 100
                
                if change > 0.095:
                    limit_up_count += 1
                    up_count += 1
                elif change < -0.095:
                    limit_down_count += 1
                    down_count += 1
                elif change > 0:
                    up_count += 1
                elif change < 0:
                    down_count += 1
                else:
                    flat_count += 1
                
                volume = item.get('f184', 0)
                if volume and volume != '-':
                    total_volume += float(volume)
            
            stats = {
                'up_count': up_count,
                'down_count': down_count,
                'flat_count': flat_count,
                'limit_up_count': limit_up_count,
                'limit_down_count': limit_down_count,
                'total_count': up_count + down_count + flat_count,
                'total_volume': total_volume
            }
            
            latest_market_data['stats'] = stats
            return stats
        else:
            error_logger.error(f"获取股票统计数据格式异常: {data}")
    except Exception as e:
        error_logger.error(f"获取股票统计数据失败: {e}")
    
    return None

def get_market_overview():
    indices = get_market_index_data()
    stats = get_stock_statistics()
    
    if indices and stats:
        return {
            'indices': indices,
            'stats': stats,
            'timestamp': datetime.now().isoformat()
        }
    
    return None

def get_ths_market_breadth():
    headers = generate_random_headers(
        host='q.10jqka.com.cn',
        referer='https://q.10jqka.com.cn/'
    )
    headers.update({
        'Accept': 'application/json, text/plain, */*',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'X-Requested-With': 'XMLHttpRequest'
    })
    headers = attach_fresh_ths_cookie(headers)

    try:
        response = requests.get(THS_INDEX_FLASH_URL, headers=headers, timeout=10)
        if response.status_code in (401, 403):
            headers = attach_fresh_ths_cookie(headers)
            response = requests.get(THS_INDEX_FLASH_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = _parse_json_or_jsonp(response.text)
        if not isinstance(data, dict):
            error_logger.error(f"同花顺涨跌家数数据格式异常: {response.text[:300]}")
            return None

        zdfb_data = data.get('zdfb_data') if isinstance(data.get('zdfb_data'), dict) else data
        zdt_data = data.get('zdt_data') if isinstance(data.get('zdt_data'), dict) else data
        limit_up = _last_dict_value(zdt_data, 'ztzs')
        limit_down = _last_dict_value(zdt_data, 'dtzs')

        return {
            'index_point': _pick_first_number(data, ['point', 'zs', 'zsz', 'dpzs', 'shzs', 'shindex', 'index']),
            'up_count': int(_safe_float(zdfb_data.get('znum'), 0)),
            'down_count': int(_safe_float(zdfb_data.get('dnum'), 0)),
            'limit_up_count': int(_safe_float(_last_list_value(limit_up), 0)),
            'limit_down_count': int(_safe_float(_last_list_value(limit_down), 0)),
            'source': 'ths',
            'raw_keys': list(data.keys())
        }
    except Exception as e:
        error_logger.error(f"获取同花顺涨跌家数失败: {e}")
        return None

def get_ths_turnover_summary():
    headers = generate_random_headers(
        host='dq.10jqka.com.cn',
        referer='https://dq.10jqka.com.cn/'
    )
    headers.update({
        'Accept': 'application/json, text/plain, */*',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin'
    })
    headers = attach_fresh_ths_cookie(headers)

    try:
        response = requests.get(
            THS_TURNOVER_MINUTE_URL,
            params={'chart_key': 'turnover_minute'},
            headers=headers,
            timeout=10
        )
        if response.status_code in (401, 403):
            headers = attach_fresh_ths_cookie(headers)
            response = requests.get(
                THS_TURNOVER_MINUTE_URL,
                params={'chart_key': 'turnover_minute'},
                headers=headers,
                timeout=10
            )
        response.raise_for_status()
        data = response.json()
        chart = data.get('data', {}).get('charts', {})
        header = chart.get('header', [])
        header_map = {
            item.get('key'): item.get('val')
            for item in header
            if isinstance(item, dict)
        }

        return {
            'turnover': _safe_float(header_map.get('turnover'), None),
            'turnover_pre': _safe_float(header_map.get('turnover_pre'), None),
            'turnover_change': _safe_float(header_map.get('turnover_change'), None),
            'predict_turnover': _safe_float(header_map.get('predict_turnover'), None),
            'mtime': chart.get('mtime'),
            'source': 'ths'
        }
    except Exception as e:
        error_logger.error(f"获取同花顺成交额数据失败: {e}")
        return None

def get_jrj_market_breadth():
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin': 'https://summary.jrj.com.cn',
        'Referer': 'https://summary.jrj.com.cn/',
        'User-Agent': get_random_user_agent(),
        'productId': '6000021'
    }

    try:
        response = requests.post(JRJ_MARKET_URL, headers=headers, json={}, timeout=10)
        response.raise_for_status()
        data = response.json()
        stock = data.get('data', {}).get('stock', {})
        if data.get('code') != 20000 or not isinstance(stock, dict):
            error_logger.error(f"金融界涨跌停数据格式异常: {data}")
            return None

        return {
            'up_count': int(_safe_float(stock.get('up'), 0)),
            'down_count': int(_safe_float(stock.get('down'), 0)),
            'limit_up_count': int(_safe_float(stock.get('zt'), 0)),
            'limit_down_count': int(_safe_float(stock.get('dt'), 0)),
            'flat_count': int(_safe_float(stock.get('zero'), 0)),
            'total_count': int(_safe_float(stock.get('total'), 0)),
            'stopped_count': int(_safe_float(stock.get('stopped'), 0)),
            'source': 'jrj'
        }
    except Exception as e:
        error_logger.error(f"获取金融界涨跌停家数失败: {e}")
        return None

def get_market_summary():
    cached_summary = latest_market_data.get('summary')
    if not cached_summary and os.path.exists(MARKET_SUMMARY_CACHE_FILE):
        try:
            with open(MARKET_SUMMARY_CACHE_FILE, 'r', encoding='utf-8') as f:
                cached_summary = json.load(f)
        except Exception:
            cached_summary = None

    breadth = get_jrj_market_breadth() or get_ths_market_breadth()
    turnover = get_ths_turnover_summary()
    indices = get_market_index_data()
    if not indices and isinstance(cached_summary, dict):
        indices = cached_summary.get('indices')
    main_index = indices.get('000001') if isinstance(indices, dict) else None
    if not main_index and isinstance(cached_summary, dict):
        main_index = cached_summary.get('main_index')

    summary = {
        'breadth': breadth,
        'turnover': turnover,
        'indices': indices,
        'main_index': main_index,
        'timestamp': datetime.now().astimezone().isoformat()
    }
    latest_market_data['summary'] = summary
    return summary

def get_market_fast_summary():
    cached_summary = load_market_summary_cache() or {}
    breadth = get_jrj_market_breadth() or get_ths_market_breadth() or cached_summary.get('breadth')
    indices = get_market_index_data() or cached_summary.get('indices')
    main_index = indices.get('000001') if isinstance(indices, dict) else cached_summary.get('main_index')

    summary = {
        'breadth': breadth,
        'turnover': cached_summary.get('turnover'),
        'indices': indices,
        'main_index': main_index,
        'timestamp': datetime.now().astimezone().isoformat(),
        'turnover_timestamp': cached_summary.get('turnover_timestamp') or cached_summary.get('timestamp')
    }
    latest_market_data['summary'] = summary
    save_market_summary_cache(summary)
    return summary

def should_refresh_market_turnover(summary):
    if not isinstance(summary, dict) or not summary.get('turnover'):
        return True
    timestamp_text = summary.get('turnover_timestamp') or summary.get('timestamp')
    if not timestamp_text:
        return True
    try:
        timestamp = datetime.fromisoformat(timestamp_text)
        return (datetime.now().astimezone() - timestamp).total_seconds() >= MARKET_TURNOVER_REFRESH_SECONDS
    except Exception:
        return True

def refresh_market_summary_cache(fast_only=False):
    cached_summary = load_market_summary_cache() or {}
    summary = get_market_fast_summary()

    if not fast_only and should_refresh_market_turnover(cached_summary):
        turnover = get_ths_turnover_summary()
        if turnover:
            summary['turnover'] = turnover
            summary['turnover_timestamp'] = datetime.now().astimezone().isoformat()
            latest_market_data['summary'] = summary
            save_market_summary_cache(summary)

    return summary

def save_market_summary_cache(summary):
    try:
        os.makedirs(os.path.dirname(MARKET_SUMMARY_CACHE_FILE), exist_ok=True)
        with open(MARKET_SUMMARY_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        error_logger.error(f"保存首页大盘摘要缓存失败: {e}")
        return False

def load_market_summary_cache():
    if latest_market_data.get('summary'):
        return latest_market_data.get('summary')

    try:
        if not os.path.exists(MARKET_SUMMARY_CACHE_FILE):
            return None
        with open(MARKET_SUMMARY_CACHE_FILE, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        latest_market_data['summary'] = summary
        return summary
    except Exception as e:
        error_logger.error(f"读取首页大盘摘要缓存失败: {e}")
        return None

def is_market_summary_complete(summary):
    if not isinstance(summary, dict):
        return False
    indices = summary.get('indices')
    indices_complete = isinstance(indices, dict) and all(
        isinstance(indices.get(code), dict) and _safe_float(indices[code].get('price'), None) is not None
        for code in ('000001', '399001', '399006')
    )
    breadth = summary.get('breadth')
    breadth_complete = isinstance(breadth, dict) and all(
        _safe_float(breadth.get(key), None) is not None
        for key in ('up_count', 'down_count', 'limit_up_count', 'limit_down_count')
    )
    turnover = summary.get('turnover')
    turnover_complete = isinstance(turnover, dict) and _safe_float(turnover.get('turnover'), None) is not None
    return indices_complete and breadth_complete and turnover_complete


def get_top5_comparison_data(date_str):
    try:
        today_data = load_daily_data(date_str)
        if not today_data or 'data' not in today_data:
            return None
        
        today_sectors = today_data['data']
        if not today_sectors:
            return None
        
        yesterday = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_data = load_daily_data(yesterday)
        yesterday_sectors = yesterday_data.get('data', []) if yesterday_data else []
        
        yesterday_dict = {item['name']: item for item in yesterday_sectors}
        
        top5 = today_sectors[:5]
        
        comparison_data = []
        for i, today_item in enumerate(top5):
            sector_name = today_item['name']
            today_flow = today_item.get('flow', 0)
            today_change = today_item.get('change', 0)
            
            yesterday_item = yesterday_dict.get(sector_name)
            
            if yesterday_item:
                yesterday_flow = yesterday_item.get('flow', 0)
                yesterday_change = yesterday_item.get('change', 0)
                
                if yesterday_flow != 0:
                    flow_change_percent = ((today_flow - yesterday_flow) / abs(yesterday_flow)) * 100
                else:
                    flow_change_percent = 100 if today_flow > 0 else 0
                
                if today_flow > yesterday_flow:
                    strength = '增强'
                elif today_flow < yesterday_flow:
                    strength = '减弱'
                else:
                    strength = '持平'
            else:
                yesterday_flow = None
                yesterday_change = None
                flow_change_percent = None
                strength = '新增'
            
            comparison_data.append({
                'rank': i + 1,
                'name': sector_name,
                'today_flow': today_flow,
                'today_change': today_change,
                'yesterday_flow': yesterday_flow,
                'yesterday_change': yesterday_change,
                'flow_change_percent': flow_change_percent,
                'strength': strength
            })
        
        return {
            'date': date_str,
            'time': datetime.now().strftime('%H:%M'),
            'top5': comparison_data
        }
    except Exception as e:
        error_logger.error(f"获取TOP5对比数据失败: {e}")
        return None
