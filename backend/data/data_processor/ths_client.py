"""同花顺(THS)采集客户端（从 data_processor._legacy 拆分）。

板块资金流向(get_sector_flow_data) / 板块个股(get_sector_stocks) 采集：
代理池、Cookie 现场生成与刷新、请求头构造、HTML 解析。
含跨模块共享的“最新板块资金数据” accessor get_latest_data()，替代原先会被 global 重绑定
导致外部引用失效的裸 latest_data 变量。
"""
import os
import random
import shutil
import signal
import string
import subprocess
import sys
import tempfile
import threading
import time
from bs4 import BeautifulSoup

import requests

from core.config import USE_PROXY, THS_SECTOR_URL, THS_SECTOR_NET_IN_URL, THS_SECTOR_NET_IN_URLS, THS_SECTOR_NET_OUT_URL
from ._common import error_logger, data_logger, system_logger, _parse_ths_number, _parse_ths_int


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

# 跨模块共享的“最新板块资金数据”：用 dict 容器承载，避免 global 重绑定导致外部 import 引用失效
_state = {'latest_data': []}


def get_latest_data():
    """返回最新板块资金数据（accessor）。

    get_sector_flow_data 每次成功会更新 _state['latest_data']；flow_routes 等外部模块
    应调用本函数，不要 import 裸变量（原 latest_data 被 global 重绑定，外部拿到恒空列表）。
    """
    return _state['latest_data']


_ths_cookie_lock = threading.Lock()
# 同花顺 cookie 全局缓存:成功获取后 10 分钟内复用,避免每次采集/健康检查都拉起 Chromium
_ths_cookie_cache = {"value": "", "ts": 0.0, "refreshing": False}
_THS_COOKIE_CACHE_TTL = 600  # 秒(10 分钟)

def _generate_random_string(length):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def _generate_random_cookie():
    return ''

# ths_cookie_refresh.py 是 data_processor 包的同级脚本(位于 backend/data/)。
# 包改成目录后 __file__ 落在包内，须取“包父目录”才能定位脚本——用 2 层 dirname，
# 对函数在包内哪个子模块都稳健（单层 dirname 会错指到包内 → 脚本找不到）。
_THS_COOKIE_REFRESH_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ths_cookie_refresh.py')


def _ths_cache_valid(force):
    """缓存是否仍可复用:非强制、有值、未过期。"""
    return (not force
            and _ths_cookie_cache["value"]
            and (time.time() - _ths_cookie_cache["ts"]) < _THS_COOKIE_CACHE_TTL)


def refresh_ths_cookie(force=False):
    # 命中缓存(非强制、未过期)直接返回,避免重复拉起 Chromium
    if _ths_cache_valid(force):
        return _ths_cookie_cache["value"]

    script_path = _THS_COOKIE_REFRESH_SCRIPT
    if not os.path.exists(script_path):
        error_logger.error(f"同花顺Cookie刷新脚本不存在: {script_path}")
        # fail-soft: 返回上次缓存(可能为空),与下方失败分支一致
        return _ths_cookie_cache["value"]

    # 持锁仅做"缓存二次确认 + refreshing 标志读写";subprocess 在锁外执行。
    # 否则一次 45s 刷新会把业务采集与健康检查互相串行卡死(锁竞争放大单次超时影响)。
    with _ths_cookie_lock:
        if _ths_cache_valid(force):
            return _ths_cookie_cache["value"]
        if _ths_cookie_cache["refreshing"]:
            # 已有线程在拉 Chromium:本次不阻塞排队,尽量复用缓存(哪怕已过期),
            # 刷新完成后下一次调用即可拿到新值。
            return _ths_cookie_cache["value"]
        _ths_cookie_cache["refreshing"] = True

    try:
        result = subprocess.run(
            [sys.executable, script_path, THS_SECTOR_URL],
            capture_output=True,
            text=True,
            timeout=90
        )
        cookie = result.stdout.strip()
        if result.returncode == 0 and cookie.startswith('v='):
            with _ths_cookie_lock:
                _ths_cookie_cache["value"] = cookie
                _ths_cookie_cache["ts"] = time.time()
            return cookie

        error_logger.error(f"同花顺动态Cookie刷新失败: {result.stderr.strip() or result.stdout.strip()}")
    except subprocess.TimeoutExpired as e:
        # 超时时子脚本可能已输出关键诊断信息(chromium报错/页面forbidden/端口未就绪)，
        # TimeoutExpired.stderr 携带已捕获的输出，必须打出来否则只剩干巴巴的"超时"无法定位。
        stderr_tail = (e.stderr or '').strip()[-1500:] if isinstance(e.stderr, str) else ''
        stdout_tail = (e.stdout or '').strip()[-500:] if isinstance(e.stdout, str) else ''
        detail = stderr_tail or stdout_tail or '(子脚本无输出)'
        error_logger.error(f"同花顺动态Cookie刷新超时(45s)。子脚本输出: {detail}")
        # 超时后清理残留的 chromium 进程（子脚本被 kill 时 finally 可能来不及执行）
        _kill_orphan_chromium()
    except Exception as e:
        error_logger.error(f"同花顺动态Cookie刷新异常: {e}")
    finally:
        with _ths_cookie_lock:
            _ths_cookie_cache["refreshing"] = False

    # fail-soft: 刷新失败时优先返回上次成功获取的 cookie(过期也用),
    # 让业务请求有机会继续成功,避免一次 Chromium 抖动导致整轮采集空数据(折线图缺点)。
    # 首次启动尚无缓存时返回 ''(由调用方重试逻辑兜底),行为与改造前一致。
    with _ths_cookie_lock:
        return _ths_cookie_cache["value"]


def _kill_orphan_chromium():
    """清理残留的 chromium 孤儿进程（ths-cookie- 临时 profile 关联的进程）。"""
    try:
        import glob as _glob
        # 查找所有 ths-cookie- 开头的临时目录，提取关联的 chromium 进程
        if os.name == 'nt':
            # Windows: 用 taskkill 杀 chromium 进程
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'],
                           capture_output=True, timeout=5)
            subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'],
                           capture_output=True, timeout=5)
        else:
            # Linux: pkill 匹配 ths-cookie- 的 chromium 进程
            subprocess.run(
                ['pkill', '-f', 'ths-cookie-'],
                capture_output=True, timeout=5
            )
        # 清理残留临时目录
        tmp_dir = tempfile.gettempdir()
        for d in _glob.glob(os.path.join(tmp_dir, 'ths-cookie-*')):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
    except Exception as e:
        error_logger.error(f"清理残留chromium进程失败: {e}")

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

def attach_fresh_ths_cookie(headers, force=False):
    cookie = refresh_ths_cookie(force=force)
    if cookie:
        headers['Cookie'] = cookie
    return headers


def parse_ths_sector_html(html_content, request_url=''):
    """解析同花顺板块资金流向HTML"""
    soup = BeautifulSoup(html_content, 'html.parser')
    sectors = []

    # 同花顺改版可能调整表格 class，按优先级回退：精确 class → 任意 m-table → 行数最多的表格
    table = soup.find('table', class_='m-table J-ajax-table')
    if not table:
        table = soup.find('table', class_=lambda c: c and 'm-table' in c)
    if not table:
        candidates = soup.find_all('table')
        if candidates:
            table = max(candidates, key=lambda t: len(t.find_all('tr')))
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
    from monitors.health_checker import get_crawler_status, set_crawler_working, set_crawler_idle
    
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
        # 401/403 认证失败:旧 cookie 已失效,强刷一份新的(绕过缓存)
        return attach_fresh_ths_cookie(normalize_ths_sector_headers(), force=True)

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
    
    max_retries = 3  # cookie 全局缓存后 3 次足够;过多只会徒增 Chromium 启动
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

            # 净流入页：遍历候选路由(新版 DESC/free → 旧版 desc)，哪个返回数据用哪个
            inflow_sectors = None
            inflow_url_used = None
            for in_url in THS_SECTOR_NET_IN_URLS:
                response, inflow_sectors = fetch_sector_page(session, in_url, headers, proxies)
                if response.status_code == 401 or response.status_code == 403:
                    headers = refresh_headers_after_auth_error()
                    inflow_sectors = None
                    break  # cookie 失效，换 URL 无意义，直接进下一轮 retry
                if inflow_sectors:
                    inflow_url_used = in_url
                    break
            if response.status_code in (401, 403):
                continue
            if not inflow_sectors:
                error_logger.error(f"所有净流入路由均无数据: {THS_SECTOR_NET_IN_URLS}")

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
                _state['latest_data'] = sectors
                from data.data_collector import is_trading_day, is_trading_time
                from datetime import datetime
                now = datetime.now()
                if is_trading_day(now) and is_trading_time(now):
                    data_logger.info(f"成功获取 {len(sectors)} 个板块数据")
                set_crawler_idle('sector_flow')
                return sectors
            else:
                html_preview = response.text[:1000] if response.text else '(空响应)'
                in_url_log = inflow_url_used or THS_SECTOR_NET_IN_URLS
                error_logger.error(f"解析板块数据失败，返回空列表，流入URL: {in_url_log} / 流出URL: {THS_SECTOR_NET_OUT_URL}，HTML内容预览: {html_preview}")
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
        table = soup.find('table', class_=lambda c: c and 'm-table' in c)
    if not table:
        candidates = soup.find_all('table')
        if candidates:
            table = max(candidates, key=lambda t: len(t.find_all('tr')))
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
    # 内存缓存：同板块 5 分钟内复用，避免反复爬同花顺（个股列表日内变化小）
    import time as _time
    if not hasattr(get_sector_stocks, '_cache'):
        get_sector_stocks._cache = {}
    _cached = get_sector_stocks._cache.get(sector_url)
    if _cached and _time.time() - _cached[0] < 300:
        return _cached[1]

    from monitors.health_checker import get_crawler_status, set_crawler_working, set_crawler_idle

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
    
    max_retries = 2
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
                get_sector_stocks._cache[sector_url] = (_time.time(), stocks)
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
                time.sleep(1)
    
    error_logger.error(f"个股数据获取最终失败，已尝试 {max_retries} 次，URL: {sector_url}")
    set_crawler_idle('stocks')
    return []
