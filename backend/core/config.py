import os
import random
import string
import json
import time
import requests
from datetime import timedelta

# config.py 位于 backend/core/ 子目录，需三层 dirname 才能回到项目根(StockRank/)
# (重构前在 backend/ 时是两层；移到 core/ 后若不改，BASE_DIR 会错指到 backend/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if BASE_DIR == '/':
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, 'data')
DAILY_DIR = os.path.join(DATA_DIR, 'daily')
REALTIME_DIR = os.path.join(DATA_DIR, 'realtime')
NEWS_DIR = os.path.join(DATA_DIR, 'news')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
# 统一业务数据库:量化(quant)与小程序(mp)共用一个 SQLite(WAL)。
# 旧 mp_game.db / mp_vpay.db / quant 的 trading.db 由 server_migration 脚本合并迁入。
UNIFIED_DB_FILE = os.path.join(DATA_DIR, 'stockrank.db')

# 量化区统一门禁:登录/兑换成功后下发的 tz_gate cookie,值须与 docker/nginx.conf
# 的 tz_gate SECRET 一致(nginx 据此放行 /TrendZen/ 与未来的 /quant/ 路由)。
# tz_user 为"已登录凭证"(HMAC 签名):量化后端凭它区分 管理员/游客(游客只读)。
TZ_GATE_COOKIE = 'tz_gate'
TZ_USER_COOKIE = 'tz_user'
TZ_GATE_SECRET = 'vK-TzGate-9f2c7a1e'

MAX_DAYS = 30
MAX_NEWS_HOURS = 48

DATA_URL = "https://push2.eastmoney.com/api/qt/clist/get"
NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"
THS_SECTOR_NET_IN_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/je/order/DESC/ajax/1/free/1/"
# 净流入路由候选：同花顺改版后新旧路由并存，哪个有数据用哪个(自动回退)。
# 主路由(大写DESC+free)拿不到数据时回退到旧路由(小写desc)。
THS_SECTOR_NET_IN_URLS = [
    THS_SECTOR_NET_IN_URL,
    "https://data.10jqka.com.cn/funds/hyzjl/field/je/order/desc/ajax/1/",
]
THS_SECTOR_NET_OUT_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/je/order/asc/ajax/1/free/1/"
THS_SECTOR_URL = THS_SECTOR_NET_IN_URL

# ── 同花顺代理兜底配置 ──
# 根因:服务器机房IP会被同花顺在Nginx层封禁(返回403 Nginx forbidden),
# 刷cookie无效。本机被风控时,从采集窗口第2轮起自动切到代理重试。
THS_PROXY_ENABLED = True          # 主开关:本机IP被风控时从第2轮起走代理
THS_PROXY_VERIFY_URL = THS_SECTOR_NET_IN_URL   # 用净流入主路由验证代理(必须能拿到真实板块表才算可用)
THS_PROXY_CACHE_TTL = 300         # 验证通过的代理缓存复用5分钟,避免每轮采集都重验
THS_PROXY_FETCH_COUNT = 20        # 每次从代理源拉取的候选数(免费代理质量差,多拉才有可能攒到可用的)
THS_PROXY_TARGET_COUNT = 2        # 目标可用代理数(粘性用1个+备用1个,被封后立即切换)
THS_PROXY_COOLDOWN_SECONDS = 600  # 被同花顺短期封禁的代理冷却时长(秒);过冷却期后重新验证可复用
THS_PROXY_MAX_FETCH_ROUNDS = 3    # 攒代理时最多拉取多少轮(每轮FETCH_COUNT个),避免无限拉免费接口

# 可插拔代理源列表。kind 决定如何解析响应成 ["ip:port", ...] / 完整URL:
#   scdn   → proxy.scdn.io JSON API(占位,实测返回垃圾IP;置 enabled:False 可关)
#   jhao   → jhao104/proxy_pool 本地实例的 /get 接口
#   static → 固定 IP:PORT 列表(付费/自建代理直接填这里,最稳)
# 机制优先,不依赖免费代理可用。付费代理填入 static 源即生效,无需改代码。
PROXY_SOURCES = [
    {
        'name': 'proxy.scdn.io',
        'kind': 'scdn',
        'url': 'https://proxy.scdn.io/api/get_proxy.php',
        'params': {'protocol': 'https', 'count': 20, 'country_code': 'CN'},
        'enabled': True,         # 免费源(实测大量垃圾IP,靠验证池过滤;count拉满20提高命中率)
    },
    {
        'name': 'jhao_proxy_pool_local',
        'kind': 'jhao',
        'url': 'http://127.0.0.1:5010/get',   # 部署 jhao104/proxy_pool 后默认端口
        'enabled': True,
    },
    # 付费/自建代理示例:取消注释、填入完整URL(支持 http://user:pass@host:port)即生效。
    # {'name': 'paid_static', 'kind': 'static',
    #  'proxies': ['http://user:pass@paid-host:port'], 'enabled': True},
]

USE_PROXY = False  # 已弃用:同花顺代理改用上方 THS_PROXY_ENABLED + PROXY_SOURCES(验证式池)。保留定义以防旧脚本引用。

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
# 微信小程序内容安全代理(msgSecCheck/mediaCheckAsync)配置
MP_SEC_CONFIG_FILE = os.path.join(CONFIG_DIR, 'mp_sec_config.json')
STOCK_MONITOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'stock_monitor.json')
# TrendZen 套利背离接入:轮询其免鉴权 feed 拉告警→微信推送→ack 回执(见 monitors/trendzen_arb_monitor.py)
TRENDZEN_ARB_CONFIG_FILE = os.path.join(CONFIG_DIR, 'trendzen_arb.json')
# 演示模式:未登录访客只读固定历史快照(见 data/demo_snapshot.py,接口 routes/demo_routes.py)
DEMO_CONFIG_FILE = os.path.join(CONFIG_DIR, 'demo_config.json')
AI_PROMPT_FILE = os.path.join(CONFIG_DIR, 'ai_prompt.txt')
AI_DAILY_PROMPT_FILE = os.path.join(CONFIG_DIR, 'ai_daily_prompt.txt')
AI_DAILY_RESULT_FILE = os.path.join(CONFIG_DIR, 'ai_daily_result.md')
AI_DAILY_STATUS_FILE = os.path.join(CONFIG_DIR, 'ai_daily_status.json')
AI_NEWS_SUMMARY_PROMPT_FILE = os.path.join(CONFIG_DIR, 'ai_news_summary_prompt.txt')
AI_NEWS_SUMMARY_RESULT_FILE = os.path.join(CONFIG_DIR, 'ai_news_summary_result.md')
AI_NEWS_SUMMARY_STATUS_FILE = os.path.join(CONFIG_DIR, 'ai_news_summary_status.json')
NEWS_ANALYSIS_CACHE_FILE = os.path.join(CONFIG_DIR, 'news_analysis_cache.json')
MONITOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'monitor_config.json')

# OTP 动态口令（TOTP）二次验证：开关 + 密钥
OTP_CONFIG_FILE = os.path.join(CONFIG_DIR, 'otp_config.json')
# 会话签名密钥持久化：开启 OTP 时旋转并落盘，使所有旧会话立即失效（强制重新登录）
SESSION_SECRET_FILE = os.path.join(CONFIG_DIR, 'session_secret.json')

# Jarvis 手机管家：免登录共享密钥。手机 app 在请求头带 X-Jarvis-Token，
# install_auth_guard 匹配成功后直接放行（跳过每日动态密码/OTP）。
# 文件不入版本库（见 .gitignore），换机器部署需重建并同步到 app 端 Tokens.kt。
JARVIS_TOKEN_CONFIG_FILE = os.path.join(CONFIG_DIR, 'jarvis_token.json')

# 兑换码（体验访问）：一次性限时码池，vk 生成后分享给他人免登录体验网站。
# 结构见 core/redemption_code.py。文件不入版本库（见 .gitignore）。
REDEMPTION_CODES_FILE = os.path.join(CONFIG_DIR, 'redemption_codes.json')


def load_jarvis_token():
    """读取 Jarvis app 的共享密钥；文件缺失或为空则返回空串（=关闭免登录，回退常规登录鉴权）。"""
    try:
        if os.path.exists(JARVIS_TOKEN_CONFIG_FILE):
            with open(JARVIS_TOKEN_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return (json.load(f).get('token') or '').strip()
    except Exception:
        pass
    return ''

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

# 同花顺代理池持久化:验证可用的代理 + 被短期封禁的冷却池(过冷却期可复用)
PROXY_POOL_DIR = os.path.join(DATA_DIR, 'proxy_pool')
PROXY_POOL_FILE = os.path.join(PROXY_POOL_DIR, 'pool.json')
PROXY_COOLDOWN_FILE = os.path.join(PROXY_POOL_DIR, 'cooldown.json')

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
# 2026-09-08 按实际采集链路如实修正(角色/顺序与代码真实取数顺序一致):
#   板块资金=同花顺净流入/净流出双榜(ths_client 每轮都拉); 涨跌家数=金融界主源+同花顺兜底
#   (get_market_summary: get_jrj_market_breadth() or get_ths_market_breadth());
#   成交额=同花顺分钟接口唯一来源; 云图行业库+市值=东方财富缓存, 实时涨跌=新浪。
#   em_stock_list(板块资金类)已删:DATA_URL 无任何采集代码引用,该类目实际只用同花顺。
DEFAULT_DATASOURCES = [
    # --- A股板块资金净流入 ---
    {'key': 'ths_sector_net_in', 'name': '同花顺-板块资金净流入', 'category': '板块资金净流入',
     'role': '主', 'url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/DESC/ajax/1/free/1/',
     'test_url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/DESC/ajax/1/free/1/', 'provider': '同花顺'},
    {'key': 'ths_sector_net_out', 'name': '同花顺-板块资金净流出', 'category': '板块资金净流入',
     'role': '互补', 'url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/asc/ajax/1/free/1/',
     'test_url': 'https://data.10jqka.com.cn/funds/hyzjl/field/je/order/asc/ajax/1/free/1/', 'provider': '同花顺'},

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

    # --- 行情快闪(涨跌家数/成交额) ---
    {'key': 'jrj_market', 'name': '金融界-涨跌家数', 'category': '行情快闪',
     'role': '主', 'url': 'https://gateway.jrj.com/quot-dc/zdt/market',
     'test_url': 'https://gateway.jrj.com/quot-dc/zdt/market', 'provider': '金融界'},
    {'key': 'ths_turnover_minute', 'name': '同花顺-分钟成交额', 'category': '行情快闪',
     'role': '主', 'url': 'https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data',
     'test_url': 'https://dq.10jqka.com.cn/fuyao/market_analysis_api/chart/v1/get_chart_data', 'provider': '同花顺'},
    {'key': 'ths_index_flash', 'name': '同花顺-指数快闪', 'category': '行情快闪',
     'role': '备', 'url': 'https://q.10jqka.com.cn/api.php?t=indexflash&',
     'test_url': 'https://q.10jqka.com.cn/api.php?t=indexflash&', 'provider': '同花顺'},

    # --- 大盘云图(行业板块+个股) ---
    {'key': 'sina_sector_list', 'name': '新浪-行业板块实时涨跌', 'category': '大盘云图',
     'role': '主', 'url': 'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php',
     'test_url': 'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php', 'provider': '新浪'},
    {'key': 'sina_sector_stocks', 'name': '新浪-板块个股下钻', 'category': '大盘云图',
     'role': '主', 'url': 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData',
     'test_url': 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData', 'provider': '新浪'},
    {'key': 'em_all_stock', 'name': '东方财富-行业库+市值缓存', 'category': '大盘云图',
     'role': '主', 'url': 'https://push2.eastmoney.com/api/qt/clist/get',
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
# 代理池上次加载时间：加载失败(代理源本身不可达)后10分钟内不重试，
# 否则每次 em_request 都白等一次 15s 超时(2026-09-08 连通性测试超时根因之一)。
EM_PROXY_POOL_LAST_LOAD = 0.0


def load_em_proxy_pool(force=False):
    """从免费代理API获取国内HTTPS代理，供东方财富请求使用。"""
    global EM_PROXY_POOL, EM_PROXY_POOL_LAST_LOAD
    if not force and time.time() - EM_PROXY_POOL_LAST_LOAD < 600:
        return
    EM_PROXY_POOL_LAST_LOAD = time.time()
    try:
        resp = requests.get("https://proxy.scdn.io/api/get_proxy.php", params={
            'protocol': 'https', 'count': 5, 'country_code': 'CN'
        }, timeout=15)
        data = resp.json()
        if data.get('code') == 200 and data.get('data', {}).get('proxies'):
            EM_PROXY_POOL = [f'https://{p}' for p in data['data']['proxies']]
    except Exception:
        pass


def em_request(url, params=None, headers=None, timeout=3, max_retries=1):
    """东方财富请求：直连失败自动切换代理重试。

    典型场景：服务器IP被东方财富WAF封禁(Empty reply / Connection refused)，
    通过国内代理绕过。
    """
    resp = None
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
        return resp  # 返回上一次的response(可能失败，可能None)

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
