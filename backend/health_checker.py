import os
import json
import time
import threading
import traceback
from datetime import datetime
from logger import get_logger
from config import DATA_DIR, THS_SECTOR_URL, THS_SECTOR_NET_OUT_URL
import requests
from bs4 import BeautifulSoup

error_logger = get_logger('error')
health_logger = get_logger('health')

HEALTH_DATA_DIR = os.path.join(DATA_DIR, 'health')
HEALTH_FILE = os.path.join(HEALTH_DATA_DIR, 'status.json')

NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"

if not os.path.exists(HEALTH_DATA_DIR):
    os.makedirs(HEALTH_DATA_DIR)

# ============ 共享请求头（新闻和板块资金共用） ============
_shared_headers = None

# ============ 健康状态 ============
_health_status = {
    'news': {
        'status': 'checking',
        'last_check': None,
        'error': None,
        'response_time': None
    },
    'sector': {
        'status': 'checking',
        'last_check': None,
        'error': None,
        'response_time': None
    }
}

# ============ 采集器状态 ============
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

# ============ 定时检测线程 ============
_check_thread = None
_check_interval = 60  # 每60秒检测一次
_check_running = False

# ============ 共享请求头接口 ============

def get_shared_headers():
    """兼容旧调用；健康检测不再共享同花顺请求头或 Cookie。"""
    return None

def update_shared_headers(headers):
    return None

def get_news_headers():
    """获取新闻API请求头：优先使用共享请求头"""
    shared = get_shared_headers()
    if shared:
        headers = dict(shared)
        headers['Host'] = 'news.10jqka.com.cn'
        headers['Referer'] = 'https://news.10jqka.com.cn/'
        return headers
    # 无共享请求头时使用默认
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://news.10jqka.com.cn/',
    }

def get_sector_headers():
    """获取板块API请求头：优先使用共享请求头"""
    shared = get_shared_headers()
    from data_processor import generate_random_headers, normalize_ths_sector_headers
    if shared:
        return normalize_ths_sector_headers(shared)
    return normalize_ths_sector_headers(generate_random_headers())

def _is_trading_now():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hour = now.hour
    minute = now.minute
    return (
        (hour == 9 and minute >= 30) or
        (10 <= hour < 11) or
        (hour == 11 and minute <= 30) or
        (13 <= hour < 15) or
        (hour == 15 and minute == 0)
    )

# ============ URL验证工具函数 ============

def _verify_headers_with_url(url, headers, timeout=10):
    """用指定请求头请求URL，验证是否可用。返回 (成功, 响应时间, 错误信息, 响应文本)"""
    start_time = time.time()
    try:
        if '10jqka.com.cn' in url and ('funds/hyzjl' in url or '/thshy/' in url):
            from data_processor import normalize_ths_sector_headers
            headers = normalize_ths_sector_headers(headers)

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

def _test_news_with_headers(headers):
    """用指定请求头测试新闻API。返回 (成功, 响应时间, 错误信息)"""
    news_headers = dict(headers)
    news_headers['Host'] = 'news.10jqka.com.cn'
    news_headers['Referer'] = 'https://news.10jqka.com.cn/'

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
        response = session.get(NEWS_URL, params=params, headers=news_headers, timeout=10, verify=False)
        response_time = round((time.time() - start_time) * 1000, 2)

        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '200' or data.get('data'):
                return True, response_time, None
            return False, response_time, f"API返回错误: {data.get('msg', '未知')}"
        return False, response_time, f'HTTP {response.status_code}'
    except requests.exceptions.Timeout:
        return False, round((time.time() - start_time) * 1000, 2), '新闻请求超时'
    except requests.exceptions.ConnectionError:
        return False, round((time.time() - start_time) * 1000, 2), '新闻网络连接失败'
    except Exception as e:
        return False, round((time.time() - start_time) * 1000, 2), str(e)[:30]

def _test_sector_with_headers(headers):
    in_ok, in_time, in_error, _ = _verify_headers_with_url(THS_SECTOR_URL, headers)
    if not in_ok:
        return False, in_time, in_error

    out_ok, out_time, out_error, _ = _verify_headers_with_url(THS_SECTOR_NET_OUT_URL, headers)
    if not out_ok:
        return False, out_time, out_error

    return True, max(in_time, out_time), None

# ============ 请求头获取 ============

def _acquire_headers(max_attempts=9):
    """尝试获取可用请求头，最多max_attempts次。返回 (headers, 成功)"""
    from data_processor import generate_random_headers, normalize_ths_sector_headers, refresh_ths_cookie

    for attempt in range(max_attempts):
        headers = normalize_ths_sector_headers(generate_random_headers())
        cookie = refresh_ths_cookie(force=True)
        if cookie:
            headers['Cookie'] = cookie
        success, _, error = _test_sector_with_headers(headers)
        if success:
            return headers, True
        if attempt < max_attempts - 1:
            time.sleep(1)

    health_logger.warning(f"获取请求头失败，已尝试{max_attempts}次")
    return None, False

def _acquire_news_headers(max_attempts=5):
    from data_processor import generate_random_headers

    for attempt in range(max_attempts):
        headers = generate_random_headers(host='news.10jqka.com.cn', referer='https://news.10jqka.com.cn/')
        success, _, _ = _test_news_with_headers(headers)
        if success:
            return headers, True
        if attempt < max_attempts - 1:
            time.sleep(1)

    health_logger.warning(f"????????????? {max_attempts} ?")
    return None, False

# ============ 健康检测主逻辑 ============

def run_full_health_check():
    """???????????????????????????"""
    global _health_status

    now = datetime.now().isoformat()
    trading_now = _is_trading_now()
    sector_ok = False
    sector_error = None
    sector_time = 0
    news_ok = False
    news_error = None
    news_time = 0

    if trading_now:
        _, found = _acquire_headers(9)
        if found:
            sector_ok = True
            sector_error = None
        else:
            sector_error = '???????????'
    else:
        sector_ok = True
        sector_error = '??????????????'

    news_headers, found = _acquire_news_headers(5)
    if found:
        news_ok, news_time, news_error = _test_news_with_headers(news_headers)
    else:
        news_error = '????????'

    _health_status['news'] = {
        'status': 'ok' if news_ok else 'error',
        'last_check': now,
        'error': news_error,
        'response_time': news_time
    }
    _health_status['sector'] = {
        'status': 'ok' if sector_ok else 'error',
        'last_check': now,
        'error': sector_error,
        'response_time': sector_time
    }

    save_health_status()

    if not news_ok or (trading_now and not sector_ok):
        health_logger.warning(f"?????????={'??' if news_ok else news_error}???={'??' if sector_ok else sector_error}")

    return _health_status

# ============ ???? ============

def _periodic_check_loop():
    """定时检测循环：每60秒检查一次请求头是否仍然有效"""
    global _check_running

    health_logger.info("定时健康检测线程已启动")

    while _check_running:
        try:
            run_full_health_check()
        except Exception as e:
            error_logger.error(f"定时健康检测异常: {e}\n{traceback.format_exc()}")

        # 等待下一个检测周期
        for _ in range(_check_interval):
            if not _check_running:
                break
            time.sleep(1)

    health_logger.info("定时健康检测线程已停止")

# ============ 启动/停止 ============

def start_health_checker():
    """???????????????????????????"""
    global _check_thread, _check_running

    if _check_running:
        return

    now = datetime.now().isoformat()
    trading_now = _is_trading_now()
    sector_ok = True
    if trading_now:
        _, sector_ok = _acquire_headers(9)

    news_headers, news_found = _acquire_news_headers(5)

    if sector_ok and news_found:
        news_ok, _, news_error = _test_news_with_headers(news_headers)
        _health_status['news'] = {
            'status': 'ok' if news_ok else 'error',
            'last_check': now,
            'error': None if news_ok else news_error,
            'response_time': None
        }
        _health_status['sector'] = {
            'status': 'ok' if sector_ok else 'error',
            'last_check': now,
            'error': None if trading_now else '??????????????',
            'response_time': None
        }
        save_health_status()
    else:
        _health_status['news'] = {'status': 'error', 'last_check': now, 'error': '???????????', 'response_time': None}
        _health_status['sector'] = {
            'status': 'error' if trading_now and not sector_ok else 'ok',
            'last_check': now,
            'error': '???????????' if trading_now and not sector_ok else '??????????????',
            'response_time': None
        }
        save_health_status()
        health_logger.warning('??????????????????????????')

    _check_running = True
    _check_thread = threading.Thread(target=_periodic_check_loop, daemon=True)
    _check_thread.start()

def stop_health_checker():
    """停止定时健康检测"""
    global _check_running
    _check_running = False
    health_logger.info("健康检测已停止")

# ============ 状态查询接口 ============

def get_health_status():
    """获取当前健康状态"""
    return _health_status

def save_health_status():
    """保存健康状态到文件"""
    try:
        with open(HEALTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(_health_status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f"保存健康状态失败: {e}")

def load_health_status():
    """从文件加载健康状态，只加载已知的键（news、sector），忽略旧键"""
    global _health_status
    try:
        if os.path.exists(HEALTH_FILE):
            with open(HEALTH_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved:
                    for key in ('news', 'sector'):
                        if key in saved:
                            _health_status[key] = saved[key]
    except Exception as e:
        error_logger.error(f"加载健康状态失败: {e}")

# ============ 采集器状态管理 ============

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
