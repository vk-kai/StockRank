import os
import json
import time
from datetime import datetime
from logger import get_logger
from config import DATA_DIR
import requests

error_logger = get_logger('error')
health_logger = get_logger('health')

HEALTH_DATA_DIR = os.path.join(DATA_DIR, 'health')
HEALTH_FILE = os.path.join(HEALTH_DATA_DIR, 'status.json')

THS_SECTOR_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/tradezdf/order/desc/ajax/1/"
THS_STOCKS_URL = "https://q.10jqka.com.cn/gn/detail/code/301466/"
NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"

if not os.path.exists(HEALTH_DATA_DIR):
    os.makedirs(HEALTH_DATA_DIR)

health_status = {
    'ths_sector': {
        'status': 'unknown',
        'last_check': None,
        'error': None,
        'response_time': None
    },
    'ths_stocks': {
        'status': 'unknown',
        'last_check': None,
        'error': None,
        'response_time': None
    },
    'news': {
        'status': 'unknown',
        'last_check': None,
        'error': None,
        'response_time': None
    }
}

_crawler_status = {
    'sector_flow': {
        'status': 'idle',
        'message': '',
        'retrying': False,
        'retry_count': 0
    },
    'stocks': {
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

def check_url_with_headers(url, headers, timeout=15):
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            # 检查是否是重定向页面
            if '<script' in response.text and 'window.location.href' in response.text:
                # 提取重定向URL
                import re
                match = re.search(r'window.location.href="(.*?)";', response.text)
                if match:
                    redirect_url = match.group(1)
                    if not redirect_url.startswith('http'):
                        redirect_url = f'https:{redirect_url}' if redirect_url.startswith('//') else f'https://data.10jqka.com.cn{redirect_url}'
                    # 跟随重定向
                    response = session.get(redirect_url, headers=headers, timeout=timeout, verify=False, allow_redirects=True)
                    if response.status_code !=200:
                        return {
                            'success': False,
                            'status_code': response.status_code,
                            'response_time': response_time,
                            'error': f'重定向后HTTP状态码: {response.status_code}'
                        }
            # 处理编码
            if response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            else:
                response.encoding = response.apparent_encoding
            return {
                'success': True,
                'status_code': response.status_code,
                'response_time': response_time,
                'content': response.text[:500]
            }
        else:
            return {
                'success': False,
                'status_code': response.status_code,
                'response_time': response_time,
                'error': f'HTTP状态码: {response.status_code}'
            }
    except requests.exceptions.Timeout:
        response_time = round((time.time() - start_time) * 1000, 2)
        return {
            'success': False,
            'response_time': response_time,
            'error': '请求超时'
        }
    except requests.exceptions.ConnectionError as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return {
            'success': False,
            'response_time': response_time,
            'error': f'连接错误: {str(e)[:100]}'
        }
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return {
            'success': False,
            'response_time': response_time,
            'error': f'未知错误: {str(e)[:100]}'
        }

def test_ths_sector_headers(headers):
    result = check_url_with_headers(THS_SECTOR_URL, headers)
    if result['success']:
        return True, result['response_time'], None
    return False, result.get('response_time', 0), result.get('error', '未知错误')

def test_ths_stocks_headers(headers):
    result = check_url_with_headers(THS_STOCKS_URL, headers)
    if result['success']:
        return True, result['response_time'], None
    return False, result.get('response_time', 0), result.get('error', '未知错误')

def test_news_headers(headers):
    params = {
        'page': 1,
        'tag': '',
        'track': 'website',
        'pagesize': 10
    }
    
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(NEWS_URL, params=params, headers=headers, timeout=15, verify=False, allow_redirects=True)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            return True, response_time, None
        else:
            return False, response_time, f'HTTP状态码: {response.status_code}'
    except requests.exceptions.Timeout:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, '请求超时'
    except requests.exceptions.ConnectionError as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, f'连接错误: {str(e)[:50]}'
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, f'未知错误: {str(e)[:50]}'

def find_working_headers_for_sector(max_retries=10):
    from data_processor import generate_random_headers, set_working_headers
    
    global _crawler_status
    _crawler_status['sector_flow']['status'] = 'checking'
    _crawler_status['sector_flow']['retrying'] = True
    _crawler_status['sector_flow']['message'] = '正在检测可用请求头...'
    save_crawler_status()
    
    for i in range(max_retries):
        _crawler_status['sector_flow']['retry_count'] = i + 1
        _crawler_status['sector_flow']['message'] = f'正在尝试第 {i + 1} 次请求头...'
        save_crawler_status()
        
        headers = generate_random_headers()
        success, response_time, error = test_ths_sector_headers(headers)
        
        if success:
            set_working_headers(headers)
            _crawler_status['sector_flow']['status'] = 'working'
            _crawler_status['sector_flow']['retrying'] = False
            _crawler_status['sector_flow']['message'] = ''
            _crawler_status['sector_flow']['retry_count'] = 0
            save_crawler_status()
            
            update_health_status('ths_sector', 'ok', response_time, None)
            health_logger.info(f"板块资金请求头检测成功，响应时间: {response_time}ms")
            return headers
        
        update_health_status('ths_sector', 'error', response_time, error)
        health_logger.warning(f"板块资金请求头检测失败 (第{i+1}次): {error} | URL: {THS_SECTOR_URL} | Headers: {json.dumps(headers, ensure_ascii=False)}")
        time.sleep(1)
    
    _crawler_status['sector_flow']['status'] = 'failed'
    _crawler_status['sector_flow']['retrying'] = False
    _crawler_status['sector_flow']['message'] = f'尝试了 {max_retries} 次请求头均失败，板块资金获取已停止'
    save_crawler_status()
    
    return None

def find_working_headers_for_stocks(max_retries=10):
    from data_processor import generate_random_headers
    
    global _crawler_status
    _crawler_status['stocks']['status'] = 'checking'
    _crawler_status['stocks']['retrying'] = True
    _crawler_status['stocks']['message'] = '正在检测可用请求头...'
    save_crawler_status()
    
    for i in range(max_retries):
        _crawler_status['stocks']['retry_count'] = i + 1
        _crawler_status['stocks']['message'] = f'正在尝试第 {i + 1} 次请求头...'
        save_crawler_status()
        
        headers = generate_random_headers(host='q.10jqka.com.cn', referer=THS_STOCKS_URL)
        success, response_time, error = test_ths_stocks_headers(headers)
        
        if success:
            _crawler_status['stocks']['status'] = 'working'
            _crawler_status['stocks']['retrying'] = False
            _crawler_status['stocks']['message'] = ''
            _crawler_status['stocks']['retry_count'] = 0
            save_crawler_status()
            
            update_health_status('ths_stocks', 'ok', response_time, None)
            health_logger.info(f"个股详情请求头检测成功，响应时间: {response_time}ms")
            return headers
        
        update_health_status('ths_stocks', 'error', response_time, error)
        health_logger.warning(f"个股详情请求头检测失败 (第{i+1}次): {error} | URL: {THS_STOCKS_URL} | Headers: {json.dumps(headers, ensure_ascii=False)}")
        time.sleep(1)
    
    _crawler_status['stocks']['status'] = 'failed'
    _crawler_status['stocks']['retrying'] = False
    _crawler_status['stocks']['message'] = f'尝试了 {max_retries} 次请求头均失败，个股详情获取已停止'
    save_crawler_status()
    
    return None

def find_working_headers_for_news(max_retries=10):
    from data_processor import generate_random_headers
    
    global _crawler_status
    _crawler_status['news']['status'] = 'checking'
    _crawler_status['news']['retrying'] = True
    _crawler_status['news']['message'] = '正在检测可用请求头...'
    save_crawler_status()
    
    for i in range(max_retries):
        _crawler_status['news']['retry_count'] = i + 1
        _crawler_status['news']['message'] = f'正在尝试第 {i + 1} 次请求头...'
        save_crawler_status()
        
        headers = {
            'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{100 + i}.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://news.10jqka.com.cn/',
        }
        success, response_time, error = test_news_headers(headers)
        
        if success:
            _crawler_status['news']['status'] = 'working'
            _crawler_status['news']['retrying'] = False
            _crawler_status['news']['message'] = ''
            _crawler_status['news']['retry_count'] = 0
            save_crawler_status()
            
            update_health_status('news', 'ok', response_time, None)
            health_logger.info(f"新闻请求头检测成功，响应时间: {response_time}ms")
            return headers
        
        update_health_status('news', 'error', response_time, error)
        health_logger.warning(f"新闻请求头检测失败 (第{i+1}次): {error} | URL: {NEWS_URL} | Headers: {json.dumps(headers, ensure_ascii=False)}")
        time.sleep(1)
    
    _crawler_status['news']['status'] = 'failed'
    _crawler_status['news']['retrying'] = False
    _crawler_status['news']['message'] = f'尝试了 {max_retries} 次请求头均失败，新闻获取已停止'
    save_crawler_status()
    
    return None

def update_health_status(key, status, response_time=None, error=None):
    global health_status
    health_status[key] = {
        'status': status,
        'last_check': datetime.now().isoformat(),
        'error': error,
        'response_time': response_time
    }
    save_health_status()

def save_health_status():
    try:
        with open(HEALTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(health_status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f"保存健康状态失败: {e}")

CRAWLER_STATUS_FILE = os.path.join(HEALTH_DATA_DIR, 'crawler_status.json')

def save_crawler_status():
    try:
        with open(CRAWLER_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(_crawler_status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f"保存爬虫状态失败: {e}")

def load_crawler_status():
    if os.path.exists(CRAWLER_STATUS_FILE):
        try:
            with open(CRAWLER_STATUS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    global _crawler_status
                    _crawler_status = json.loads(content)
        except Exception as e:
            error_logger.error(f"加载爬虫状态失败: {e}")
    return _crawler_status

def get_crawler_status():
    return _crawler_status

def load_health_status():
    global health_status
    if os.path.exists(HEALTH_FILE):
        try:
            with open(HEALTH_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    health_status = json.loads(content)
        except Exception as e:
            error_logger.error(f"加载健康状态失败: {e}")
    return health_status

def get_health_status():
    return health_status

def set_crawler_idle(crawler_name):
    global _crawler_status
    if crawler_name in _crawler_status:
        _crawler_status[crawler_name]['status'] = 'idle'
        _crawler_status[crawler_name]['message'] = ''
        _crawler_status[crawler_name]['retrying'] = False
        _crawler_status[crawler_name]['retry_count'] = 0
        save_crawler_status()

def set_crawler_working(crawler_name):
    global _crawler_status
    if crawler_name in _crawler_status:
        _crawler_status[crawler_name]['status'] = 'working'
        _crawler_status[crawler_name]['message'] = ''
        _crawler_status[crawler_name]['retrying'] = False
        save_crawler_status()
