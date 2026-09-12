"""大盘指数与市场摘要（从 data_processor._legacy 拆分）。

G5 大盘指数(上证/深证/创业板 + 全球主要股市指数) + G8 市场摘要(涨跌家数/成交额/综合摘要/缓存)。
latest_market_data dict 是 G5/G8 共享可变状态(indices/stats/summary)，故须同模块；
get_stock_statistics 虽在远处但写 latest_market_data['stats']，一并在此。
依赖 ths_client 的 generate_random_headers/attach_fresh_ths_cookie（同花顺涨跌家数/成交额接口）。
"""
import os
import json
import time
from datetime import datetime

import requests

from core.config import REALTIME_DIR, get_random_user_agent, get_eastmoney_headers, em_request
from ._common import (
    error_logger, _safe_float,
    _parse_json_or_jsonp, _last_list_value, _last_dict_value, _pick_first_number,
    MARKET_INDEX_URL, GLOBAL_INDICES_CACHE_FILE,
)
from .ths_client import generate_random_headers, attach_fresh_ths_cookie


SINA_INDEX_URL = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006"
STOCK_STAT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
THS_INDEX_FLASH_URL = "https://q.10jqka.com.cn/api.php?t=indexflash&"
THS_TURNOVER_MINUTE_URL = "https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data"
JRJ_MARKET_URL = "https://gateway.jrj.com/quot-dc/zdt/market"

latest_market_data = {}
MARKET_SUMMARY_CACHE_FILE = os.path.join(REALTIME_DIR, 'market_summary.json')
MARKET_FAST_REFRESH_SECONDS = 15
MARKET_TURNOVER_REFRESH_SECONDS = 60


def get_eastmoney_market_index_data():
    global latest_market_data
    
    headers = get_eastmoney_headers()
    
    params = {
        'fltt': 2,
        'invt': 2,
        'fields': 'f1,f2,f3,f4,f12,f13,f14',
        'secids': '1.000001,0.399001,0.399006'
    }
    
    try:
        response = em_request(MARKET_INDEX_URL, params=params, headers=headers, timeout=10)
        if response is None:
            raise Exception("东方财富大盘指数请求失败(直连+代理均不可达)")
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

# 全球主要股市指数配置：(名称, 东方财富secid, 新浪代码, 纬度, 经度, 国家/地区, skip_eastmoney)
# skip_eastmoney=True: 跳过东方财富（被反爬或数据不稳定），直接用新浪作为主源
# 注意：同一国家多个指数经纬度需错开，避免地图标签重叠
GLOBAL_INDICES_CONFIG = [
    ('上证指数', '1.000001', 'sh000001', 31.23, 121.47, '中国', False),
    ('沪深300', '1.000300', None, 39.90, 116.40, '中国', False),
    ('恒生指数', '100.HSI', 'int_hangseng', 22.32, 114.17, '香港', False),
    ('台湾加权', '100.TWII', None, 25.03, 121.57, '台湾', False),
    ('日经225', '100.N225', 'int_nikkei', 35.68, 139.69, '日本', False),
    ('韩国KOSPI', '100.KS11', 'b_KOSPI', 37.57, 126.98, '韩国', True),
    ('富时马来西亚', '100.KLSE', None, 3.14, 101.69, '马来西亚', False),
    ('印尼综合', '100.JKSE', None, -6.21, 106.85, '印尼', False),
    ('越南胡志明', '100.VNINDEX', None, 10.78, 106.70, '越南', False),
    ('印度SENSEX', '100.SENSEX', 'b_SENSEX', 19.08, 72.88, '印度', False),
    ('澳大利亚ASX200', '100.AS51', None, -33.87, 151.21, '澳大利亚', False),
    ('道琼斯', '100.DJIA', 'int_dji', 38.90, -77.04, '美国', False),
    ('纳斯达克', '100.NDX', 'int_nasdaq', 40.71, -74.01, '美国', False),
    ('标普500', '100.SPX', 'int_sp500', 41.80, -87.65, '美国', False),
    ('巴西BOVESPA', '100.BVSP', 'int_bovespa', -23.55, -46.63, '巴西', False),
    ('英国富时100', '100.FTSE', 'int_ftse', 51.51, -0.13, '英国', False),
    ('德国DAX30', '100.GDAXI', None, 50.11, 8.68, '德国', False),
    ('法国CAC40', '100.FCHI', None, 48.86, 2.35, '法国', False),
    ('荷兰AEX', '100.AEX', None, 52.37, 4.90, '荷兰', False),
    ('瑞士SMI', '100.SSMI', None, 47.37, 8.54, '瑞士', False),
    ('俄罗斯RTS', '100.RTS', None, 55.75, 37.62, '俄罗斯', False),
]


def _parse_sina_global_indices(sina_text, configs):
    """解析新浪全球指数返回数据，返回 {secid: dict}。"""
    result = {}
    for part in sina_text.split(';'):
        if 'hq_str_' not in part or '="' not in part:
            continue
        key = part.split('hq_str_', 1)[1].split('=', 1)[0]
        values_text = part.split('="', 1)[1].rstrip('"')
        values = values_text.split(',')
        if len(values) < 4:
            continue
        price = None
        change = None
        change_amount = None
        if key.startswith(('sh', 'sz')):
            prev_close = _safe_float(values[2], None)
            p = _safe_float(values[3], None)
            if p is not None and prev_close not in (None, 0):
                price = p
                change_amount = p - prev_close
                change = change_amount / prev_close
        else:
            # 国际指数(int_/b_，4字段格式)：[1]=现价 [2]=涨跌额 [3]=涨跌幅%
            if not values[1]:
                continue
            p = _safe_float(values[1], None)
            cp = _safe_float(values[3], None)
            if p is not None and cp is not None:
                price = p
                change = cp / 100
                change_amount = p * cp / 100
        if price is None:
            continue
        for cfg in configs:
            if cfg[2] == key and cfg[1] not in result:
                name, secid, _, lat, lng, region = cfg[:6]
                result[secid] = {
                    'name': name,
                    'code': secid,
                    'price': round(price, 2),
                    'change': change,
                    'change_amount': round(change_amount or 0, 2),
                    'lat': lat,
                    'lng': lng,
                    'region': region,
                    'source': 'sina'
                }
                break
    return result


# 全球指数内存缓存：前端 30 秒轮询一次，两次轮询间直接复用上次结果，
# 避免每次都同步等新浪+东财两路 HTTP(超时上限 10s×2)，地图打开秒出。
_GLOBAL_INDICES_MEM_CACHE = {'ts': 0.0, 'result': None}
_GLOBAL_INDICES_MEM_TTL = 25.0  # 秒，略小于前端 30s 轮询间隔


def get_global_market_indices():
    """获取全球主要股市指数(新浪主源 + AKShare 保底;少数无新浪代码的指数保留东财)。

    数据源策略(按用户"首选东财才保留"规则):
    - 有新浪代码的指数(上证/恒生/日经/KOSPI/印度/道琼斯/纳指/标普/巴西/英国):
      新浪主源 → AKShare 保底(跳过东财,规避反爬)
    - 无新浪代码的指数(沪深300/台湾加权/德法/马来/印尼/越南/澳洲/荷兰/瑞士/俄罗斯):
      东财是唯一可行源,保留(新浪无代码,AKShare 底层也是东财)
    """
    # 内存缓存命中：TTL 内直接复用上次成功结果(前端 30s 轮询，两次轮询间秒回)
    cached = _GLOBAL_INDICES_MEM_CACHE.get('result')
    if cached is not None and time.time() - _GLOBAL_INDICES_MEM_CACHE['ts'] < _GLOBAL_INDICES_MEM_TTL:
        return cached

    # 拆分:有新浪代码(走新浪,不用东财) vs 无新浪代码(只能东财)
    sina_configs = [cfg for cfg in GLOBAL_INDICES_CONFIG if cfg[2]]
    em_only_configs = [cfg for cfg in GLOBAL_INDICES_CONFIG if not cfg[2]]

    result = {}
    em_ok = False  # 东财(无新浪代码的指数)是否成功,用于返回的 source 标记

    # ---- 源1: 新浪(有新浪代码的指数,主源)----
    if sina_configs:
        try:
            sina_codes = ','.join(cfg[2] for cfg in sina_configs)
            s_headers = {
                'User-Agent': get_random_user_agent(),
                'Referer': 'https://finance.sina.com.cn/'
            }
            s_resp = requests.get("https://hq.sinajs.cn/list=" + sina_codes, headers=s_headers, timeout=10)
            s_resp.encoding = 'gbk'
            sina_result = _parse_sina_global_indices(s_resp.text, sina_configs)
            result.update(sina_result)
        except Exception as e:
            error_logger.warning(f"新浪全球指数获取失败: {e}")

    # ---- 源2: 东方财富(仅无新浪代码的指数——东财是其唯一可行源,保留)----
    if em_only_configs:
        secids = ','.join(cfg[1] for cfg in em_only_configs)
        headers = get_eastmoney_headers()
        params = {
            'fltt': 2,
            'invt': 2,
            'fields': 'f2,f3,f4,f12,f14',
            'secids': secids
        }
        try:
            response = em_request(MARKET_INDEX_URL, params=params, headers=headers, timeout=10)
            if response is not None:
                response.raise_for_status()
                data = response.json()
                diff = data.get('data', {}).get('diff', []) if data.get('data') else []
                em_map = {item.get('f12'): item for item in diff}
                for cfg in em_only_configs:
                    name, secid, _, lat, lng, region = cfg[:6]
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
            error_logger.warning(f"东方财富全球指数(无新浪代码的指数)获取失败: {e}")

    # ---- 源3: AKShare 保底(已移除)----
    # 原 akshare index_global_spot_em 底层走东财,且服务器到东财/akshare 连接常被掐
    # (Connection aborted),快速失败但日志吵。新浪(主源)+ 东财(无新浪代码的)两源已够,
    # 缺失的指数由下方"兜底缓存"用上次成功值补齐。如需恢复可加回。

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
        error_logger.error("全球指数数据获取失败：东方财富/新浪/AKShare 均不可用")
        return None

    indices = list(result.values())
    indices.sort(key=lambda x: x.get('change', 0), reverse=True)
    payload = {
        'indices': indices,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'eastmoney' if em_ok else 'sina'
    }
    _GLOBAL_INDICES_MEM_CACHE['ts'] = time.time()
    _GLOBAL_INDICES_MEM_CACHE['result'] = payload
    return payload


def get_stock_statistics():
    global latest_market_data
    
    headers = get_eastmoney_headers()
    
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
        response = em_request(STOCK_STAT_URL, params=params, headers=headers, timeout=10)
        if response is None:
            raise Exception("东方财富个股统计请求失败(直连+代理均不可达)")
        if response.status_code != 200:
            raise Exception(f"东方财富个股统计请求失败(HTTP {response.status_code})")
        text = response.text
        if not text or len(text) < 10:
            raise Exception("东方财富个股统计返回空响应(可能被反爬拦截)")
        try:
            data = response.json()
        except ValueError:
            raise Exception(f"东方财富个股统计返回非JSON(前80字符: {text[:80]!r})")

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
