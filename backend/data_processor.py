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
import sys
from bs4 import BeautifulSoup
from config import DAILY_DIR, REALTIME_DIR, MAX_DAYS, DATA_URL, THS_SECTOR_URL, THS_SECTOR_NET_IN_URL, THS_SECTOR_NET_OUT_URL, USE_PROXY, get_random_user_agent
from logger import get_logger

error_logger = get_logger('error')
data_logger = get_logger('data')
system_logger = get_logger('system')
cleanup_logger = get_logger('cleanup_flow')

PROXY_POOL = []
PROXY_API_URL = "https://proxy.scdn.io/api/get_proxy.php"

# 同花顺请求不复用健康检测 Cookie；业务请求现场生成 Cookie。

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
_ths_cookie_lock = threading.Lock()

def _generate_random_string(length):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def _generate_random_cookie():
    return ''

def refresh_ths_cookie(force=False):
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ths_cookie_refresh.py')
    if not os.path.exists(script_path):
        error_logger.error(f"同花顺Cookie刷新脚本不存在: {script_path}")
        return ''

    try:
        with _ths_cookie_lock:
            result = subprocess.run(
                [sys.executable, script_path, THS_SECTOR_URL],
                capture_output=True,
                text=True,
                timeout=45
            )
        cookie = result.stdout.strip()
        if result.returncode == 0 and cookie.startswith('v='):
            return cookie

        error_logger.error(f"同花顺动态Cookie刷新失败: {result.stderr.strip() or result.stdout.strip()}")
    except subprocess.TimeoutExpired:
        error_logger.error("同花顺动态Cookie刷新超时")
    except Exception as e:
        error_logger.error(f"同花顺动态Cookie刷新异常: {e}")

    return ''

def _generate_random_browser_version():
    major = random.randint(120, 148)
    minor = 0
    patch = random.randint(1000, 9999)
    build = random.randint(10, 200)
    return f'{major}.{minor}.{patch}.{build}'

def generate_random_headers(host=None, referer=None):
    browser_version = _generate_random_browser_version()
    major_version = browser_version.split('.')[0]
    
    sec_ch_ua = f'"Microsoft Edge";v="{major_version}", "Not.A/Brand";v="8", "Chromium";v="{major_version}"'
    user_agent = f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser_version} Safari/537.36 Edg/{browser_version}'
    
    target_url = THS_SECTOR_URL
    
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
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

def normalize_ths_sector_headers(headers=None):
    """Ensure cached headers are valid for the THS sector fund endpoint."""
    normalized = dict(headers or generate_random_headers())
    target_referer = 'https://data.10jqka.com.cn/funds/hyzjl/'
    normalized['Host'] = 'data.10jqka.com.cn'
    normalized['Referer'] = target_referer
    normalized['Accept'] = 'text/html, */*; q=0.01'
    normalized['X-Requested-With'] = 'XMLHttpRequest'
    normalized['sec-fetch-dest'] = 'empty'
    normalized['sec-fetch-mode'] = 'cors'
    normalized['sec-fetch-site'] = 'same-origin'

    cookie = normalized.get('Cookie', '')
    if cookie.strip() == 'vvvv=1' or cookie.strip().startswith('checkcookie='):
        normalized.pop('Cookie', None)

    return normalized

def attach_fresh_ths_cookie(headers):
    cookie = refresh_ths_cookie(force=True)
    if cookie:
        headers['Cookie'] = cookie
    return headers

def _parse_ths_number(value, default=0):
    if isinstance(value, (int, float)):
        return value
    text = (value or '').strip().replace(',', '')
    if not text or text in ('--', '-'):
        return default
    try:
        return float(text)
    except Exception:
        return default

def _parse_ths_int(value, default=0):
    return int(_parse_ths_number(value, default))

def parse_ths_sector_html(html_content, request_url=''):
    """解析同花顺板块资金流向HTML"""
    soup = BeautifulSoup(html_content, 'html.parser')
    sectors = []
    
    table = soup.find('table', class_='m-table J-ajax-table')
    if not table:
        html_preview = html_content[:500] if html_content else '(空响应)'
        error_logger.error(f"未找到板块数据表格，URL: {request_url}，HTML内容预览: {html_preview}")
        return []
    
    tbody = table.find('tbody')
    if not tbody:
        html_preview = html_content[:500] if html_content else '(空响应)'
        error_logger.error(f"未找到表格tbody，URL: {request_url}，HTML内容预览: {html_preview}")
        return []
    
    rows = tbody.find_all('tr')
    for row in rows:
        try:
            cols = row.find_all('td')
            if len(cols) < 11:
                continue
            
            rank = _parse_ths_int(cols[0].get_text(strip=True))
            
            sector_link = cols[1].find('a')
            sector_name = sector_link.get_text(strip=True) if sector_link else ''
            sector_url = sector_link.get('href', '') if sector_link else ''
            
            # 修复URL协议问题，将http改为https
            if sector_url.startswith('http://'):
                sector_url = sector_url.replace('http://', 'https://')
            
            sector_index = cols[2].get_text(strip=True)
            
            change_text = cols[3].get_text(strip=True)
            change = _parse_ths_number(change_text.replace('%', '')) / 100 if change_text else 0
            
            inflow = _parse_ths_number(cols[4].get_text(strip=True))
            outflow = _parse_ths_number(cols[5].get_text(strip=True))
            net_flow = _parse_ths_number(cols[6].get_text(strip=True))
            
            company_count = _parse_ths_int(cols[7].get_text(strip=True))
            
            lead_stock_link = cols[8].find('a')
            lead_stock_name = lead_stock_link.get_text(strip=True) if lead_stock_link else ''
            lead_stock_url = lead_stock_link.get('href', '') if lead_stock_link else ''
            
            # 修复URL协议问题，将http改为https
            if lead_stock_url.startswith('http://'):
                lead_stock_url = lead_stock_url.replace('http://', 'https://')
            
            lead_stock_change_text = cols[9].get_text(strip=True)
            lead_stock_change = _parse_ths_number(lead_stock_change_text.replace('%', '')) / 100 if lead_stock_change_text else 0
            
            lead_stock_price = _parse_ths_number(cols[10].get_text(strip=True))
            
            sectors.append({
                'rank': rank,
                'name': sector_name,
                'sector_url': sector_url,
                'sector_index': sector_index,
                'change': change,
                'inflow': inflow,
                'outflow': outflow,
                'flow': inflow,
                'net_flow': net_flow,
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
    
    return sectors

def get_sector_flow_data():
    from health_checker import get_crawler_status, set_crawler_working, set_crawler_idle
    
    crawler_status = get_crawler_status()
    if crawler_status.get('sector_flow', {}).get('status') == 'failed':
        error_logger.warning("板块资金获取已停止，跳过本次获取")
        return []
    
    set_crawler_working('sector_flow')
    # 业务采集现场生成 Cookie，不复用健康检测结果。
    headers = normalize_ths_sector_headers()
    headers = attach_fresh_ths_cookie(headers)

    def fetch_sector_page(session, url, request_headers, proxies):
        response = session.get(url, headers=request_headers, proxies=proxies, timeout=15, verify=False, allow_redirects=True)
        if response.status_code == 401 or response.status_code == 403:
            return response, None

        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '')
        if 'charset=gbk' in content_type.lower() or 'charset=gb2312' in content_type.lower():
            response.encoding = 'GBK'
        elif response.encoding == 'ISO-8859-1':
            response.encoding = 'GBK'
        else:
            try:
                response.encoding = response.apparent_encoding
            except:
                response.encoding = 'GBK'

        return response, parse_ths_sector_html(response.text, url)

    def refresh_headers_after_auth_error():
        return attach_fresh_ths_cookie(normalize_ths_sector_headers())

    def build_net_flow_watchlist(inflow_sectors, outflow_sectors):
        selected = []
        seen = set()

        inflow_top = sorted(inflow_sectors, key=lambda item: abs(_parse_ths_number(item.get('net_flow'))), reverse=True)
        outflow_top = sorted(outflow_sectors, key=lambda item: abs(_parse_ths_number(item.get('net_flow'))), reverse=True)

        for rank, item in enumerate(inflow_top[:5], start=1):
            name = item.get('name')
            if not name or name in seen:
                continue
            copied = dict(item)
            copied['rank'] = rank
            copied['flow_group'] = 'net_in'
            selected.append(copied)
            seen.add(name)

        for rank, item in enumerate(outflow_top[:5], start=1):
            name = item.get('name')
            if not name or name in seen:
                continue
            copied = dict(item)
            copied['rank'] = rank
            copied['flow_group'] = 'net_out'
            selected.append(copied)
            seen.add(name)

        return selected
    
    max_retries = 9
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
            response, inflow_sectors = fetch_sector_page(session, THS_SECTOR_NET_IN_URL, headers, proxies)
            
            if response.status_code == 401 or response.status_code == 403:
                headers = refresh_headers_after_auth_error()
                continue

            response, outflow_sectors = fetch_sector_page(session, THS_SECTOR_NET_OUT_URL, headers, proxies)
            if response.status_code == 401 or response.status_code == 403:
                headers = refresh_headers_after_auth_error()
                continue

            sectors = build_net_flow_watchlist(inflow_sectors or [], outflow_sectors or [])
            
            if sectors:
                has_valid_name = False
                for sector in sectors:
                    name = sector.get('name', '')
                    if name and any('\u4e00' <= char <= '\u9fff' for char in name):
                        has_valid_name = True
                        break
                
                if not has_valid_name:
                    error_logger.error(f"获取的板块数据名称无效（非中文），跳过本次数据保存")
                    headers = normalize_ths_sector_headers()
                    continue
                
                # 请求成功
                global latest_data
                latest_data = sectors
                from data_collector import is_trading_day, is_trading_time
                from datetime import datetime
                now = datetime.now()
                if is_trading_day(now) and is_trading_time(now):
                    data_logger.info(f"成功获取 {len(sectors)} 个板块数据")
                set_crawler_idle('sector_flow')
                return sectors
            else:
                html_preview = response.text[:1000] if response.text else '(空响应)'
                error_logger.error(f"解析板块数据失败，返回空列表，URL: {THS_SECTOR_NET_IN_URL} / {THS_SECTOR_NET_OUT_URL}，HTML内容预览: {html_preview}")
                headers = normalize_ths_sector_headers()
        
        except Exception as e:
            error_logger.error(f"板块数据获取第 {retry + 1}/{max_retries} 次失败: {e}")
            if retry < max_retries - 1:
                headers = attach_fresh_ths_cookie(normalize_ths_sector_headers())
                if USE_PROXY:
                    load_proxy_pool()
                import time
                time.sleep(6)
    
    error_logger.error(f"板块数据获取最终失败，已尝试 {max_retries} 次，URL: {THS_SECTOR_URL}")
    set_crawler_idle('sector_flow')
    return []

def parse_ths_stock_html(html_content, request_url=''):
    """解析同花顺个股详情HTML"""
    soup = BeautifulSoup(html_content, 'html.parser')
    stocks = []
    
    table = soup.find('table', class_='m-table m-pager-table')
    if not table:
        html_preview = html_content[:500] if html_content else '(空响应)'
        error_logger.error(f"未找到个股数据表格，URL: {request_url}，HTML内容预览: {html_preview}")
        return []
    
    tbody = table.find('tbody')
    if not tbody:
        html_preview = html_content[:500] if html_content else '(空响应)'
        error_logger.error(f"未找到表格tbody，URL: {request_url}，HTML内容预览: {html_preview}")
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
    from health_checker import get_crawler_status, set_crawler_working, set_crawler_idle
    
    if not sector_url:
        error_logger.error("板块URL为空")
        return []
    
    if sector_url.startswith('http://'):
        sector_url = sector_url.replace('http://', 'https://')
    
    from urllib.parse import urlparse
    parsed_url = urlparse(sector_url)
    host = parsed_url.netloc if parsed_url.netloc else 'q.10jqka.com.cn'
    
    set_crawler_working('stocks')
    # 个股详情请求现场生成 Cookie，不复用健康检测结果。
    headers = attach_fresh_ths_cookie(generate_random_headers(host=host))
    
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
            
            if response.status_code == 401 or response.status_code == 403:
                # 请求头失效，重新获取
                headers = attach_fresh_ths_cookie(generate_random_headers(host=host))
                continue
            
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '')
            if 'charset=gbk' in content_type.lower() or 'charset=gb2312' in content_type.lower():
                response.encoding = 'GBK'
            elif response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            else:
                try:
                    response.encoding = response.apparent_encoding
                except:
                    response.encoding = 'GBK'
            
            stocks = parse_ths_stock_html(response.text, sector_url)
            
            if stocks:
                set_crawler_idle('stocks')
                return stocks
            else:
                html_preview = response.text[:1000] if response.text else '(空响应)'
                error_logger.error(f"解析个股数据失败，返回空列表，URL: {sector_url}，HTML内容预览: {html_preview}")
                headers = attach_fresh_ths_cookie(generate_random_headers(host=host))
        
        except Exception as e:
            error_logger.error(f"获取板块个股第 {retry + 1}/{max_retries} 次失败: {e}")
            if retry < max_retries - 1:
                headers = attach_fresh_ths_cookie(generate_random_headers(host=host))
                if USE_PROXY:
                    load_proxy_pool()
                import time
                time.sleep(2)
    
    error_logger.error(f"个股数据获取最终失败，已尝试 {max_retries} 次，URL: {sector_url}")
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
                'net_flow': item.get('net_flow', 0),
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
                'net_flow': item.get('net_flow', 0),
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

MARKET_INDEX_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
SINA_INDEX_URL = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006"
STOCK_STAT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
THS_INDEX_FLASH_URL = "https://q.10jqka.com.cn/api.php?t=indexflash&"
THS_TURNOVER_MINUTE_URL = "https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data"
JRJ_MARKET_URL = "https://gateway.jrj.com/quot-dc/zdt/market"

latest_market_data = {}
MARKET_SUMMARY_CACHE_FILE = os.path.join(REALTIME_DIR, 'market_summary.json')
MARKET_FAST_REFRESH_SECONDS = 15
MARKET_TURNOVER_REFRESH_SECONDS = 60

def _safe_float(value, default=0):
    try:
        if value is None or value == '-':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

def _last_list_value(value):
    if isinstance(value, list) and value:
        last = value[-1]
        if isinstance(last, list) and last:
            return last[-1]
        return last
    return value

def _last_dict_value(data, key):
    if isinstance(data, dict):
        if key in data:
            return data.get(key)
        last_data = data.get('last_zdt')
        if isinstance(last_data, dict) and key in last_data:
            return last_data.get(key)
    return None

def _pick_first_number(data, keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        number = _safe_float(value, None)
        if number is not None:
            return number
    for value in data.values():
        if isinstance(value, dict):
            number = _pick_first_number(value, keys)
            if number is not None:
                return number
    return None

def _parse_json_or_jsonp(text):
    if not text:
        return None
    content = text.strip()
    if content.startswith('{') or content.startswith('['):
        return json.loads(content)
    start = content.find('(')
    end = content.rfind(')')
    if start != -1 and end > start:
        return json.loads(content[start + 1:end])
    return None

def get_eastmoney_market_index_data():
    global latest_market_data
    
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://quote.eastmoney.com/'
    }
    
    params = {
        'fltt': 2,
        'invt': 2,
        'fields': 'f1,f2,f3,f4,f12,f13,f14',
        'secids': '1.000001,0.399001,0.399006'
    }
    
    try:
        response = requests.get(MARKET_INDEX_URL, params=params, headers=headers, timeout=10)
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
    ('韩国KOSPI', '100.KS11', None, 37.57, 126.98, '韩国'),
    ('富时马来西亚', '100.KLSE', None, 3.14, 101.69, '马来西亚'),
    ('印尼综合', '100.JKSE', None, -6.21, 106.85, '印尼'),
    ('越南胡志明', '100.VNINDEX', None, 10.78, 106.70, '越南'),
    ('印度SENSEX', '100.SENSEX', 'b_SENSEX', 19.08, 72.88, '印度'),
    ('澳大利亚ASX200', '100.AS51', None, -33.87, 151.21, '澳大利亚'),
    ('道琼斯', '100.DJIA', 'int_dji', 38.90, -77.04, '美国'),
    ('纳斯达克', '100.NDX', 'int_nasdaq', 40.71, -74.01, '美国'),
    ('标普500', '100.SPX', 'int_sp500', 41.80, -87.65, '美国'),
    ('巴西BOVESPA', '100.BVSP', None, -23.55, -46.63, '巴西'),
    ('英国富时100', '100.FTSE', 'int_ftse', 51.51, -0.13, '英国'),
    ('德国DAX30', '100.GDAXI', None, 50.11, 8.68, '德国'),
    ('法国CAC40', '100.FCHI', None, 48.86, 2.35, '法国'),
    ('荷兰AEX', '100.AEX', None, 52.37, 4.90, '荷兰'),
    ('瑞士SMI', '100.SSMI', None, 47.37, 8.54, '瑞士'),
    ('俄罗斯RTS', '100.RTS', None, 55.75, 37.62, '俄罗斯'),
]

GLOBAL_INDICES_CACHE_FILE = os.path.join(REALTIME_DIR, 'global_indices_cache.json')


def get_global_market_indices():
    """获取全球主要股市指数（双源：东方财富为主，新浪兜底）"""
    secids = ','.join(cfg[1] for cfg in GLOBAL_INDICES_CONFIG)
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://quote.eastmoney.com/'
    }
    params = {
        'fltt': 2,
        'invt': 2,
        'fields': 'f2,f3,f4,f12,f14',
        'secids': secids
    }

    result = {}
    em_ok = False
    try:
        response = requests.get(MARKET_INDEX_URL, params=params, headers=headers, timeout=10)
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
                if len(values) < 4 or not values[1]:
                    continue
                price = _safe_float(values[1], None)
                change_pct = _safe_float(values[3], None)
                if price is None or change_pct is None:
                    continue
                for cfg in sina_needed:
                    if cfg[2] == key and cfg[1] not in result:
                        name, secid, _, lat, lng, region = cfg
                        result[secid] = {
                            'name': name,
                            'code': secid,
                            'price': round(price, 2),
                            'change': change_pct / 100,
                            'change_amount': round(price * change_pct / 100, 2),
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

# 新浪行业板块与个股接口（大盘云图用，避免东方财富反爬）
SINA_SECTOR_LIST_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
SINA_SECTOR_STOCKS_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

# 东方财富全A股接口（用于行业分类+市值，低频缓存）
EM_ALL_STOCK_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

# 行业缓存文件
MARKET_MAP_CACHE_FILE = os.path.join(REALTIME_DIR, 'market_map_industry.json')

# 申万二级行业(f100) → 一级行业 映射表（申万2021分类标准）
SW_L2_TO_L1 = {
    # 农林牧渔
    '种植业': '农林牧渔', '渔业': '农林牧渔', '林业Ⅱ': '农林牧渔', '饲料': '农林牧渔',
    '农产品加工': '农林牧渔', '养殖业': '农林牧渔', '农业综合Ⅱ': '农林牧渔', '动物保健Ⅱ': '农林牧渔',
    # 基础化工
    '化学原料': '基础化工', '化学制品': '基础化工', '化学纤维': '基础化工', '农化制品': '基础化工',
    '塑料': '基础化工', '橡胶': '基础化工', '非金属材料Ⅱ': '基础化工',
    # 钢铁
    '普钢': '钢铁', '特钢Ⅱ': '钢铁', '冶钢原料': '钢铁',
    # 有色金属
    '工业金属': '有色金属', '小金属': '有色金属', '贵金属': '有色金属', '能源金属': '有色金属', '金属新材料': '有色金属',
    # 电子
    '半导体': '电子', '元件': '电子', '光学光电子': '电子', '消费电子': '电子', '其他电子Ⅱ': '电子', '电子化学品Ⅱ': '电子',
    # 机械设备
    '通用设备': '机械设备', '专用设备': '机械设备', '仪器仪表': '机械设备', '自动化设备': '机械设备',
    '工程机械': '机械设备', '轨交设备Ⅱ': '机械设备',
    # 国防军工
    '航空装备Ⅱ': '国防军工', '航天装备Ⅱ': '国防军工', '地面兵装Ⅱ': '国防军工', '军工电子Ⅱ': '国防军工', '航海装备Ⅱ': '国防军工',
    # 计算机
    '软件开发': '计算机', '计算机设备': '计算机', 'IT服务Ⅱ': '计算机',
    # 传媒
    '数字媒体': '传媒', '广告营销': '传媒', '出版': '传媒', '影视院线': '传媒', '游戏Ⅱ': '传媒', '电视广播Ⅱ': '传媒',
    # 通信
    '通信设备': '通信', '通信服务': '通信',
    # 医药生物
    '化学制药': '医药生物', '中药Ⅱ': '医药生物', '生物制品': '医药生物', '医疗器械': '医药生物',
    '医药商业': '医药生物', '医疗服务': '医药生物', '医疗美容': '医药生物',
    # 银行 / 非银金融
    '银行Ⅱ': '银行',
    '证券Ⅱ': '非银金融', '保险Ⅱ': '非银金融', '多元金融': '非银金融',
    # 房地产
    '房地产开发': '房地产', '房地产服务': '房地产',
    # 交通运输
    '铁路公路': '交通运输', '航运港口': '交通运输', '航空机场': '交通运输', '物流': '交通运输',
    # 公用事业
    '电力': '公用事业', '燃气Ⅱ': '公用事业',
    # 电力设备
    '光伏设备': '电力设备', '风电设备': '电力设备', '电池': '电力设备', '电网设备': '电力设备',
    '其他电源设备Ⅱ': '电力设备', '电机Ⅱ': '电力设备',
    # 汽车
    '乘用车': '汽车', '商用车': '汽车', '汽车零部件': '汽车', '汽车服务': '汽车', '摩托车及其他': '汽车',
    # 家用电器
    '白色家电': '家用电器', '黑色家电': '家用电器', '小家电': '家用电器', '厨卫电器': '家用电器',
    '照明设备Ⅱ': '家用电器', '家电零部件Ⅱ': '家用电器', '其他家电Ⅱ': '家用电器',
    # 食品饮料
    '白酒Ⅱ': '食品饮料', '非白酒': '食品饮料', '饮料乳品': '食品饮料', '食品加工': '食品饮料',
    '休闲食品': '食品饮料', '调味发酵品Ⅱ': '食品饮料',
    # 纺织服饰
    '服装家纺': '纺织服饰', '纺织制造': '纺织服饰', '饰品': '纺织服饰',
    # 轻工制造
    '家居用品': '轻工制造', '造纸': '轻工制造', '包装印刷': '轻工制造', '文娱用品': '轻工制造',
    # 商贸零售
    '一般零售': '商贸零售', '专业连锁Ⅱ': '商贸零售', '互联网电商': '商贸零售', '贸易Ⅱ': '商贸零售', '旅游零售Ⅱ': '商贸零售',
    # 社会服务
    '酒店餐饮': '社会服务', '旅游及景区': '社会服务', '教育': '社会服务', '专业服务': '社会服务', '体育Ⅱ': '社会服务',
    # 建筑材料
    '水泥': '建筑材料', '玻璃玻纤': '建筑材料', '装修建材': '建筑材料',
    # 建筑装饰
    '房屋建设Ⅱ': '建筑装饰', '装修装饰Ⅱ': '建筑装饰', '基础建设': '建筑装饰', '专业工程': '建筑装饰', '工程咨询服务Ⅱ': '建筑装饰',
    # 环保
    '环境治理': '环保', '环保设备Ⅱ': '环保',
    # 煤炭 / 石油石化
    '煤炭开采': '煤炭', '焦炭Ⅱ': '煤炭',
    '油气开采Ⅱ': '石油石化', '油服工程': '石油石化', '炼化及贸易': '石油石化',
    # 美容护理 / 综合
    '化妆品': '美容护理', '个护用品': '美容护理',
    '综合Ⅱ': '综合',
}


def _em_code_to_sina(em_code):
    """东方财富纯代码 → 新浪代码(sh/sz/bj前缀)"""
    code = str(em_code)
    if code.startswith(('6', '68', '11', '13')):
        return 'sh' + code
    elif code.startswith(('8', '4', '9')):
        return 'bj' + code
    else:
        return 'sz' + code


def refresh_market_map_cache():
    """分页抓取东方财富全部A股的行业分类+市值，缓存到本地文件。
    股票行业分类变化极少，建议低频更新（每周/手动触发）。"""
    # 用Session复用HTTP连接(keep-alive)+页间小延时+断连退避重试，降低东财反爬断连概率
    session = requests.Session()
    session.headers.update({
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://quote.eastmoney.com/',
        'Accept': '*/*'
    })
    all_stocks = {}
    page = 1
    while page <= 80:
        params = {
            'pn': page, 'pz': 100, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f12',  # 按股票代码排序(稳定)。勿用f3涨跌幅——交易时段实时变动会让分页间股票漂移，导致漏抓/重抓(银行等就这样丢了)
            'fs': EM_A_SHARE_FS,
            'fields': 'f12,f14,f100,f20'
        }
        # 单页重试3次(断连后0.5s退避)；仍失败则跳过该页继续，不再中止整批
        diff = None
        last_err = None
        for _attempt in range(3):
            try:
                response = session.get(EM_ALL_STOCK_URL, params=params, timeout=12)
                diff = (response.json().get('data') or {}).get('diff', []) or []
                break
            except Exception as e:
                last_err = e
                diff = None
                time.sleep(0.5)
        if diff is None:
            error_logger.warning(f"大盘云图缓存抓取第{page}页失败(重试3次): {last_err}")
            page += 1
            continue
        if not diff:
            break
        for item in diff:
            code = str(item.get('f12', ''))
            if not code:
                continue
            l2 = item.get('f100', '') or ''
            l2 = l2.strip()
            l1 = SW_L2_TO_L1.get(l2, '综合')
            if not l2 or l2 == '-':
                l2 = '其他'
                l1 = '综合'
            market_cap = _safe_float(item.get('f20'), 0)
            all_stocks[_em_code_to_sina(code)] = {
                'name': item.get('f14', ''),
                'l1': l1,
                'l2': l2,
                'value': market_cap  # 总市值(元)，作为面积基准
            }
        if len(diff) < 100:
            break
        page += 1
        time.sleep(0.2)   # 页间小延时，避免突发请求被东财反爬断连

    if not all_stocks:
        error_logger.warning("大盘云图缓存抓取失败：无数据")
        return None

    # 与上次缓存合并：本次因断连漏抓的页，用上次缓存里对应个股补齐，
    # 多刷新几次会累加到接近全量；银行等早期页面始终能抓到、永不丢。
    merged = dict(all_stocks)
    filled = 0
    try:
        if os.path.exists(MARKET_MAP_CACHE_FILE):
            with open(MARKET_MAP_CACHE_FILE, 'r', encoding='utf-8') as f:
                old = json.load(f)
            for code, info in (old.get('stocks') or {}).items():
                if code not in merged:
                    merged[code] = info
                    filled += 1
    except Exception:
        pass

    cache_data = {
        'stocks': merged,
        'count': len(merged),
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    try:
        with open(MARKET_MAP_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False)
        error_logger.info(f"大盘云图行业缓存已更新: 本次新抓{len(all_stocks)}只，缓存补齐{filled}只，合计{len(merged)}只")
    except Exception as e:
        error_logger.warning(f"大盘云图缓存写入失败: {e}")
    return cache_data


def _load_market_map_cache():
    """读取行业+市值缓存"""
    if not os.path.exists(MARKET_MAP_CACHE_FILE):
        return None
    try:
        with open(MARKET_MAP_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _sina_batch_one(batch):
    """新浪批量获取单批涨跌幅（供并行调用）"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    result = {}
    url = f"https://hq.sinajs.cn/list={','.join(batch)}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'gbk'
        for line in response.text.strip().split('\n'):
            m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code = m.group(1)
            fields = m.group(2).split(',')
            if len(fields) >= 4:
                try:
                    pre_close = float(fields[2])
                    price = float(fields[3])
                    # price<=0：盘前/集合竞价尚未撮合/停牌无成交，新浪此时最新价为0，
                    # 直接算会得到 -100%。跳过，下游回退为0%（持平），避免全屏 -100%。
                    if pre_close > 0 and price > 0:
                        result[code] = round((price - pre_close) / pre_close * 100, 2)
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        error_logger.warning(f"新浪批量行情获取失败: {e}")
    return result


def _sina_batch_changes(sina_codes):
    """新浪并行批量获取实时涨跌幅。返回 {sina_code: 涨跌幅%}"""
    if not sina_codes:
        return {}
    batch_size = 400
    batches = [sina_codes[i:i + batch_size] for i in range(0, len(sina_codes), batch_size)]
    from concurrent.futures import ThreadPoolExecutor
    result = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        for batch_result in executor.map(_sina_batch_one, batches):
            result.update(batch_result)
    return result


def get_market_map_tree(include_changes=True):
    """构建三级大盘云图树：申万一级→二级→个股。
    行业+市值来自本地缓存（低频更新），涨跌幅来自新浪实时行情（高频）。
    若缓存不存在则自动抓取一次。
    include_changes=False 时跳过新浪实时请求、涨跌幅全部按0%，用于首屏秒开骨架。"""
    cache = _load_market_map_cache()
    if not cache or not cache.get('stocks'):
        error_logger.info("大盘云图缓存不存在，自动抓取中...")
        cache = refresh_market_map_cache()
        if not cache:
            return None

    stocks_cache = cache['stocks']
    cache_time = cache.get('update_time', '')

    # 新浪批量获取实时涨跌幅（首屏骨架模式跳过，涨跌幅全部为0，瞬时返回）
    sina_codes = list(stocks_cache.keys())
    changes = _sina_batch_changes(sina_codes) if include_changes else {}

    # 构建三级树
    tree_map = {}  # {l1: {l2: [stocks]}}
    for code, info in stocks_cache.items():
        l1 = info['l1']
        l2 = info['l2']
        change = changes.get(code, 0)
        if l1 not in tree_map:
            tree_map[l1] = {}
        if l2 not in tree_map[l1]:
            tree_map[l1][l2] = []
        tree_map[l1][l2].append({
            'name': info['name'],
            'code': code,
            'change': change,
            'value': info['value']
        })

    # 转为列表并排序，统计层级市值
    tree = []
    total_stocks = 0
    for l1, l2_map in tree_map.items():
        l1_value = 0
        l1_change_sum = 0
        l1_count = 0
        l2_list = []
        for l2, stocks in l2_map.items():
            # 每个二级内的个股按市值排序
            stocks.sort(key=lambda x: x['value'], reverse=True)
            l2_value = sum(s['value'] for s in stocks)
            l2_change = sum(s['change'] for s in stocks) / len(stocks) if stocks else 0
            l1_value += l2_value
            l1_change_sum += sum(s['change'] for s in stocks)
            l1_count += len(stocks)
            total_stocks += len(stocks)
            l2_list.append({
                'name': l2,
                'change': round(l2_change, 2),
                'value': l2_value,
                'children': stocks
            })
        l2_list.sort(key=lambda x: x['value'], reverse=True)
        tree.append({
            'name': l1,
            'change': round(l1_change_sum / l1_count, 2) if l1_count else 0,
            'value': l1_value,
            'children': l2_list
        })

    # 一级按市值排序
    tree.sort(key=lambda x: x['value'], reverse=True)
    return {
        'tree': tree,
        'total_sectors': len(tree),
        'total_stocks': total_stocks,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'cache_time': cache_time,
        'source': 'eastmoney+sina'
    }


def _fetch_sector_stocks(node):
    """抓取单个板块的全部个股（供并行调用）"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://vip.stock.finance.sina.com.cn/'
    }
    params = {
        'page': 1,
        'num': 300,
        'sort': 'mktcap',
        'asc': 0,
        'node': node,
        'symbol': '',
        '_s_r_a': 'page'
    }
    try:
        response = requests.get(SINA_SECTOR_STOCKS_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list):
            return []
        stocks = []
        for s in items:
            mktcap = _safe_float(s.get('mktcap'), 0)   # 流通市值（万元）
            if mktcap <= 0:
                continue
            stocks.append({
                'name': s.get('name', ''),
                'code': s.get('symbol', ''),
                'change': round(_safe_float(s.get('changepercent'), 0), 2),
                'value': mktcap,
                'price': _safe_float(s.get('trade'), 0)
            })
        return stocks
    except Exception as e:
        error_logger.warning(f"板块 {node} 个股获取失败: {e}")
        return []


def get_market_map_all():
    """一次性并行抓取全市场 行业→个股 嵌套数据（大盘云图用）。
    使用线程池并行抓取49个板块，返回嵌套结构。
    返回：[{ name:行业名, change:板块涨跌, value:板块市值, children: [{name,code,change,value,price}] }]"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    try:
        # 1. 获取全部一级行业板块
        response = requests.get(SINA_SECTOR_LIST_URL, headers=headers, timeout=10)
        response.encoding = 'gbk'
        m = re.search(r'\{.*\}', response.text, re.S)
        if not m:
            error_logger.warning("大盘云图板块数据格式异常")
            return None
        raw = m.group(0).replace("'", '"')
        d = json.loads(raw)

        sector_list = []
        for node, val in d.items():
            p = val.split(',')
            if len(p) < 13:
                continue
            name = p[1]
            change = round(_safe_float(p[4], 0), 2)
            market_cap = _safe_float(p[7], 0)
            if market_cap <= 0:
                continue
            sector_list.append({
                'name': name,
                'code': node,
                'change': change,
                'value': market_cap
            })
        if not sector_list:
            error_logger.warning("大盘云图板块数据为空")
            return None

        # 2. 并行抓取各板块个股
        from concurrent.futures import ThreadPoolExecutor
        nodes = [s['code'] for s in sector_list]
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(_fetch_sector_stocks, nodes))

        # 3. 组装嵌套结构
        tree = []
        for sector, stocks in zip(sector_list, results):
            if not stocks:
                continue
            sector_value = sum(st['value'] for st in stocks)
            tree.append({
                'name': sector['name'],
                'change': sector['change'],
                'value': sector_value,
                'children': stocks
            })
        # 按市值排序
        tree.sort(key=lambda x: x['value'], reverse=True)
        total_stocks = sum(len(s['children']) for s in tree)
        error_logger.info(f"大盘云图: {len(tree)}个行业, {total_stocks}只个股")
        return {
            'tree': tree,
            'total_sectors': len(tree),
            'total_stocks': total_stocks,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'sina'
        }
    except Exception as e:
        error_logger.warning(f"大盘云图全量数据获取失败: {e}")
        return None


def get_market_map_sectors():
    """获取全市场行业板块列表（按市值排序，数据源：新浪）"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    try:
        response = requests.get(SINA_SECTOR_LIST_URL, headers=headers, timeout=10)
        response.encoding = 'gbk'
        m = re.search(r'\{.*\}', response.text, re.S)
        if not m:
            error_logger.warning("大盘云图板块数据格式异常")
            return None
        raw = m.group(0).replace("'", '"')
        d = json.loads(raw)

        sectors = []
        for node, val in d.items():
            p = val.split(',')
            if len(p) < 13:
                continue
            name = p[1]
            change = _safe_float(p[4], 0)
            turnover = _safe_float(p[6], 0)
            market_cap = _safe_float(p[7], 0)
            if market_cap <= 0:
                continue
            sectors.append({
                'name': name,
                'code': node,
                'change': round(change, 2),
                'value': market_cap,
                'turnover': turnover,
                'leader': p[12] if len(p) > 12 else '',
                'leader_change': round(_safe_float(p[9], 0), 2)
            })
        if not sectors:
            error_logger.warning("大盘云图板块数据为空")
            return None
        sectors.sort(key=lambda x: x['value'], reverse=True)
        return {
            'sectors': sectors,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'sina'
        }
    except Exception as e:
        error_logger.warning(f"大盘云图板块数据获取失败: {e}")
        return None

def get_market_map_stocks(sector_code):
    """获取指定板块下的个股（按流通市值排序，数据源：新浪）"""
    stocks = _fetch_sector_stocks(sector_code)
    if not stocks:
        return None
    return {
        'stocks': stocks,
        'sector_code': sector_code,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'sina'
    }

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
