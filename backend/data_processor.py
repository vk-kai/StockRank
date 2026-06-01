import requests
import json
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

# 请求头由 health_checker 统一管理，业务功能通过 get_shared_headers() 获取

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
_ths_cookie_cache = {
    'cookie': '',
    'expires_at': 0
}
_ths_cookie_lock = threading.Lock()

def _generate_random_string(length):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def _generate_random_cookie():
    return ''

def _get_cached_ths_cookie():
    if _ths_cookie_cache['cookie'] and _ths_cookie_cache['expires_at'] > time.time():
        return _ths_cookie_cache['cookie']
    return ''

def refresh_ths_cookie():
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ths_cookie_refresh.py')
    if not os.path.exists(script_path):
        error_logger.error(f"同花顺Cookie刷新脚本不存在: {script_path}")
        return ''

    try:
        with _ths_cookie_lock:
            cached_cookie = _get_cached_ths_cookie()
            if cached_cookie:
                return cached_cookie

            result = subprocess.run(
                [sys.executable, script_path, THS_SECTOR_URL],
                capture_output=True,
                text=True,
                timeout=45
            )
        cookie = result.stdout.strip()
        if result.returncode == 0 and cookie.startswith('v='):
            _ths_cookie_cache['cookie'] = cookie
            _ths_cookie_cache['expires_at'] = time.time() + 3600
            data_logger.info("同花顺动态Cookie刷新成功")
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
    target_referer = 'https://q.10jqka.com.cn/thshy/'
    normalized['Host'] = 'q.10jqka.com.cn'
    normalized['Referer'] = target_referer
    normalized['Accept'] = 'text/html, */*; q=0.01'
    normalized['X-Requested-With'] = 'XMLHttpRequest'
    normalized['sec-fetch-dest'] = 'empty'
    normalized['sec-fetch-mode'] = 'cors'
    normalized['sec-fetch-site'] = 'same-origin'

    cookie = normalized.get('Cookie', '')
    if cookie.strip() == 'vvvv=1' or cookie.strip().startswith('checkcookie='):
        normalized.pop('Cookie', None)

    cached_cookie = _get_cached_ths_cookie()
    if cached_cookie and not normalized.get('Cookie'):
        normalized['Cookie'] = cached_cookie

    return normalized

def _parse_ths_number(value, default=0):
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
    from health_checker import get_crawler_status, set_crawler_working, set_crawler_idle, get_shared_headers
    
    crawler_status = get_crawler_status()
    if crawler_status.get('sector_flow', {}).get('status') == 'failed':
        error_logger.warning("板块资金获取已停止，跳过本次获取")
        return []
    
    set_crawler_working('sector_flow')
    # 优先使用健康检测的共享请求头，没有则随机生成
    shared = get_shared_headers()
    if shared:
        headers = normalize_ths_sector_headers(shared)
    else:
        headers = normalize_ths_sector_headers()

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
        refreshed_cookie = refresh_ths_cookie()
        shared_headers = get_shared_headers()
        if shared_headers:
            next_headers = normalize_ths_sector_headers(shared_headers)
        else:
            next_headers = normalize_ths_sector_headers()
        if refreshed_cookie:
            next_headers['Cookie'] = refreshed_cookie
        return next_headers

    def build_net_flow_watchlist(inflow_sectors, outflow_sectors):
        selected = []
        seen = set()

        for item in inflow_sectors[:5]:
            name = item.get('name')
            if not name or name in seen:
                continue
            copied = dict(item)
            copied['flow_group'] = 'net_in'
            selected.append(copied)
            seen.add(name)

        for item in outflow_sectors[:5]:
            name = item.get('name')
            if not name or name in seen:
                continue
            copied = dict(item)
            copied['flow_group'] = 'net_out'
            selected.append(copied)
            seen.add(name)

        for i, sector in enumerate(selected):
            sector['rank'] = i + 1

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
            if retry < max_retries - 1:
                headers = normalize_ths_sector_headers()
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
    from health_checker import get_crawler_status, set_crawler_working, set_crawler_idle, get_shared_headers
    
    if not sector_url:
        error_logger.error("板块URL为空")
        return []
    
    if sector_url.startswith('http://'):
        sector_url = sector_url.replace('http://', 'https://')
    
    from urllib.parse import urlparse
    parsed_url = urlparse(sector_url)
    host = parsed_url.netloc if parsed_url.netloc else 'q.10jqka.com.cn'
    
    set_crawler_working('stocks')
    # 优先使用健康检测的共享请求头，没有则随机生成
    shared = get_shared_headers()
    if shared:
        headers = dict(shared)
        headers['Host'] = host
    else:
        headers = generate_random_headers(host=host)
    
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
                shared = get_shared_headers()
                if shared:
                    headers = dict(shared)
                    headers['Host'] = host
                else:
                    headers = generate_random_headers(host=host)
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
                headers = generate_random_headers(host=host)
        
        except Exception as e:
            if retry < max_retries - 1:
                headers = generate_random_headers(host=host)
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
    
    return get_sina_market_index_data()

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
            if price is None or prev_close in (None, 0):
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
        error_logger.error(f"新浪大盘指数数据格式异常: {response.text[:300]}")
    except Exception as e:
        error_logger.error(f"获取新浪大盘指数数据失败: {e}")

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
    cached_cookie = _get_cached_ths_cookie()
    if cached_cookie:
        headers['Cookie'] = cached_cookie

    try:
        response = requests.get(THS_INDEX_FLASH_URL, headers=headers, timeout=10)
        if response.status_code in (401, 403):
            refreshed_cookie = refresh_ths_cookie()
            if refreshed_cookie:
                headers['Cookie'] = refreshed_cookie
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

    try:
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

    ths_breadth = get_ths_market_breadth()
    breadth = ths_breadth or get_jrj_market_breadth()
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
    ths_breadth = get_ths_market_breadth()
    breadth = ths_breadth or get_jrj_market_breadth() or cached_summary.get('breadth')
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
