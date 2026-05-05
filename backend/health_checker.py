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
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Cookie': 'vvvv=1',
    }

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
            if len(cols) >= 9:
                lead_stock_link = cols[8].find('a')
                if lead_stock_link:
                    stock_url = lead_stock_link.get('href', '')
                    if stock_url:
                        if stock_url.startswith('http://'):
                            stock_url = stock_url.replace('http://', 'https://')
                        return stock_url
        return None
    except Exception as e:
        error_logger.error(f"提取个股URL失败: {e}")
        return None

def test_stock_detail_url(stock_url):
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(stock_url, headers=get_sector_headers(), timeout=10, verify=False)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            if response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            text = response.text
            if 'm-table' in text or '个股' in text or '资金' in text:
                return True, response_time, None
            return False, response_time, '页面内容异常'
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

def test_sector_and_stocks():
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(THS_SECTOR_URL, headers=get_sector_headers(), timeout=10, verify=False)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            if response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            text = response.text
            if 'm-table' in text or '板块' in text:
                sector_success = True
                sector_error = None
                
                stock_url = extract_stock_url_from_sector(text)
                if stock_url:
                    stocks_success, stocks_time, stocks_error = test_stock_detail_url(stock_url)
                else:
                    stocks_success = False
                    stocks_time = 0
                    stocks_error = '未找到个股URL'
                
                return {
                    'sector_success': sector_success,
                    'sector_time': response_time,
                    'sector_error': sector_error,
                    'stocks_success': stocks_success,
                    'stocks_time': stocks_time,
                    'stocks_error': stocks_error
                }
            return {
                'sector_success': False,
                'sector_time': response_time,
                'sector_error': '页面内容异常',
                'stocks_success': False,
                'stocks_time': 0,
                'stocks_error': '板块检测失败'
            }
        return {
            'sector_success': False,
            'sector_time': response_time,
            'sector_error': f'HTTP {response.status_code}',
            'stocks_success': False,
            'stocks_time': 0,
            'stocks_error': '板块检测失败'
        }
    except requests.exceptions.Timeout:
        response_time = round((time.time() - start_time) * 1000, 2)
        return {
            'sector_success': False,
            'sector_time': response_time,
            'sector_error': '请求超时',
            'stocks_success': False,
            'stocks_time': 0,
            'stocks_error': '板块检测失败'
        }
    except requests.exceptions.ConnectionError:
        response_time = round((time.time() - start_time) * 1000, 2)
        return {
            'sector_success': False,
            'sector_time': response_time,
            'sector_error': '网络连接失败',
            'stocks_success': False,
            'stocks_time': 0,
            'stocks_error': '板块检测失败'
        }
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return {
            'sector_success': False,
            'sector_time': response_time,
            'sector_error': str(e)[:30],
            'stocks_success': False,
            'stocks_time': 0,
            'stocks_error': '板块检测失败'
        }

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
