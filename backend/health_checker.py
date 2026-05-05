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
    'ths_sector_stocks': {
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

def get_simple_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }

def check_url_simple(url, timeout=15):
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(url, headers=get_simple_headers(), timeout=timeout, verify=False, allow_redirects=True)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            if response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            else:
                response.encoding = response.apparent_encoding
            return {
                'success': True,
                'status_code': response.status_code,
                'response_time': response_time,
                'content': response.text
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
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return {
            'success': False,
            'response_time': response_time,
            'error': f'错误: {str(e)[:100]}'
        }

def test_news_api():
    params = {
        'page': 1,
        'tag': '',
        'track': 'website',
        'pagesize': 10
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://news.10jqka.com.cn/',
    }
    
    start_time = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(NEWS_URL, params=params, headers=headers, timeout=30, verify=False)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            return True, response_time, None
        return False, response_time, f'HTTP状态码: {response.status_code}'
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, str(e)[:50]

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
        response = session.get(stock_url, headers=get_simple_headers(), timeout=15, verify=False)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        if response.status_code == 200:
            return True, response_time, None
        return False, response_time, f'HTTP状态码: {response.status_code}'
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000, 2)
        return False, response_time, str(e)[:50]

def run_health_check():
    global health_status
    
    health_logger.info("开始健康检测...")
    
    news_success = False
    sector_success = False
    stocks_success = False
    
    health_status['ths_news']['status'] = 'checking'
    health_status['ths_news']['last_check'] = datetime.now().isoformat()
    save_health_status()
    
    success, response_time, error = test_news_api()
    if success:
        news_success = True
        health_status['ths_news'] = {
            'status': 'ok',
            'last_check': datetime.now().isoformat(),
            'error': None,
            'response_time': response_time
        }
        health_logger.info(f"同花顺新闻检测成功，响应时间: {response_time}ms")
    else:
        health_status['ths_news'] = {
            'status': 'error',
            'last_check': datetime.now().isoformat(),
            'error': error,
            'response_time': response_time
        }
        health_logger.warning(f"同花顺新闻检测失败: {error}")
    
    save_health_status()
    
    health_status['ths_sector_stocks']['status'] = 'checking'
    health_status['ths_sector_stocks']['sector_status'] = 'checking'
    health_status['ths_sector_stocks']['last_check'] = datetime.now().isoformat()
    save_health_status()
    
    result = check_url_simple(THS_SECTOR_URL)
    
    if result['success']:
        has_table = 'm-table' in result.get('content', '') or '板块' in result.get('content', '')
        if has_table:
            sector_success = True
            health_status['ths_sector_stocks']['sector_status'] = 'ok'
            health_logger.info(f"同花顺板块资金检测成功，响应时间: {result['response_time']}ms")
            
            stock_url = extract_stock_url_from_sector(result['content'])
            
            if stock_url:
                health_status['ths_sector_stocks']['stocks_status'] = 'checking'
                save_health_status()
                
                stock_success, stock_time, stock_error = test_stock_detail_url(stock_url)
                
                if stock_success:
                    stocks_success = True
                    health_status['ths_sector_stocks']['stocks_status'] = 'ok'
                    health_logger.info(f"同花顺个股详情检测成功，响应时间: {stock_time}ms")
                else:
                    health_status['ths_sector_stocks']['stocks_status'] = 'error'
                    health_logger.warning(f"同花顺个股详情检测失败: {stock_error}")
            else:
                health_status['ths_sector_stocks']['stocks_status'] = 'skipped'
                health_logger.warning("未能从板块数据中提取个股URL")
            
            if sector_success and stocks_success:
                health_status['ths_sector_stocks']['status'] = 'ok'
                health_status['ths_sector_stocks']['response_time'] = result['response_time']
                health_status['ths_sector_stocks']['error'] = None
            elif sector_success:
                health_status['ths_sector_stocks']['status'] = 'partial'
                health_status['ths_sector_stocks']['response_time'] = result['response_time']
                health_status['ths_sector_stocks']['error'] = '个股详情检测失败'
            else:
                health_status['ths_sector_stocks']['status'] = 'error'
                health_status['ths_sector_stocks']['error'] = '板块数据解析失败'
        else:
            health_status['ths_sector_stocks']['status'] = 'error'
            health_status['ths_sector_stocks']['sector_status'] = 'error'
            health_status['ths_sector_stocks']['error'] = '页面内容无板块数据'
            health_logger.warning("同花顺板块资金检测失败: 页面内容无板块数据")
    else:
        health_status['ths_sector_stocks']['status'] = 'error'
        health_status['ths_sector_stocks']['sector_status'] = 'error'
        health_status['ths_sector_stocks']['error'] = result.get('error', '未知错误')
        health_status['ths_sector_stocks']['stocks_status'] = 'skipped'
        health_logger.warning(f"同花顺板块资金检测失败: {result.get('error')}")
    
    health_status['ths_sector_stocks']['last_check'] = datetime.now().isoformat()
    save_health_status()
    
    health_logger.info(f"健康检测完成: 新闻={news_success}, 板块={sector_success}, 个股={stocks_success}")
    
    return {
        'news': news_success,
        'sector': sector_success,
        'stocks': stocks_success
    }

def find_working_headers_for_sector(max_retries=3):
    from data_processor import generate_random_headers, set_working_headers
    
    global _crawler_status
    _crawler_status['sector_flow']['status'] = 'checking'
    _crawler_status['sector_flow']['retrying'] = True
    _crawler_status['sector_flow']['message'] = '正在检测...'
    save_crawler_status()
    
    for i in range(max_retries):
        _crawler_status['sector_flow']['retry_count'] = i + 1
        save_crawler_status()
        
        headers = generate_random_headers()
        result = check_url_simple(THS_SECTOR_URL)
        
        if result['success'] and ('m-table' in result.get('content', '') or '板块' in result.get('content', '')):
            set_working_headers(headers)
            _crawler_status['sector_flow']['status'] = 'working'
            _crawler_status['sector_flow']['retrying'] = False
            _crawler_status['sector_flow']['message'] = ''
            _crawler_status['sector_flow']['retry_count'] = 0
            save_crawler_status()
            
            update_health_status('ths_sector_stocks', 'ok', result['response_time'], None)
            health_logger.info(f"板块资金检测成功，响应时间: {result['response_time']}ms")
            return headers
        
        update_health_status('ths_sector_stocks', 'error', result.get('response_time', 0), result.get('error'))
        health_logger.warning(f"板块资金检测失败 (第{i+1}次): {result.get('error')}")
        time.sleep(1)
    
    _crawler_status['sector_flow']['status'] = 'failed'
    _crawler_status['sector_flow']['retrying'] = False
    _crawler_status['sector_flow']['message'] = f'尝试了 {max_retries} 次均失败'
    save_crawler_status()
    
    return None

def find_working_headers_for_news(max_retries=3):
    global _crawler_status
    _crawler_status['news']['status'] = 'checking'
    _crawler_status['news']['retrying'] = True
    _crawler_status['news']['message'] = '正在检测...'
    save_crawler_status()
    
    for i in range(max_retries):
        _crawler_status['news']['retry_count'] = i + 1
        save_crawler_status()
        
        success, response_time, error = test_news_api()
        
        if success:
            _crawler_status['news']['status'] = 'working'
            _crawler_status['news']['retrying'] = False
            _crawler_status['news']['message'] = ''
            _crawler_status['news']['retry_count'] = 0
            save_crawler_status()
            
            update_health_status('ths_news', 'ok', response_time, None)
            health_logger.info(f"新闻检测成功，响应时间: {response_time}ms")
            return get_simple_headers()
        
        update_health_status('ths_news', 'error', response_time, error)
        health_logger.warning(f"新闻检测失败 (第{i+1}次): {error}")
        time.sleep(1)
    
    _crawler_status['news']['status'] = 'failed'
    _crawler_status['news']['retrying'] = False
    _crawler_status['news']['message'] = f'尝试了 {max_retries} 次均失败'
    save_crawler_status()
    
    return None

def update_health_status(key, status, response_time=None, error=None):
    global health_status
    if key in health_status:
        health_status[key]['status'] = status
        health_status[key]['last_check'] = datetime.now().isoformat()
        health_status[key]['error'] = error
        health_status[key]['response_time'] = response_time
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
