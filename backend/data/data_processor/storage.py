"""数据存储与日报聚合（从 data_processor._legacy 拆分）。

G3 文件IO(daily/realtime 读写、推送状态、过期清理) + G4 日报聚合(每日汇总、近 N 日/小时加载、
累计 top 板块) + G9 TOP5 对比。自洽：仅依赖 core.config 目录常量 + _common logger + 标准库，
不调用其它子模块（market_index 不依赖 storage，故无反向 import）。
"""
import os
import json
from datetime import datetime, timedelta

from core.config import DAILY_DIR, REALTIME_DIR, MAX_DAYS
from ._common import error_logger, data_logger, data_summary_logger


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
