import requests
import json
from datetime import datetime, timedelta
import os
import random
import string
import hashlib
from bs4 import BeautifulSoup
from config import DAILY_DIR, REALTIME_DIR, MAX_DAYS, DATA_URL, THS_SECTOR_URL, USE_PROXY, get_random_user_agent
from logger import get_logger

error_logger = get_logger('error')
data_logger = get_logger('data')
system_logger = get_logger('system')
cleanup_logger = get_logger('cleanup_flow')

PROXY_POOL = []
PROXY_API_URL = "https://proxy.scdn.io/api/get_proxy.php"

_current_working_headers = None

def load_proxy_pool():
    if not USE_PROXY:
        system_logger.info("代理功能已禁用，跳过代理池加载")
        return
    
    global PROXY_POOL
    try:
        response = requests.get(PROXY_API_URL, params={
            'protocol': 'https',
            'count': 5,
            'country_code': 'CN'
        }, timeout=15)
        data = response.json()
        if data.get('code') == 200 and data.get('data', {}).get('proxies'):
            proxies = data['data']['proxies']
            PROXY_POOL.clear()
            for proxy in proxies:
                proxy_with_protocol = f'https://{proxy}'
                PROXY_POOL.append(proxy_with_protocol)
            system_logger.info(f"成功从API获取 {len(PROXY_POOL)} 个HTTPS代理")
        else:
            error_logger.warning(f"API返回异常: {data}")
    except Exception as e:
        error_logger.error(f"获取代理失败: {e}")

if USE_PROXY:
    load_proxy_pool()

latest_data = []

def _generate_random_string(length):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def _generate_random_cookie():
    return 'vvvv=1'

def _generate_random_browser_version():
    major = random.randint(120, 148)
    minor = 0
    patch = random.randint(1000, 9999)
    build = random.randint(10, 200)
    return f'{major}.{minor}.{patch}.{build}'

def generate_random_headers(host=None, referer=None):
    browser_version = _generate_random_browser_version()
    major_version = browser_version.split('.')[0]
    
    cookie = _generate_random_cookie()
    
    sec_ch_ua = f'"Microsoft Edge";v="{major_version}", "Not.A/Brand";v="8", "Chromium";v="{major_version}"'
    user_agent = f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser_version} Safari/537.36 Edg/{browser_version}'
    
    target_url = THS_SECTOR_URL
    
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Cookie': cookie,
        'Host': host or 'data.10jqka.com.cn',
        'Referer': referer or target_url,
        'sec-ch-ua': sec_ch_ua,
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': user_agent
    }
    
    return headers

def get_working_headers():
    global _current_working_headers
    return _current_working_headers

def set_working_headers(headers):
    global _current_working_headers
    _current_working_headers = headers
    system_logger.info(f"已设置可用的请求头")

def parse_ths_sector_html(html_content):
    """解析同花顺板块资金流向HTML"""
    soup = BeautifulSoup(html_content, 'html.parser')
    sectors = []
    
    table = soup.find('table', class_='m-table J-ajax-table')
    if not table:
        error_logger.error("未找到板块数据表格")
        return []
    
    tbody = table.find('tbody')
    if not tbody:
        error_logger.error("未找到表格tbody")
        return []
    
    rows = tbody.find_all('tr')
    for row in rows:
        try:
            cols = row.find_all('td')
            if len(cols) < 11:
                continue
            
            rank = int(cols[0].get_text(strip=True))
            
            sector_link = cols[1].find('a')
            sector_name = sector_link.get_text(strip=True) if sector_link else ''
            sector_url = sector_link.get('href', '') if sector_link else ''
            
            # 修复URL协议问题，将http改为https
            if sector_url.startswith('http://'):
                sector_url = sector_url.replace('http://', 'https://')
            
            sector_index = cols[2].get_text(strip=True)
            
            change_text = cols[3].get_text(strip=True)
            change = float(change_text.replace('%', '')) / 100 if change_text else 0
            
            inflow = float(cols[4].get_text(strip=True)) if cols[4].get_text(strip=True) else 0
            outflow = float(cols[5].get_text(strip=True)) if cols[5].get_text(strip=True) else 0
            net_flow = float(cols[6].get_text(strip=True)) if cols[6].get_text(strip=True) else 0
            
            company_count = int(cols[7].get_text(strip=True)) if cols[7].get_text(strip=True) else 0
            
            lead_stock_link = cols[8].find('a')
            lead_stock_name = lead_stock_link.get_text(strip=True) if lead_stock_link else ''
            lead_stock_url = lead_stock_link.get('href', '') if lead_stock_link else ''
            
            # 修复URL协议问题，将http改为https
            if lead_stock_url.startswith('http://'):
                lead_stock_url = lead_stock_url.replace('http://', 'https://')
            
            lead_stock_change_text = cols[9].get_text(strip=True)
            lead_stock_change = float(lead_stock_change_text.replace('%', '')) / 100 if lead_stock_change_text else 0
            
            lead_stock_price = float(cols[10].get_text(strip=True)) if cols[10].get_text(strip=True) else 0
            
            sectors.append({
                'rank': rank,
                'name': sector_name,
                'sector_url': sector_url,
                'sector_index': sector_index,
                'change': change,
                'inflow': inflow,
                'outflow': outflow,
                'flow': net_flow,
                'company_count': company_count,
                'lead_stock': {
                    'name': lead_stock_name,
                    'url': lead_stock_url,
                    'change': lead_stock_change,
                    'price': lead_stock_price
                }
            })
        except Exception as e:
            error_logger.error(f"解析板块行数据失败: {e}")
            continue
    
    return sectors[:10]

def get_sector_flow_data():
    from health_checker import get_crawler_status, set_crawler_working, set_crawler_idle
    
    crawler_status = get_crawler_status()
    if crawler_status.get('sector_flow', {}).get('status') == 'failed':
        error_logger.warning("板块资金获取已停止，跳过本次获取")
        return []
    
    set_crawler_working('sector_flow')
    headers = generate_random_headers()
    
    max_retries = 3
    for retry in range(max_retries):
        try:
            proxies = None
            proxy = None
            if USE_PROXY and PROXY_POOL:
                proxy = random.choice(PROXY_POOL)
                proxies = {
                    'http': proxy,
                    'https': proxy
                }
            
            session = requests.Session()
            session.trust_env = False
            response = session.get(THS_SECTOR_URL, headers=headers, proxies=proxies, timeout=15, verify=False, allow_redirects=True)
            
            if response.status_code == 401 or response.status_code == 403:
                error_logger.warning(f"请求被拒绝 (HTTP {response.status_code})，尝试重新生成请求头")
                headers = generate_random_headers()
                continue
            
            response.raise_for_status()
            
            if response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            else:
                response.encoding = response.apparent_encoding
            
            sectors = parse_ths_sector_html(response.text)
            
            if sectors:
                global latest_data
                latest_data = sectors
                data_logger.info(f"成功获取 {len(sectors)} 个板块数据")
                set_crawler_idle('sector_flow')
                return sectors
            else:
                error_logger.error("解析板块数据失败，返回空列表")
        
        except Exception as e:
            if USE_PROXY and PROXY_POOL:
                error_logger.error(f"第 {retry+1} 次尝试使用代理 {proxy} 获取数据失败: {e}")
            else:
                error_logger.error(f"第 {retry+1} 次尝试获取数据失败: {e}")
            
            if retry < max_retries - 1:
                if USE_PROXY:
                    load_proxy_pool()
                import time
                time.sleep(2)
    
    error_logger.error(f"已尝试 {max_retries} 次，均未能成功获取数据")
    set_crawler_idle('sector_flow')
    return []

def parse_ths_stock_html(html_content):
    """解析同花顺个股详情HTML"""
    soup = BeautifulSoup(html_content, 'html.parser')
    stocks = []
    
    table = soup.find('table', class_='m-table m-pager-table')
    if not table:
        error_logger.error("未找到个股数据表格")
        return []
    
    tbody = table.find('tbody')
    if not tbody:
        error_logger.error("未找到表格tbody")
        return []
    
    rows = tbody.find_all('tr')
    for row in rows:
        try:
            cols = row.find_all('td')
            if len(cols) < 14:
                continue
            
            rank = int(cols[0].get_text(strip=True))
            
            code_link = cols[1].find('a')
            code = code_link.get_text(strip=True) if code_link else ''
            stock_url = code_link.get('href', '') if code_link else ''
            
            name_link = cols[2].find('a')
            name = name_link.get_text(strip=True) if name_link else ''
            
            price_text = cols[3].get_text(strip=True)
            price = float(price_text) if price_text and price_text != '--' else 0
            
            change_text = cols[4].get_text(strip=True)
            change = float(change_text) / 100 if change_text and change_text != '--' else 0
            
            change_value_text = cols[5].get_text(strip=True)
            change_value = float(change_value_text) if change_value_text and change_value_text != '--' else 0
            
            speed_text = cols[6].get_text(strip=True)
            speed = float(speed_text) / 100 if speed_text and speed_text != '--' else 0
            
            turnover_text = cols[7].get_text(strip=True)
            turnover = float(turnover_text) if turnover_text and turnover_text != '--' else 0
            
            volume_ratio_text = cols[8].get_text(strip=True)
            volume_ratio = float(volume_ratio_text) if volume_ratio_text and volume_ratio_text != '--' else 0
            
            amplitude_text = cols[9].get_text(strip=True)
            amplitude = float(amplitude_text) / 100 if amplitude_text and amplitude_text != '--' else 0
            
            volume_text = cols[10].get_text(strip=True)
            volume = volume_text if volume_text else ''
            
            circulation_text = cols[11].get_text(strip=True)
            circulation = circulation_text if circulation_text else ''
            
            market_cap_text = cols[12].get_text(strip=True)
            market_cap = market_cap_text if market_cap_text else ''
            
            pe_text = cols[13].get_text(strip=True)
            pe = float(pe_text) if pe_text and pe_text != '--' else 0
            
            stocks.append({
                'rank': rank,
                'code': code,
                'name': name,
                'url': stock_url,
                'price': price,
                'change': change,
                'change_value': change_value,
                'speed': speed,
                'turnover': turnover,
                'volume_ratio': volume_ratio,
                'amplitude': amplitude,
                'volume': volume,
                'circulation': circulation,
                'market_cap': market_cap,
                'pe': pe
            })
        except Exception as e:
            error_logger.error(f"解析个股行数据失败: {e}")
            continue
    
    return stocks

def get_sector_stocks(sector_url):
    from health_checker import find_working_headers_for_stocks, get_crawler_status, set_crawler_working, set_crawler_idle
    
    if not sector_url:
        error_logger.error("板块URL为空")
        return []
    
    if sector_url.startswith('http://'):
        sector_url = sector_url.replace('http://', 'https://')
    
    from urllib.parse import urlparse
    parsed_url = urlparse(sector_url)
    host = parsed_url.netloc if parsed_url.netloc else 'q.10jqka.com.cn'
    
    crawler_status = get_crawler_status()
    if crawler_status.get('stocks', {}).get('status') == 'failed':
        error_logger.warning("个股详情获取已停止，跳过本次获取")
        return []
    
    working_headers = find_working_headers_for_stocks()
    if not working_headers:
        error_logger.error("无法找到可用的请求头，个股详情获取已停止")
        return []
    
    set_crawler_working('stocks')
    headers = working_headers
    
    max_retries = 3
    for retry in range(max_retries):
        try:
            proxies = None
            proxy = None
            if USE_PROXY and PROXY_POOL:
                proxy = random.choice(PROXY_POOL)
                proxies = {
                    'http': proxy,
                    'https': proxy
                }
            
            session = requests.Session()
            session.trust_env = False
            response = session.get(sector_url, headers=headers, proxies=proxies, timeout=15, verify=False, allow_redirects=True)
            response.raise_for_status()
            
            if response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            else:
                response.encoding = response.apparent_encoding
            
            stocks = parse_ths_stock_html(response.text)
            
            if stocks:
                data_logger.info(f"成功获取 {len(stocks)} 只个股数据")
                set_crawler_idle('stocks')
                return stocks
            else:
                error_logger.error("解析个股数据失败，返回空列表")
        
        except Exception as e:
            if USE_PROXY and PROXY_POOL:
                error_logger.error(f"第 {retry+1} 次尝试使用代理 {proxy} 获取个股数据失败: {e}")
            else:
                error_logger.error(f"第 {retry+1} 次尝试获取个股数据失败: {e}")
            
            if retry < max_retries - 1:
                if USE_PROXY:
                    load_proxy_pool()
                import time
                time.sleep(2)
    
    error_logger.error(f"已尝试 {max_retries} 次，均未能成功获取个股数据")
    set_crawler_idle('stocks')
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
        system_logger.info(f"当天({today})没有实时数据，无法生成每日汇总")
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
                'change': item['change']
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
            system_logger.error(f"无法构建当天({today})的每日汇总数据")
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
                'change': item['change']
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

MARKET_INDEX_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
STOCK_STAT_URL = "https://push2.eastmoney.com/api/qt/clist/get"

latest_market_data = {}

def get_market_index_data():
    global latest_market_data
    
    headers = {
        'User-Agent': get_random_user_agent()
    }
    
    params = {
        'fltt': 2,
        'invt': 2,
        'fields': 'f1,f2,f3,f4,f12,f13,f14',
        'secids': '1.000001,0.399001,0.399006'
    }
    
    try:
        response = requests.get(MARKET_INDEX_URL, params=params, headers=headers, timeout=10)
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
            error_logger.error(f"获取大盘指数数据格式异常: {data}")
    except Exception as e:
        error_logger.error(f"获取大盘指数数据失败: {e}")
    
    return None

def get_stock_statistics():
    global latest_market_data
    
    headers = {
        'User-Agent': get_random_user_agent()
    }
    
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
        response = requests.get(STOCK_STAT_URL, params=params, headers=headers, timeout=10)
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
