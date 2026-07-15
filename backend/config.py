import os
import random
import string
import json
import requests
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BASE_DIR == '/':
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, 'data')
DAILY_DIR = os.path.join(DATA_DIR, 'daily')
REALTIME_DIR = os.path.join(DATA_DIR, 'realtime')
NEWS_DIR = os.path.join(DATA_DIR, 'news')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')

MAX_DAYS = 30
MAX_NEWS_HOURS = 48

DATA_URL = "https://push2.eastmoney.com/api/qt/clist/get"
NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"
THS_SECTOR_NET_IN_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/je/order/desc/ajax/1/"
THS_SECTOR_NET_OUT_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/je/order/asc/ajax/1/"
THS_SECTOR_URL = THS_SECTOR_NET_IN_URL

USE_PROXY = False

# 东方财富专用代理池（IP被封时自动使用）
EM_PROXY_POOL = []
EM_PROXY_ENABLED = True  # 开关：东方财富请求失败时自动尝试代理

# 东方财富反爬绕过：专用请求头生成（模拟真实浏览器完整指纹）
def get_eastmoney_headers():
    """生成东方财富API请求头，模拟真实浏览器行为以绕过反爬检测。
    东方财富反爬检测点：User-Agent、Referer、Accept-Encoding、Connection、Cookie(cb参数)。
    """
    ua = get_random_user_agent()
    # cb 是东方财富前端JS动态生成的校验参数，不同接口有不同值
    # push2 接口的典型 cb 值格式：jQuery + 时间戳
    import time as _time
    cb = f"jQuery{random.randint(1111111, 9999999)}_{int(_time.time() * 1000)}"
    return {
        'User-Agent': ua,
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://quote.eastmoney.com/',
        'Connection': 'keep-alive',
        'Cookie': f'qgqp_b_id={_gen_eastmoney_cookie_id()}; cb={cb}',
    }

def _gen_eastmoney_cookie_id():
    """模拟东方财富前端生成的浏览器指纹cookie值"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(32))

def is_dev_mode():
    return os.environ.get('STOCKRANK_ENV', 'prod') == 'dev'

def get_random_user_agent():
    browsers = ['Chrome', 'Firefox', 'Safari', 'Edge']
    browser = random.choice(browsers)
    
    chrome_version = f"{random.randint(100, 125)}.0.{random.randint(1000, 9999)}.{random.randint(10, 999)}"
    firefox_version = random.randint(100, 125)
    safari_version = f"{random.randint(600, 620)}.{random.randint(1, 15)}.{random.randint(1, 15)}"
    edge_version = f"{random.randint(100, 125)}.0.{random.randint(1000, 9999)}.{random.randint(10, 999)}"
    
    webkit_version = f"{random.randint(535, 538)}.{random.randint(1, 99)}"
    gecko_version = f"{random.randint(2010, 2025)}{random.randint(1, 12):02d}{random.randint(1, 28):02d}"
    
    platforms = [
        ('Windows NT 10.0; Win64; x64', 'Windows'),
        ('Windows NT 10.0; Win64; x64', 'Windows'),
        ('Macintosh; Intel Mac OS X 10_15_7', 'Mac'),
        ('Macintosh; Intel Mac OS X 11_0_0', 'Mac'),
        ('X11; Linux x86_64', 'Linux'),
        ('X11; Ubuntu; Linux x86_64', 'Linux'),
    ]
    
    platform, os_type = random.choice(platforms)
    
    if browser == 'Chrome':
        return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Chrome/{chrome_version} Safari/{webkit_version}"
    elif browser == 'Firefox':
        return f"Mozilla/5.0 ({platform}; rv:{firefox_version}.0) Gecko/{gecko_version} Firefox/{firefox_version}.0"
    elif browser == 'Safari':
        if os_type == 'Mac':
            return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Version/{random.randint(15, 18)}.{random.randint(0, 5)} Safari/{safari_version}"
        else:
            return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Chrome/{chrome_version} Safari/{webkit_version}"
    else:
        return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Chrome/{chrome_version} Safari/{webkit_version} Edg/{edge_version}"

DEV_NEWS_URL = "http://127.0.0.1:8899/tapp/news/push/stock/"

AI_CONFIG_FILE = os.path.join(CONFIG_DIR, 'ai_config.json')
FEISHU_CONFIG_FILE = os.path.join(CONFIG_DIR, 'feishu_config.json')
WECHAT_CONFIG_FILE = os.path.join(CONFIG_DIR, 'wechat_config.json')
STOCK_MONITOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'stock_monitor.json')
AI_PROMPT_FILE = os.path.join(CONFIG_DIR, 'ai_prompt.txt')
AI_DAILY_PROMPT_FILE = os.path.join(CONFIG_DIR, 'ai_daily_prompt.txt')
AI_DAILY_RESULT_FILE = os.path.join(CONFIG_DIR, 'ai_daily_result.md')
AI_DAILY_STATUS_FILE = os.path.join(CONFIG_DIR, 'ai_daily_status.json')
NEWS_ANALYSIS_CACHE_FILE = os.path.join(CONFIG_DIR, 'news_analysis_cache.json')
MONITOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'monitor_config.json')

# AI 批量股票打分（大盘云图）：提示词 + 分数/状态持久化（低频数据，放 data/ 不随每日清理）
STOCK_SCORE_PROMPT_FILE = os.path.join(CONFIG_DIR, 'stock_score_prompt.txt')
DATASOURCE_CONFIG_FILE = os.path.join(CONFIG_DIR, 'datasource_config.json')
STOCK_SCORES_DIR = os.path.join(DATA_DIR, 'stock_scores')
STOCK_SCORES_FILE = os.path.join(STOCK_SCORES_DIR, 'scores.json')
STOCK_SCORE_STATUS_FILE = os.path.join(STOCK_SCORES_DIR, 'status.json')

# 行业见顶周期批量诊断（大盘云图）：分数/状态持久化
INDUSTRY_CYCLE_SCORES_DIR = os.path.join(DATA_DIR, 'industry_cycle_scores')
INDUSTRY_CYCLE_SCORES_FILE = os.path.join(INDUSTRY_CYCLE_SCORES_DIR, 'scores.json')
INDUSTRY_CYCLE_BATCH_STATUS_FILE = os.path.join(INDUSTRY_CYCLE_SCORES_DIR, 'batch_status.json')

def load_monitor_config():
    default_config = {
        'api_base_url': 'http://127.0.0.1:5000',
        'check_interval': 30,
        'alert_threshold': 120,
        'restart_cooldown': 300
    }
    
    if os.path.exists(MONITOR_CONFIG_FILE):
        try:
            with open(MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                default_config.update(config)
        except Exception:
            pass
    
    return default_config

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)

# ==================== 数据源默认配置 ====================
# 每个数据源: key, name(显示名), category(分类), role(主/备/互补), url, test_url(测试可达性的URL), headers_hint(请求头提示)
DEFAULT_DATASOURCES = [
    # --- A股板块资金净流入 ---
    {'key': 'em_stock_list', 'name': '东方财富-A股板块列表', 'category': '板块资金净流入',
     'role': '主', 'url': 'https://push2.eastmoney.com/api/qt/clist/get',
     'test_url': 'https://push2.eastmoney.com/api/qt/clist/get', 'provider': '东方财富'},
    {'key': 'ths_sector_net_in', 'name': '同花顺-板块资金净流入', 'category': '板块资金净流入',
     'role': '主', 'url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/desc/ajax/1/',
     'test_url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/desc/ajax/1/', 'provider': '同花顺'},
    {'key': 'ths_sector_net_out', 'name': '同花顺-板块资金净流出', 'category': '板块资金净流入',
     'role': '互补', 'url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/asc/ajax/1/',
     'test_url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/asc/ajax/1/', 'provider': '同花顺'},

    # --- 大盘指数 ---
    {'key': 'em_market_index', 'name': '东方财富-大盘指数', 'category': '大盘指数',
     'role': '主', 'url': 'https://push2.eastmoney.com/api/qt/ulist.np/get',
     'test_url': 'https://push2.eastmoney.com/api/qt/ulist.np/get', 'provider': '东方财富'},
    {'key': 'sina_index', 'name': '新浪-大盘指数', 'category': '大盘指数',
     'role': '备', 'url': 'https://hq.sinajs.cn/list=sh000001,sz399001,sz399006',
     'test_url': 'https://hq.sinajs.cn/list=sh000001', 'provider': '新浪'},

    # --- 全球股市指数 ---
    {'key': 'em_global_index', 'name': '东方财富-全球指数', 'category': '全球股市指数',
     'role': '主', 'url': 'https://push2.eastmoney.com/api/qt/ulist.np/get',
     'test_url': 'https://push2.eastmoney.com/api/qt/ulist.np/get', 'provider': '东方财富'},
    {'key': 'sina_global_index', 'name': '新浪-全球指数兜底', 'category': '全球股市指数',
     'role': '备', 'url': 'https://hq.sinajs.cn/list=int_hangseng,b_KOSPI,int_nikkei',
     'test_url': 'https://hq.sinajs.cn/list=b_KOSPI', 'provider': '新浪'},

    # --- 个股行情 ---
    {'key': 'sina_stock_quote', 'name': '新浪-个股行情', 'category': '个股行情',
     'role': '主', 'url': 'https://hq.sinajs.cn/list=',
     'test_url': 'https://hq.sinajs.cn/list=sh600519', 'provider': '新浪'},
    {'key': 'tencent_stock_quote', 'name': '腾讯-个股行情兜底', 'category': '个股行情',
     'role': '备', 'url': 'https://qt.gtimg.cn/q=',
     'test_url': 'https://qt.gtimg.cn/q=sh600519', 'provider': '腾讯'},

    # --- 新闻 ---
    {'key': 'ths_news', 'name': '同花顺-新闻推送', 'category': '新闻',
     'role': '主', 'url': 'https://news.10jqka.com.cn/tapp/news/push/stock/',
     'test_url': 'https://news.10jqka.com.cn/tapp/news/push/stock/', 'provider': '同花顺'},

    # --- 行情快闪 ---
    {'key': 'ths_index_flash', 'name': '同花顺-指数快闪', 'category': '行情快闪',
     'role': '主', 'url': 'https://q.10jqka.com.cn/api.php?t=indexflash&',
     'test_url': 'https://q.10jqka.com.cn/api.php?t=indexflash&', 'provider': '同花顺'},
    {'key': 'ths_turnover_minute', 'name': '同花顺-分钟换手', 'category': '行情快闪',
     'role': '互补', 'url': 'https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data',
     'test_url': 'https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data', 'provider': '同花顺'},
    {'key': 'jrj_market', 'name': '金融界-市场数据', 'category': '行情快闪',
     'role': '互补', 'url': 'https://gateway.jrj.com/quot-dc/zdt/market',
     'test_url': 'https://gateway.jrj.com/quot-dc/zdt/market', 'provider': '金融界'},

    # --- 大盘云图(行业板块+个股) ---
    {'key': 'sina_sector_list', 'name': '新浪-行业板块列表', 'category': '大盘云图',
     'role': '主', 'url': 'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php',
     'test_url': 'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php', 'provider': '新浪'},
    {'key': 'sina_sector_stocks', 'name': '新浪-板块个股', 'category': '大盘云图',
     'role': '主', 'url': 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData',
     'test_url': 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData', 'provider': '新浪'},
    {'key': 'em_all_stock', 'name': '东方财富-全A股列表', 'category': '大盘云图',
     'role': '互补', 'url': 'https://push2.eastmoney.com/api/qt/clist/get',
     'test_url': 'https://push2.eastmoney.com/api/qt/clist/get', 'provider': '东方财富'},

    # --- 股票搜索 ---
    {'key': 'sina_suggest', 'name': '新浪-股票搜索建议', 'category': '股票搜索',
     'role': '主', 'url': 'https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15',
     'test_url': 'https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15&key=贵州茅台&name=suggestdata', 'provider': '新浪'},

    # --- 融资融券 ---
    {'key': 'sse_margin', 'name': '上交所-融资融券', 'category': '融资融券',
     'role': '主', 'url': 'akshare:stock_margin_detail_sse',
     'test_url': '', 'provider': '上交所(akshare)'},
    {'key': 'szse_margin', 'name': '深交所-融资融券', 'category': '融资融券',
     'role': '互补', 'url': 'akshare:stock_margin_detail_szse',
     'test_url': '', 'provider': '深交所(akshare)'},
]


# ==================== 东方财富代理请求 ====================
def load_em_proxy_pool():
    """从免费代理API获取国内HTTPS代理，供东方财富请求使用。"""
    global EM_PROXY_POOL
    try:
        resp = requests.get("https://proxy.scdn.io/api/get_proxy.php", params={
            'protocol': 'https', 'count': 5, 'country_code': 'CN'
        }, timeout=15)
        data = resp.json()
        if data.get('code') == 200 and data.get('data', {}).get('proxies'):
            EM_PROXY_POOL = [f'https://{p}' for p in data['data']['proxies']]
    except Exception:
        pass


def em_request(url, params=None, headers=None, timeout=10, max_retries=2):
    """东方财富请求：直连失败自动切换代理重试。

    典型场景：服务器IP被东方财富WAF封禁(Empty reply / Connection refused)，
    通过国内代理绕过。
    """
    # 第一次直连
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout,
                            allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 10:
            return resp
    except (requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError):
        pass
    except Exception:
        pass

    # 直连失败，尝试代理
    if not EM_PROXY_ENABLED:
        return resp  # 返回上一次的response(可能失败)

    # 懒加载代理池
    if not EM_PROXY_POOL:
        load_em_proxy_pool()

    for attempt in range(max_retries):
        if not EM_PROXY_POOL:
            break
        proxy = random.choice(EM_PROXY_POOL)
        proxies = {'http': proxy, 'https': proxy}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout,
                                proxies=proxies, allow_redirects=True, verify=False)
            if resp.status_code == 200 and len(resp.content) > 10:
                return resp
        except Exception:
            # 该代理不可用，从池中移除
            if proxy in EM_PROXY_POOL:
                EM_PROXY_POOL.remove(proxy)
            continue

    # 代理也失败，返回直连的response
    try:
        return requests.get(url, params=params, headers=headers, timeout=timeout)
    except Exception:
        return None
