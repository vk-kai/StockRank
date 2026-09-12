"""大盘云图（市场行业地图，从 data_processor._legacy 拆分）。

三级树：申万一级 → 二级 → 个股。行业+市值来自东方财富全A股缓存（低频更新），涨跌幅来自新浪实时行情（高频）。
依赖 _common 的 _safe_float / error_logger。
"""
import os
import json
import re
import time
from datetime import datetime

import requests

from core.config import REALTIME_DIR, get_random_user_agent, get_eastmoney_headers
from ._common import _safe_float, error_logger, data_logger


# 新浪行业板块与个股接口（大盘云图用，避免东方财富反爬）
SINA_SECTOR_LIST_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
SINA_SECTOR_STOCKS_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

# 东方财富全A股接口（用于行业分类+市值，低频缓存）
EM_ALL_STOCK_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

# 行业缓存文件
MARKET_MAP_CACHE_FILE = os.path.join(REALTIME_DIR, 'market_map_industry.json')

# 申万二级行业(f100) → 一级行业 映射表（申万2021分类标准）
SW_L2_TO_L1 = {
    # 农林牧渔
    '种植业': '农林牧渔', '渔业': '农林牧渔', '林业Ⅱ': '农林牧渔', '饲料': '农林牧渔',
    '农产品加工': '农林牧渔', '养殖业': '农林牧渔', '农业综合Ⅱ': '农林牧渔', '动物保健Ⅱ': '农林牧渔',
    # 基础化工
    '化学原料': '基础化工', '化学制品': '基础化工', '化学纤维': '基础化工', '农化制品': '基础化工',
    '塑料': '基础化工', '橡胶': '基础化工', '非金属材料Ⅱ': '基础化工',
    # 钢铁
    '普钢': '钢铁', '特钢Ⅱ': '钢铁', '冶钢原料': '钢铁',
    # 有色金属
    '工业金属': '有色金属', '小金属': '有色金属', '贵金属': '有色金属', '能源金属': '有色金属', '金属新材料': '有色金属',
    # 电子
    '半导体': '电子', '元件': '电子', '光学光电子': '电子', '消费电子': '电子', '其他电子Ⅱ': '电子', '电子化学品Ⅱ': '电子',
    # 机械设备
    '通用设备': '机械设备', '专用设备': '机械设备', '仪器仪表': '机械设备', '自动化设备': '机械设备',
    '工程机械': '机械设备', '轨交设备Ⅱ': '机械设备',
    # 国防军工
    '航空装备Ⅱ': '国防军工', '航天装备Ⅱ': '国防军工', '地面兵装Ⅱ': '国防军工', '军工电子Ⅱ': '国防军工', '航海装备Ⅱ': '国防军工',
    # 计算机
    '软件开发': '计算机', '计算机设备': '计算机', 'IT服务Ⅱ': '计算机',
    # 传媒
    '数字媒体': '传媒', '广告营销': '传媒', '出版': '传媒', '影视院线': '传媒', '游戏Ⅱ': '传媒', '电视广播Ⅱ': '传媒',
    # 通信
    '通信设备': '通信', '通信服务': '通信',
    # 医药生物
    '化学制药': '医药生物', '中药Ⅱ': '医药生物', '生物制品': '医药生物', '医疗器械': '医药生物',
    '医药商业': '医药生物', '医疗服务': '医药生物', '医疗美容': '医药生物',
    # 银行 / 非银金融
    '银行Ⅱ': '银行',
    '证券Ⅱ': '非银金融', '保险Ⅱ': '非银金融', '多元金融': '非银金融',
    # 房地产
    '房地产开发': '房地产', '房地产服务': '房地产',
    # 交通运输
    '铁路公路': '交通运输', '航运港口': '交通运输', '航空机场': '交通运输', '物流': '交通运输',
    # 公用事业
    '电力': '公用事业', '燃气Ⅱ': '公用事业',
    # 电力设备
    '光伏设备': '电力设备', '风电设备': '电力设备', '电池': '电力设备', '电网设备': '电力设备',
    '其他电源设备Ⅱ': '电力设备', '电机Ⅱ': '电力设备',
    # 汽车
    '乘用车': '汽车', '商用车': '汽车', '汽车零部件': '汽车', '汽车服务': '汽车', '摩托车及其他': '汽车',
    # 家用电器
    '白色家电': '家用电器', '黑色家电': '家用电器', '小家电': '家用电器', '厨卫电器': '家用电器',
    '照明设备Ⅱ': '家用电器', '家电零部件Ⅱ': '家用电器', '其他家电Ⅱ': '家用电器',
    # 食品饮料
    '白酒Ⅱ': '食品饮料', '非白酒': '食品饮料', '饮料乳品': '食品饮料', '食品加工': '食品饮料',
    '休闲食品': '食品饮料', '调味发酵品Ⅱ': '食品饮料',
    # 纺织服饰
    '服装家纺': '纺织服饰', '纺织制造': '纺织服饰', '饰品': '纺织服饰',
    # 轻工制造
    '家居用品': '轻工制造', '造纸': '轻工制造', '包装印刷': '轻工制造', '文娱用品': '轻工制造',
    # 商贸零售
    '一般零售': '商贸零售', '专业连锁Ⅱ': '商贸零售', '互联网电商': '商贸零售', '贸易Ⅱ': '商贸零售', '旅游零售Ⅱ': '商贸零售',
    # 社会服务
    '酒店餐饮': '社会服务', '旅游及景区': '社会服务', '教育': '社会服务', '专业服务': '社会服务', '体育Ⅱ': '社会服务',
    # 建筑材料
    '水泥': '建筑材料', '玻璃玻纤': '建筑材料', '装修建材': '建筑材料',
    # 建筑装饰
    '房屋建设Ⅱ': '建筑装饰', '装修装饰Ⅱ': '建筑装饰', '基础建设': '建筑装饰', '专业工程': '建筑装饰', '工程咨询服务Ⅱ': '建筑装饰',
    # 环保
    '环境治理': '环保', '环保设备Ⅱ': '环保',
    # 煤炭 / 石油石化
    '煤炭开采': '煤炭', '焦炭Ⅱ': '煤炭',
    '油气开采Ⅱ': '石油石化', '油服工程': '石油石化', '炼化及贸易': '石油石化',
    # 美容护理 / 综合
    '化妆品': '美容护理', '个护用品': '美容护理',
    '综合Ⅱ': '综合',
}


def _em_code_to_sina(em_code):
    """东方财富纯代码 → 新浪代码(sh/sz/bj前缀)"""
    code = str(em_code)
    if code.startswith(('6', '68', '11', '13')):
        return 'sh' + code
    elif code.startswith(('8', '4', '9')):
        return 'bj' + code
    else:
        return 'sz' + code


def refresh_market_map_cache():
    """分页抓取东方财富全部A股的行业分类+市值，缓存到本地文件。
    股票行业分类变化极少，建议低频更新（每周/手动触发）。"""
    # 用Session复用HTTP连接(keep-alive)+页间小延时+断连退避重试，降低东财反爬断连概率
    session = requests.Session()
    session.headers.update(get_eastmoney_headers())
    # 检测直连是否可达，不可达则启用代理
    from core.config import EM_PROXY_ENABLED, EM_PROXY_POOL, load_em_proxy_pool
    _use_proxy_for_session = False
    _session_proxies = None
    try:
        test_resp = session.get(EM_ALL_STOCK_URL, params={'pn': 1, 'pz': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f12', 'fs': EM_A_SHARE_FS, 'fields': 'f12'}, timeout=8)
        if test_resp.status_code != 200 or len(test_resp.content) < 10:
            raise Exception("Empty response")
    except Exception:
        # 直连失败，尝试加载代理
        if EM_PROXY_ENABLED:
            if not EM_PROXY_POOL:
                load_em_proxy_pool()
            if EM_PROXY_POOL:
                proxy = EM_PROXY_POOL[0]
                _session_proxies = {'http': proxy, 'https': proxy}
                session.proxies.update(_session_proxies)
                _use_proxy_for_session = True
    all_stocks = {}
    page = 1
    while page <= 80:
        params = {
            'pn': page, 'pz': 100, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f12',  # 按股票代码排序(稳定)。勿用f3涨跌幅——交易时段实时变动会让分页间股票漂移，导致漏抓/重抓(银行等就这样丢了)
            'fs': EM_A_SHARE_FS,
            'fields': 'f12,f14,f100,f20,f9'
        }
        # 单页重试3次(断连后0.5s退避)；仍失败则跳过该页继续，不再中止整批
        diff = None
        last_err = None
        for _attempt in range(3):
            try:
                response = session.get(EM_ALL_STOCK_URL, params=params, timeout=12)
                diff = (response.json().get('data') or {}).get('diff', []) or []
                break
            except Exception as e:
                last_err = e
                diff = None
                time.sleep(0.5)
        if diff is None:
            error_logger.warning(f"大盘云图缓存抓取第{page}页失败(重试3次): {last_err}")
            page += 1
            continue
        if not diff:
            break
        for item in diff:
            code = str(item.get('f12', ''))
            if not code:
                continue
            l2 = item.get('f100', '') or ''
            l2 = l2.strip()
            l1 = SW_L2_TO_L1.get(l2, '综合')
            if not l2 or l2 == '-':
                l2 = '其他'
                l1 = '综合'
            market_cap = _safe_float(item.get('f20'), 0)
            all_stocks[_em_code_to_sina(code)] = {
                'name': item.get('f14', ''),
                'l1': l1,
                'l2': l2,
                'value': market_cap,  # 总市值(元)，作为面积基准
                'pe': _safe_float(item.get('f9'), None)  # 市盈率(动态)；亏损为负、无数据为None
            }
        if len(diff) < 100:
            break
        page += 1
        time.sleep(0.2)   # 页间小延时，避免突发请求被东财反爬断连

    if not all_stocks:
        error_logger.warning("大盘云图缓存抓取失败：无数据")
        return None

    # 与上次缓存合并：本次因断连漏抓的页，用上次缓存里对应个股补齐，
    # 多刷新几次会累加到接近全量；银行等早期页面始终能抓到、永不丢。
    merged = dict(all_stocks)
    filled = 0
    try:
        if os.path.exists(MARKET_MAP_CACHE_FILE):
            with open(MARKET_MAP_CACHE_FILE, 'r', encoding='utf-8') as f:
                old = json.load(f)
            for code, info in (old.get('stocks') or {}).items():
                if code not in merged:
                    merged[code] = info
                    filled += 1
    except Exception:
        pass

    cache_data = {
        'stocks': merged,
        'count': len(merged),
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    try:
        with open(MARKET_MAP_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False)
        data_logger.info(f"大盘云图行业缓存已更新: 本次新抓{len(all_stocks)}只，缓存补齐{filled}只，合计{len(merged)}只")
    except Exception as e:
        error_logger.warning(f"大盘云图缓存写入失败: {e}")
    return cache_data


def _load_market_map_cache():
    """读取行业+市值缓存"""
    if not os.path.exists(MARKET_MAP_CACHE_FILE):
        return None
    try:
        with open(MARKET_MAP_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def get_all_market_map_stocks():
    """大盘云图全量股票清单（裸6位code → {name,l1,l2,value,pe}）。
    供 AI 批量打分等需要遍历全市场股票的场景使用。无缓存返回空 dict。"""
    cache = _load_market_map_cache()
    if not cache or not cache.get('stocks'):
        return {}
    return cache['stocks']


def _sina_batch_one(batch):
    """新浪批量获取单批涨跌幅（供并行调用）"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    result = {}
    url = f"https://hq.sinajs.cn/list={','.join(batch)}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'gbk'
        for line in response.text.strip().split('\n'):
            m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code = m.group(1)
            fields = m.group(2).split(',')
            if len(fields) >= 4:
                try:
                    pre_close = float(fields[2])
                    price = float(fields[3])
                    # price<=0：盘前/集合竞价尚未撮合/停牌无成交，新浪此时最新价为0，
                    # 直接算会得到 -100%。跳过，下游回退为0%（持平），避免全屏 -100%。
                    if pre_close > 0 and price > 0:
                        result[code] = round((price - pre_close) / pre_close * 100, 2)
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        error_logger.warning(f"新浪批量行情获取失败: {e}")
    return result


# 新浪实时涨跌幅短缓存：云图前端 15 秒轮询一次全量 /market-map，
# 每次都要打 13 批新浪请求(~5000只)。TTL 内直接复用，两次轮询间毫秒级返回，
# 新浪请求频率从 ~52次/分 降到 ~12次/分，页面打开也更跟手。
_changes_cache = {'ts': 0.0, 'data': {}}
_CHANGES_CACHE_TTL = 20.0  # 秒


def _sina_batch_changes(sina_codes):
    """新浪并行批量获取实时涨跌幅。返回 {sina_code: 涨跌幅%}"""
    if not sina_codes:
        return {}
    now = time.time()
    if now - _changes_cache['ts'] < _CHANGES_CACHE_TTL and _changes_cache['data']:
        return _changes_cache['data']
    batch_size = 400
    batches = [sina_codes[i:i + batch_size] for i in range(0, len(sina_codes), batch_size)]
    from concurrent.futures import ThreadPoolExecutor
    result = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        for batch_result in executor.map(_sina_batch_one, batches):
            result.update(batch_result)
    if result:
        _changes_cache['ts'] = now
        _changes_cache['data'] = result
    return result


def get_market_map_tree(include_changes=True):
    """构建三级大盘云图树：申万一级→二级→个股。
    行业+市值来自本地缓存（低频更新），涨跌幅来自新浪实时行情（高频）。
    若缓存不存在则自动抓取一次。
    include_changes=False 时跳过新浪实时请求、涨跌幅全部按0%，用于首屏秒开骨架。"""
    cache = _load_market_map_cache()
    if not cache or not cache.get('stocks'):
        data_logger.info("大盘云图缓存不存在，自动抓取中...")
        cache = refresh_market_map_cache()
        if not cache:
            return None

    stocks_cache = cache['stocks']
    cache_time = cache.get('update_time', '')

    # 新浪批量获取实时涨跌幅（首屏骨架模式跳过，涨跌幅全部为0，瞬时返回）
    sina_codes = list(stocks_cache.keys())
    changes = _sina_batch_changes(sina_codes) if include_changes else {}

    # 构建三级树
    tree_map = {}  # {l1: {l2: [stocks]}}
    for code, info in stocks_cache.items():
        l1 = info['l1']
        l2 = info['l2']
        change = changes.get(code, 0)
        if l1 not in tree_map:
            tree_map[l1] = {}
        if l2 not in tree_map[l1]:
            tree_map[l1][l2] = []
        tree_map[l1][l2].append({
            'name': info['name'],
            'code': code,
            'change': change,
            'value': info['value'],
            'pe': info.get('pe')
        })

    # 转为列表并排序，统计层级市值
    tree = []
    total_stocks = 0
    for l1, l2_map in tree_map.items():
        l1_value = 0
        l1_change_sum = 0
        l1_count = 0
        l2_list = []
        for l2, stocks in l2_map.items():
            # 每个二级内的个股按市值排序
            stocks.sort(key=lambda x: x['value'], reverse=True)
            l2_value = sum(s['value'] for s in stocks)
            l2_change = sum(s['change'] for s in stocks) / len(stocks) if stocks else 0
            l1_value += l2_value
            l1_change_sum += sum(s['change'] for s in stocks)
            l1_count += len(stocks)
            total_stocks += len(stocks)
            l2_list.append({
                'name': l2,
                'change': round(l2_change, 2),
                'value': l2_value,
                'children': stocks
            })
        l2_list.sort(key=lambda x: x['value'], reverse=True)
        tree.append({
            'name': l1,
            'change': round(l1_change_sum / l1_count, 2) if l1_count else 0,
            'value': l1_value,
            'children': l2_list
        })

    # 一级按市值排序
    tree.sort(key=lambda x: x['value'], reverse=True)
    return {
        'tree': tree,
        'total_sectors': len(tree),
        'total_stocks': total_stocks,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'cache_time': cache_time,
        'source': 'eastmoney+sina'
    }


def _fetch_sector_stocks(node):
    """抓取单个板块的全部个股（供并行调用）"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://vip.stock.finance.sina.com.cn/'
    }
    params = {
        'page': 1,
        'num': 300,
        'sort': 'mktcap',
        'asc': 0,
        'node': node,
        'symbol': '',
        '_s_r_a': 'page'
    }
    try:
        response = requests.get(SINA_SECTOR_STOCKS_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list):
            return []
        stocks = []
        for s in items:
            mktcap = _safe_float(s.get('mktcap'), 0)   # 流通市值（万元）
            if mktcap <= 0:
                continue
            stocks.append({
                'name': s.get('name', ''),
                'code': s.get('symbol', ''),
                'change': round(_safe_float(s.get('changepercent'), 0), 2),
                'value': mktcap,
                'price': _safe_float(s.get('trade'), 0)
            })
        return stocks
    except Exception as e:
        error_logger.warning(f"板块 {node} 个股获取失败: {e}")
        return []


def get_market_map_all():
    """一次性并行抓取全市场 行业→个股 嵌套数据（大盘云图用）。
    使用线程池并行抓取49个板块，返回嵌套结构。
    返回：[{ name:行业名, change:板块涨跌, value:板块市值, children: [{name,code,change,value,price}] }]"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    try:
        # 1. 获取全部一级行业板块
        response = requests.get(SINA_SECTOR_LIST_URL, headers=headers, timeout=10)
        response.encoding = 'gbk'
        m = re.search(r'\{.*\}', response.text, re.S)
        if not m:
            error_logger.warning("大盘云图板块数据格式异常")
            return None
        raw = m.group(0).replace("'", '"')
        d = json.loads(raw)

        sector_list = []
        for node, val in d.items():
            p = val.split(',')
            if len(p) < 13:
                continue
            name = p[1]
            change = round(_safe_float(p[4], 0), 2)
            market_cap = _safe_float(p[7], 0)
            if market_cap <= 0:
                continue
            sector_list.append({
                'name': name,
                'code': node,
                'change': change,
                'value': market_cap
            })
        if not sector_list:
            error_logger.warning("大盘云图板块数据为空")
            return None

        # 2. 并行抓取各板块个股
        from concurrent.futures import ThreadPoolExecutor
        nodes = [s['code'] for s in sector_list]
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(_fetch_sector_stocks, nodes))

        # 3. 组装嵌套结构
        tree = []
        for sector, stocks in zip(sector_list, results):
            if not stocks:
                continue
            sector_value = sum(st['value'] for st in stocks)
            tree.append({
                'name': sector['name'],
                'change': sector['change'],
                'value': sector_value,
                'children': stocks
            })
        # 按市值排序
        tree.sort(key=lambda x: x['value'], reverse=True)
        total_stocks = sum(len(s['children']) for s in tree)
        data_logger.info(f"大盘云图: {len(tree)}个行业, {total_stocks}只个股")
        return {
            'tree': tree,
            'total_sectors': len(tree),
            'total_stocks': total_stocks,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'sina'
        }
    except Exception as e:
        error_logger.warning(f"大盘云图全量数据获取失败: {e}")
        return None


def get_market_map_sectors():
    """获取全市场行业板块列表（按市值排序，数据源：新浪）"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    try:
        response = requests.get(SINA_SECTOR_LIST_URL, headers=headers, timeout=10)
        response.encoding = 'gbk'
        m = re.search(r'\{.*\}', response.text, re.S)
        if not m:
            error_logger.warning("大盘云图板块数据格式异常")
            return None
        raw = m.group(0).replace("'", '"')
        d = json.loads(raw)

        sectors = []
        for node, val in d.items():
            p = val.split(',')
            if len(p) < 13:
                continue
            name = p[1]
            change = _safe_float(p[4], 0)
            turnover = _safe_float(p[6], 0)
            market_cap = _safe_float(p[7], 0)
            if market_cap <= 0:
                continue
            sectors.append({
                'name': name,
                'code': node,
                'change': round(change, 2),
                'value': market_cap,
                'turnover': turnover,
                'leader': p[12] if len(p) > 12 else '',
                'leader_change': round(_safe_float(p[9], 0), 2)
            })
        if not sectors:
            error_logger.warning("大盘云图板块数据为空")
            return None
        sectors.sort(key=lambda x: x['value'], reverse=True)
        return {
            'sectors': sectors,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'sina'
        }
    except Exception as e:
        error_logger.warning(f"大盘云图板块数据获取失败: {e}")
        return None

def get_market_map_stocks(sector_code):
    """获取指定板块下的个股（按流通市值排序，数据源：新浪）"""
    stocks = _fetch_sector_stocks(sector_code)
    if not stocks:
        return None
    return {
        'stocks': stocks,
        'sector_code': sector_code,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'sina'
    }
