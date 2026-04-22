import requests
import json
from datetime import datetime, timedelta
import os
from config import DAILY_DIR, REALTIME_DIR, MAX_DAYS, DATA_URL, get_random_user_agent
from logger import get_logger

error_logger = get_logger('error')
data_logger = get_logger('data')
system_logger = get_logger('system')
cleanup_logger = get_logger('cleanup_flow')

# 全局变量存储最新数据
latest_data = []

def get_sector_flow_data():
    headers = {
        'User-Agent': get_random_user_agent()
    }
    
    params = {
        'pn': 1,
        'pz': 100,
        'po': 1,
        'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2,
        'invt': 2,
        'fid': 'f62',
        'fs': 'm:90+t:2',
        'fields': 'f1,f2,f3,f12,f13,f14,f62,f66,f69,f72,f75,f78,f81,f84,f87,f124,f184,f204,f205,f206'
    }
    
    try:
        response = requests.get(DATA_URL, params=params, headers=headers, timeout=10)
        data = response.json()
        
        if 'data' in data and 'diff' in data['data']:
            sectors = []
            for item in data['data']['diff']:
                sector_name = item.get('f14', '')
                
                try:
                    f62_value = item.get('f62', 0)
                    if f62_value == '-' or f62_value is None:
                        net_inflow = 0
                    else:
                        net_inflow = float(f62_value) / 10000
                    
                    f3_value = item.get('f3', 0)
                    if f3_value == '-' or f3_value is None:
                        change = 0
                    else:
                        change = float(f3_value) / 100
                except (ValueError, TypeError) as e:
                    error_logger.warning(f"数据类型转换失败: {item}, 错误: {e}")
                    continue
                
                if sector_name and net_inflow is not None:
                    sectors.append({
                        'name': sector_name,
                        'flow': net_inflow,
                        'change': change
                    })
            
            sectors.sort(key=lambda x: x['flow'] if x['flow'] else 0, reverse=True)
            
            result = [{
                'rank': i + 1,
                'name': s['name'],
                'flow': s['flow'],
                'change': s['change']
            } for i, s in enumerate(sectors[:50])]
            
            global latest_data
            latest_data = result
            return result
        else:
            error_logger.error(f"API返回数据格式异常: {data}")
    
    except Exception as e:
        error_logger.error(f"获取数据失败: {e}")
    
    return []

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
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                'date': date_str,
                'timestamp': datetime.now().isoformat(),
                'data': data
            }, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        error_logger.error(f"保存每日数据失败 ({date_str}): {e}")
        return False

# 加载指定日期的实时数据
def load_realtime_data(date_str):
    file_path = get_realtime_file_path(date_str)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            error_logger.error(f"加载实时数据失败 ({date_str}): {e}")
            return {}
    return {}

# 保存实时数据（追加模式）
def save_realtime_data(date_str, minute_key, data):
    file_path = get_realtime_file_path(date_str)
    try:
        realtime_data = load_realtime_data(date_str)
        
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
        system_logger.info(f"当天({today})没有实时数据，无法生成每日汇总")
        return False
    
    try:
        # 收集当天所有时间段数据中的板块资金流入
        sector_flows = {}
        for minute_key, record in realtime_data.items():
            data = record.get('data', [])
            for item in data:
                if item['name'] not in sector_flows:
                    sector_flows[item['name']] = []
                sector_flows[item['name']].append(item['flow'])
        
        # 计算每个板块的平均资金流入
        sector_avg_flows = []
        for name, flows in sector_flows.items():
            avg = sum(flows) / len(flows)
            sector_avg_flows.append({'name': name, 'avg_flow': avg})
        
        # 按平均资金流入排序，取前10个
        sector_avg_flows.sort(key=lambda x: x['avg_flow'], reverse=True)
        top_10 = sector_avg_flows[:10]
        
        # 获取最新的完整数据
        current_data = get_sector_flow_data()
        if current_data:
            # 构建当天的代表数据
            representative_data = []
            for i, item in enumerate(top_10):
                sector_info = next((s for s in current_data if s['name'] == item['name']), None)
                if sector_info:
                    representative_data.append({
                        'rank': i + 1,
                        'name': sector_info['name'],
                        'flow': sector_info['flow'],
                        'change': sector_info['change']
                    })
            
            if representative_data:
                success = save_daily_data(today, representative_data)
                if success:
                    system_logger.info(f"已生成并保存当天({today})的每日汇总数据，共{len(representative_data)}个板块")
                    return True
                else:
                    system_logger.error(f"保存当天({today})的每日汇总数据失败")
                    return False
        else:
            system_logger.error(f"获取最新数据失败，无法生成当天({today})的每日汇总")
            return False
    except Exception as e:
        error_logger.error(f"生成每日汇总数据失败 ({today}): {e}")
        return False

# 为指定日期生成每日汇总
def generate_daily_summary_for_date(date_str):
    realtime_data = load_realtime_data(date_str)
    
    if not realtime_data:
        system_logger.info(f"日期({date_str})没有实时数据")
        return False
    
    try:
        # 收集当天所有时间段数据中的板块资金流入
        sector_flows = {}
        for minute_key, record in realtime_data.items():
            data = record.get('data', [])
            for item in data:
                if item['name'] not in sector_flows:
                    sector_flows[item['name']] = []
                sector_flows[item['name']].append(item['flow'])
        
        # 计算每个板块的平均资金流入
        sector_avg_flows = []
        for name, flows in sector_flows.items():
            avg = sum(flows) / len(flows)
            sector_avg_flows.append({'name': name, 'avg_flow': avg})
        
        # 按平均资金流入排序，取前10个
        sector_avg_flows.sort(key=lambda x: x['avg_flow'], reverse=True)
        top_10 = sector_avg_flows[:10]
        
        # 获取当天的最后一个时间点的数据来获取完整信息
        last_minute = max(realtime_data.keys())
        last_data = realtime_data[last_minute]['data']
        
        # 构建当天的代表数据
        representative_data = []
        for i, item in enumerate(top_10):
            sector_info = next((s for s in last_data if s['name'] == item['name']), None)
            if sector_info:
                representative_data.append({
                    'rank': i + 1,
                    'name': sector_info['name'],
                    'flow': sector_info['flow'],
                    'change': sector_info['change']
                })
        
        if representative_data:
            success = save_daily_data(date_str, representative_data)
            if success:
                system_logger.info(f"已生成并保存日期({date_str})的每日汇总数据，共{len(representative_data)}个板块")
                return True
            else:
                system_logger.error(f"保存日期({date_str})的每日汇总数据失败")
                return False
        else:
            system_logger.error(f"无法构建日期({date_str})的每日汇总数据")
            return False
    except Exception as e:
        error_logger.error(f"生成日期({date_str})的每日汇总失败: {e}")
        return False

# 加载最近N天的每日数据
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

# 加载最近N小时的实时数据
def load_recent_realtime_data(hours):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        realtime_data = load_realtime_data(today)
        
        result = {}
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        for minute_key, record in realtime_data.items():
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
