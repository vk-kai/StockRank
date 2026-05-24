import os
import json
import time
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
    start_time = time.time()
    try:
        from urllib.parse import urlparse
        parsed_url = urlparse(sector_url)
        host = parsed_url.netloc if parsed_url.netloc else 'q.10jqka.com.cn'
        
        # 优先使用已保存的可用请求头
        from data_processor import get_working_headers, generate_random_headers
        saved_headers, _ = get_working_headers()
        if not saved_headers:
            headers = generate_random_headers(host=host)
        else:
            # 替换Host为当前请求的host
            headers = dict(saved_headers)
            headers['Host'] = host
        
        session = requests.Session()
        session.trust_env = False
        response = session.get(sector_url, headers=headers, timeout=10, verify=False)
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
            if 'm-table' in text or '个股' in text or '资金' in text:
                return True, response_time, None
            html_preview = text[:500] if text else '(空响应)'
            return False, response_time, f'页面内容异常，HTML预览: {html_preview}'
        response_preview = response.text[:500] if response.text else '(空响应)'
        return False, response_time, f'HTTP {response.status_code}，返回内容: {response_preview}'
    except requests.exceptions.Timeout:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, '请求超时'
    except requests.exceptions.ConnectionError:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, '网络连接失败'
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, str(e)[:30]

def test_sector_and_stocks():
    max_retries = 3
    retry_delay = 2
    last_error = None
    last_response_time = 0
    
    for attempt in range(max_retries):
        start_time = time.time()
        try:
            session = requests.Session()
            session.trust_env = False
            headers = get_sector_headers()
            response = session.get(THS_SECTOR_URL, headers=headers, timeout=10, verify=False)
            response_time = round((time.time() - start_time) * 1000, 2)
            last_response_time = response_time
            
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
                if 'm-table' in text or '板块' in text:
                    # 探测成功，保存可用的请求头
                    from data_processor import set_working_headers
                    set_working_headers(headers)
                    health_logger.info(f"服务监控探测到可用请求头并已保存")
                    
                    sector_success = True
                    sector_error = None
                    
                    stock_url = extract_stock_url_from_sector(text)
                    if stock_url:
                        stocks_success, stocks_time, stocks_error = test_sector_detail_url_with_retry(stock_url)
                    else:
                        stocks_success = False
                        stocks_time = 0
                        stocks_error = '未找到板块详情URL'
                        html_preview = text[:500] if text else '(空响应)'
                        error_logger.warning(f"未找到板块详情URL，板块URL: {THS_SECTOR_URL}，HTML内容预览: {html_preview}")
                    
                    return {
                        'sector_success': sector_success,
                        'sector_time': response_time,
                        'sector_error': sector_error,
                        'stocks_success': stocks_success,
                        'stocks_time': stocks_time,
                        'stocks_error': stocks_error
                    }
                last_error = '页面内容异常'
                html_preview = text[:500] if text else '(空响应)'
                error_logger.warning(f"板块检测失败(页面内容异常)，板块URL: {THS_SECTOR_URL}，HTML内容预览: {html_preview}")
            else:
                last_error = f'HTTP {response.status_code}'
                response_preview = response.text[:500] if response.text else '(空响应)'
                error_logger.warning(f"板块检测失败(HTTP {response.status_code})，板块URL: {THS_SECTOR_URL}，返回内容: {response_preview}")
            
            if attempt < max_retries - 1:
                error_logger.warning(f"板块检测失败({last_error})，第{attempt + 1}次重试，立即更换请求头...")
                time.sleep(retry_delay)
            else:
                error_logger.warning(f"板块检测失败({last_error})，已重试{max_retries}次")
                
        except requests.exceptions.Timeout:
            last_response_time = round((time.time() - start_time) * 1000, 2)
            last_error = '请求超时'
            if attempt < max_retries - 1:
                error_logger.warning(f"板块检测失败({last_error})，板块URL: {THS_SECTOR_URL}，第{attempt + 1}次重试，立即更换请求头...")
                time.sleep(retry_delay)
            else:
                error_logger.warning(f"板块检测失败({last_error})，板块URL: {THS_SECTOR_URL}，已重试{max_retries}次")
        except requests.exceptions.ConnectionError:
            last_response_time = round((time.time() - start_time) * 1000, 2)
            last_error = '网络连接失败'
            if attempt < max_retries - 1:
                error_logger.warning(f"板块检测失败({last_error})，板块URL: {THS_SECTOR_URL}，第{attempt + 1}次重试，立即更换请求头...")
                time.sleep(retry_delay)
            else:
                error_logger.warning(f"板块检测失败({last_error})，板块URL: {THS_SECTOR_URL}，已重试{max_retries}次")
        except Exception as e:
            last_response_time = round((time.time() - start_time) * 1000, 2)
            last_error = str(e)[:30]
            if attempt < max_retries - 1:
                error_logger.warning(f"板块检测失败({last_error})，板块URL: {THS_SECTOR_URL}，第{attempt + 1}次重试，立即更换请求头...")
                time.sleep(retry_delay)
            else:
                error_logger.warning(f"板块检测失败({last_error})，板块URL: {THS_SECTOR_URL}，已重试{max_retries}次")
    
    return {
        'sector_success': False,
        'sector_time': last_response_time,
        'sector_error': last_error or '重试3次均失败',
        'stocks_success': False,
        'stocks_time': 0,
        'stocks_error': '板块检测失败'
    }

def test_sector_detail_url_with_retry(sector_url):
    max_retries = 3
    retry_delay = 2
    last_result = (False, 0, '未知错误')
    
    for attempt in range(max_retries):
        result = test_stock_detail_url(sector_url)
        if result[0]:
            return result
        last_result = result
        error = result[2]
        if attempt < max_retries - 1:
            error_logger.warning(f"个股检测失败({error})，个股URL: {sector_url}，第{attempt + 1}次重试，立即更换请求头...")
            time.sleep(retry_delay)
        else:
            error_logger.warning(f"个股检测失败({error})，个股URL: {sector_url}，已重试{max_retries}次")
    
    return last_result

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
