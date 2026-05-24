import os
import json
import time
import threading
import traceback
from datetime import datetime
from logger import get_logger
from config import DATA_DIR
import requests
from bs4 import BeautifulSoup

error_logger = get_logger('error')
health_logger = get_logger('health')

HEALTH_DATA_DIR = os.path.join(DATA_DIR, 'health')
HEALTH_FILE = os.path.join(HEALTH_DATA_DIR, 'status.json')

THS_SECTOR_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/tradezdf/order/desc/ajax/1/free/1/"
NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"

if not os.path.exists(HEALTH_DATA_DIR):
    os.makedirs(HEALTH_DATA_DIR)

health_status = {
    'ths_news': {
        'status': 'unknown',
        'last_check': None,
        'error': None,
        'response_time': None
    },
    'ths_sector': {
        'status': 'unknown',
        'last_check': None,
        'error': None,
        'response_time': None,
        'sector_status': 'unknown',
        'stocks_status': 'unknown'
    }
}

_crawler_status = {
    'sector_flow': {
        'status': 'idle',
        'message': '',
        'retrying': False,
        'retry_count': 0
    },
    'news': {
        'status': 'idle',
        'message': '',
        'retrying': False,
        'retry_count': 0
    }
}

def get_news_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://news.10jqka.com.cn/',
    }

def get_sector_headers():
    """服务监控始终生成新请求头进行探测，以发现新的可用请求头"""
    from data_processor import generate_random_headers
    return generate_random_headers()

def _verify_headers_with_url(url, headers, timeout=10):
    """用指定请求头请求URL，验证是否可用。返回 (成功, 响应时间, 错误信息, 响应文本)"""
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(url, headers=headers, timeout=timeout, verify=False)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
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
            text = response.text
            if 'm-table' in text or '板块' in text or '个股' in text:
                return True, response_time, None, text
            return False, response_time, '页面内容异常', text
        return False, response_time, f'HTTP {response.status_code}', None
    except requests.exceptions.Timeout:
        return False, round((time.time() - start_time) * 1000, 2), '请求超时', None
    except requests.exceptions.ConnectionError:
        return False, round((time.time() - start_time) * 1000, 2), '网络连接失败', None
    except Exception as e:
        return False, round((time.time() - start_time) * 1000, 2), str(e)[:30], None

def test_news_api():
    params = {
        'page': 1,
        'tag': '',
        'track': 'website',
        'pagesize': 5
    }
    
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(NEWS_URL, params=params, headers=get_news_headers(), timeout=10, verify=False)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '200' or data.get('data'):
                return True, response_time, None
            return False, response_time, f"API返回错误: {data.get('msg', '未知')}"
        return False, response_time, f'HTTP {response.status_code}'
    except requests.exceptions.Timeout:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, '请求超时'
    except requests.exceptions.ConnectionError:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, '网络连接失败'
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, str(e)[:30]

def extract_stock_url_from_sector(html_content):
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        table = soup.find('table', class_='m-table J-ajax-table')
        if not table:
            return None
        
        tbody = table.find('tbody')
        if not tbody:
            return None
        
        rows = tbody.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 2:
                sector_link = cols[1].find('a')
                if sector_link:
                    sector_url = sector_link.get('href', '')
                    if sector_url:
                        if sector_url.startswith('http://'):
                            sector_url = sector_url.replace('http://', 'https://')
                        return sector_url
        return None
    except Exception as e:
        error_logger.error(f"提取板块URL失败: {e}")
        return None

def test_stock_detail_url(sector_url):
    """测试个股详情URL，优先用主请求头，失败用备用"""
    from data_processor import get_primary_headers, get_backup_headers, generate_random_headers
    from urllib.parse import urlparse
    parsed_url = urlparse(sector_url)
    host = parsed_url.netloc if parsed_url.netloc else 'q.10jqka.com.cn'
    
    # 尝试主请求头
    primary, _ = get_primary_headers()
    if primary:
        headers = dict(primary)
        headers['Host'] = host
        success, response_time, error, _ = _verify_headers_with_url(sector_url, headers)
        if success:
            return True, response_time, None
    
    # 尝试备用请求头
    backup = get_backup_headers()
    if backup:
        headers = dict(backup)
        headers['Host'] = host
        success, response_time, error, _ = _verify_headers_with_url(sector_url, headers)
        if success:
            return True, response_time, None
    
    # 用新请求头
    headers = generate_random_headers(host=host)
    success, response_time, error, _ = _verify_headers_with_url(sector_url, headers)
    if success:
        return True, response_time, None
    
    return False, response_time, error

def test_sector_and_stocks():
    """服务监控：同步验证主请求头，能用立即返回；不能用则尝试备用或探测新请求头"""
    from data_processor import get_primary_headers, get_backup_headers, set_primary_headers, set_backup_headers, promote_backup_to_primary, generate_random_headers
    
    # 第一步：验证主请求头是否还能用
    primary, primary_id = get_primary_headers()
    if primary:
        success, response_time, error, text = _verify_headers_with_url(THS_SECTOR_URL, primary)
        if success:
            # 主请求头可用，立即返回正常，异步探测备用
            health_logger.info("主请求头验证可用，服务正常")
            _probe_backup_async()
            
            sector_success = True
            sector_error = None
            stock_url = extract_stock_url_from_sector(text) if text else None
            if stock_url:
                stocks_success, stocks_time, stocks_error = test_stock_detail_url(stock_url)
            else:
                stocks_success = False
                stocks_time = 0
                stocks_error = '未找到板块详情URL'
            
            return {
                'sector_success': sector_success,
                'sector_time': response_time,
                'sector_error': sector_error,
                'stocks_success': stocks_success,
                'stocks_time': stocks_time,
                'stocks_error': stocks_error
            }
    
    # 第二步：主请求头不可用，尝试备用请求头
    backup = get_backup_headers()
    if backup:
        success, response_time, error, text = _verify_headers_with_url(THS_SECTOR_URL, backup)
        if success:
            # 备用可用，提升为主请求头
            promote_backup_to_primary()
            health_logger.info("主请求头失效，备用请求头提升为主请求头")
            _probe_backup_async()
            
            sector_success = True
            sector_error = None
            stock_url = extract_stock_url_from_sector(text) if text else None
            if stock_url:
                stocks_success, stocks_time, stocks_error = test_stock_detail_url(stock_url)
            else:
                stocks_success = False
                stocks_time = 0
                stocks_error = '未找到板块详情URL'
            
            return {
                'sector_success': sector_success,
                'sector_time': response_time,
                'sector_error': sector_error,
                'stocks_success': stocks_success,
                'stocks_time': stocks_time,
                'stocks_error': stocks_error
            }
    
    # 第三步：主备都不可用，探测新请求头（最多9次）
    max_attempts = 9
    last_error = None
    last_response_time = 0
    
    for attempt in range(max_attempts):
        headers = generate_random_headers()
        success, response_time, error, text = _verify_headers_with_url(THS_SECTOR_URL, headers)
        last_response_time = response_time
        
        if success:
            # 找到可用请求头，设为主请求头
            set_primary_headers(headers)
            health_logger.info(f"服务监控探测到新可用请求头 (第{attempt+1}次尝试)")
            _probe_backup_async()
            
            sector_success = True
            sector_error = None
            stock_url = extract_stock_url_from_sector(text) if text else None
            if stock_url:
                stocks_success, stocks_time, stocks_error = test_stock_detail_url(stock_url)
            else:
                stocks_success = False
                stocks_time = 0
                stocks_error = '未找到板块详情URL'
            
            return {
                'sector_success': sector_success,
                'sector_time': response_time,
                'sector_error': sector_error,
                'stocks_success': stocks_success,
                'stocks_time': stocks_time,
                'stocks_error': stocks_error
            }
        
        last_error = error
        if attempt < max_attempts - 1:
            time.sleep(1)
    
    # 全部失败
    error_logger.warning(f"服务监控板块检测最终失败({last_error})，已尝试{max_attempts}次，板块URL: {THS_SECTOR_URL}")
    return {
        'sector_success': False,
        'sector_time': last_response_time,
        'sector_error': last_error or f'重试{max_attempts}次均失败',
        'stocks_success': False,
        'stocks_time': 0,
        'stocks_error': '板块检测失败'
    }

_backup_probe_thread = None

def _probe_backup_async():
    """异步探测备用请求头"""
    global _backup_probe_thread
    if _backup_probe_thread and _backup_probe_thread.is_alive():
        return
    _backup_probe_thread = threading.Thread(target=_probe_backup, daemon=True)
    _backup_probe_thread.start()

def _probe_backup():
    """探测新的备用请求头，直到找到一个可用的"""
    from data_processor import get_backup_headers, set_backup_headers, generate_random_headers
    # 已有备用则跳过
    if get_backup_headers():
        return
    
    for attempt in range(9):
        headers = generate_random_headers()
        success, _, _, _ = _verify_headers_with_url(THS_SECTOR_URL, headers)
        if success:
            set_backup_headers(headers)
            health_logger.info(f"备用请求头探测成功 (第{attempt+1}次尝试)")
            return
        time.sleep(1)
    
    health_logger.info("备用请求头探测失败，将在下次健康检查时重试")

_health_check_thread = None

def _run_health_check_safe():
    """带异常捕获的健康检查，确保任何报错都记录到日志"""
    try:
        run_health_check()
    except Exception as e:
        error_logger.error(f"健康检查执行异常: {e}\n{traceback.format_exc()}")

def run_health_check_async():
    """异步执行健康检查，避免阻塞HTTP请求"""
    global _health_check_thread
    if _health_check_thread and _health_check_thread.is_alive():
        health_logger.info("健康检查正在执行中，跳过本次请求")
        return
    _health_check_thread = threading.Thread(target=_run_health_check_safe, daemon=True)
    _health_check_thread.start()
    health_logger.info("健康检查已异步启动")

def run_health_check():
    global health_status
    
    health_status = {
        'ths_news': {
            'status': 'unknown',
            'last_check': None,
            'error': None,
            'response_time': None
        },
        'ths_sector': {
            'status': 'unknown',
            'last_check': None,
            'error': None,
            'response_time': None,
            'sector_status': 'unknown',
            'stocks_status': 'unknown'
        }
    }
    
    news_success, news_time, news_error = test_news_api()
    health_status['ths_news'] = {
        'status': 'ok' if news_success else 'error',
        'last_check': datetime.now().isoformat(),
        'error': news_error,
        'response_time': news_time
    }
    
    sector_result = test_sector_and_stocks()
    
    if sector_result['sector_success'] and sector_result['stocks_success']:
        overall_status = 'ok'
    elif sector_result['sector_success']:
        overall_status = 'partial'
    else:
        overall_status = 'error'
    
    health_status['ths_sector'] = {
        'status': overall_status,
        'last_check': datetime.now().isoformat(),
        'error': sector_result['sector_error'],
        'response_time': sector_result['sector_time'],
        'sector_status': 'ok' if sector_result['sector_success'] else 'error',
        'stocks_status': 'ok' if sector_result['stocks_success'] else 'error'
    }
    
    save_health_status()
    
    result = {
        'news': news_success,
        'sector': sector_result['sector_success'],
        'stocks': sector_result['stocks_success']
    }
    
    return result

def get_health_status():
    return health_status

def save_health_status():
    try:
        with open(HEALTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(health_status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f"保存健康状态失败: {e}")

def load_health_status():
    global health_status
    try:
        if os.path.exists(HEALTH_FILE):
            with open(HEALTH_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved:
                    health_status = saved
    except Exception as e:
        error_logger.error(f"加载健康状态失败: {e}")

def get_crawler_status():
    return _crawler_status

def set_crawler_working(crawler_name):
    if crawler_name in _crawler_status:
        _crawler_status[crawler_name]['status'] = 'working'
        _crawler_status[crawler_name]['message'] = '正在获取数据...'

def set_crawler_idle(crawler_name):
    if crawler_name in _crawler_status:
        _crawler_status[crawler_name]['status'] = 'idle'
        _crawler_status[crawler_name]['message'] = ''
        _crawler_status[crawler_name]['retrying'] = False
        _crawler_status[crawler_name]['retry_count'] = 0

def set_crawler_failed(crawler_name, message='', retrying=False):
    if crawler_name in _crawler_status:
        _crawler_status[crawler_name]['status'] = 'failed'
        _crawler_status[crawler_name]['message'] = message
        _crawler_status[crawler_name]['retrying'] = retrying
        if retrying:
            _crawler_status[crawler_name]['retry_count'] += 1

def set_crawler_checking(crawler_name):
    if crawler_name in _crawler_status:
        _crawler_status[crawler_name]['status'] = 'checking'
        _crawler_status[crawler_name]['message'] = '检测中...'

def load_crawler_status():
    pass
