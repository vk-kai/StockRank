import requests
import json
from datetime import datetime, timedelta
import os
from config import DAILY_DIR, REALTIME_DIR, MAX_DAYS,DATA_URL
from logger import setup_logging

# 初始化日志
error_logger, data_logger, system_logger = setup_logging()

# 全局变量存储最新数据
latest_data = []

# 从东方财富获取板块资金流入数据
def get_sector_flow_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
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
                # f62: 净流入（单位：元），转换为万元
                net_inflow = item.get('f62', 0) / 10000
                # f3: 涨跌幅度（单位：百分比），转换为小数
                change = item.get('f3', 0) / 100
                
                if sector_name and net_inflow is not None:
                    sectors.append({
                        'name': sector_name,
                        'flow': net_inflow,
                        'change': change
                    })
            
            # 按净流入排序
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
    
    except Exception as e:
        error_logger.error(f"获取数据失败: {e}")
        return []
    
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
    try:
        cutoff_date = (datetime.now() - timedelta(days=MAX_DAYS)).strftime('%Y-%m-%d')
        
        # 清理每日数据
        deleted_daily = 0
        for filename in os.listdir(DAILY_DIR):
            if filename.endswith('.json'):
                date_str = filename.replace('.json', '')
                if date_str < cutoff_date:
                    os.remove(os.path.join(DAILY_DIR, filename))
                    deleted_daily += 1
        
        # 清理实时数据
        deleted_realtime = 0
        for filename in os.listdir(REALTIME_DIR):
            if filename.endswith('.json'):
                date_str = filename.replace('.json', '')
                if date_str < cutoff_date:
                    os.remove(os.path.join(REALTIME_DIR, filename))
                    deleted_realtime += 1
        
        system_logger.info(f"清理过期数据完成: 每日数据 {deleted_daily} 个, 实时数据 {deleted_realtime} 个")
        return True
    except Exception as e:
        error_logger.error(f"清理过期数据失败: {e}")
        return False

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

# 加载最近N小时的实时数据
def load_recent_realtime_data(hours):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        realtime_data = load_realtime_data(today)
        
        result = {}
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        for minute_key, record in realtime_data.items():
            # 将时间字符串转换为datetime对象进行比较
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
