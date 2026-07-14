# -*- coding: utf-8 -*-
"""自选股:名字↔代码互解 + 板块判定 + 涨跌停幅度。

涨跌停规则(自动,不可手填):
  - 北交所(bj) ±30%
  - 创业板(sz 300/301/302) ±20%
  - 科创板(sh 688/689) ±20%
  - 主板(sh 600/601/603/605;sz 000/001/002/003) ±10%
  - ST/*ST ±5% 仅对主板生效(注册制板块与北交所无 5% ST 档)
"""
from logger import get_logger

logger = get_logger('stock_resolver')


def classify_board(code):
    """code 形如 'sh600519' / 'sz301236' / 'bj920002'。

    返回 'main' / 'creative' / 'star' / 'bse' / 'unknown'。
    """
    code = (code or '').lower()
    if len(code) < 3:
        return 'unknown'
    ex, num = code[:2], code[2:]
    if ex == 'bj':
        return 'bse'
    if ex == 'sh':
        if num.startswith(('688', '689')):
            return 'star'
        if num.startswith(('600', '601', '603', '605')):
            return 'main'
        return 'unknown'
    if ex == 'sz':
        if num.startswith(('300', '301', '302')):
            return 'creative'
        if num.startswith(('000', '001', '002', '003')):
            return 'main'
        return 'unknown'
    return 'unknown'


def get_limit_pct(code, name):
    """返回该股涨跌停幅度(正数,百分点),如 10.0 / 20.0 / 30.0 / 5.0。"""
    board = classify_board(code)
    if board == 'bse':
        base = 30.0
    elif board in ('creative', 'star'):
        base = 20.0
    elif board == 'main':
        base = 10.0
    else:
        base = 10.0  # 未知降级主板
    # ST ±5% 仅主板
    if board == 'main' and name and ('ST' in name.upper()):
        base = 5.0
    return base


# --------------------------------------------------------------------------
# 名字 ↔ 代码互解(新浪 suggest,可注入 fetcher 便于测试)
# --------------------------------------------------------------------------
import os
import json

SUGGEST_URL = 'https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15&key={kw}&name=suggestdata'


def parse_sina_suggest(text):
    """解析新浪 suggest3 文本 -> [(name, prefixed_code), ...]。

    每行形如 '类别\\t名称\\t代码\\t拼音'(代码已含交易所前缀,如 sh600519)。
    """
    rows = []
    if not text:
        return rows
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3:
            name = parts[1].strip()
            code = parts[2].strip().lower()
            if name and code:
                rows.append((name, code))
    return rows


def _normalize_code(raw):
    """纯数字 -> 按规则补交易所前缀;已含前缀(sh/sz/bj)照用。"""
    raw = (raw or '').strip().lower()
    if not raw:
        return ''
    if raw[:2] in ('sh', 'sz', 'bj'):
        return raw
    if not raw.isdigit():
        return ''
    if raw.startswith(('600', '601', '603', '605', '688', '689')):
        return 'sh' + raw
    if raw.startswith(('000', '001', '002', '003', '300', '301', '302')):
        return 'sz' + raw
    if raw.startswith(('43', '83', '87', '88', '920')):
        return 'bj' + raw
    return ''  # 无法判定


class NameCodeCache:
    """内存 + 可选 JSON 落盘的 名字↔代码 缓存。path=None 表示纯内存(测试用)。"""

    def __init__(self, path=None):
        self.path = path
        self._mem = {}
        if path and os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self._mem = json.load(f)
            except Exception:
                self._mem = {}

    def get(self, key):
        return self._mem.get(key)

    def set(self, key, value):
        self._mem[key] = value
        if self.path:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self._mem, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f'名字代码缓存落盘失败: {e}')


_default_cache = None


def _default_cache():
    global _default_cache
    if _default_cache is None:
        from config import CONFIG_DIR
        _default_cache = NameCodeCache(path=os.path.join(CONFIG_DIR, 'name_code_cache.json'))
    return _default_cache


def _default_fetcher(keyword):
    import requests
    from config import get_random_user_agent
    try:
        url = SUGGEST_URL.format(kw=keyword)
        resp = requests.get(url, headers={
            'User-Agent': get_random_user_agent(),
            'Referer': 'https://finance.sina.com.cn/',
        }, timeout=8)
        resp.encoding = 'utf-8'
        return resp.text
    except Exception as e:
        logger.warning(f'新浪 suggest 请求失败({keyword}): {e}')
        return ''


def resolve_identifier(value, hint, fetcher='__default__', cache=None):
    """把用户输入解析为 (name, prefixed_code)。

    hint ∈ {'name', 'code', 'keyword'}。
      - code: 直接 _normalize_code;名字留空(后续报价里有)。
      - name: 走 suggest 反查(fetcher=None 时直接返回 None,便于纯逻辑测试)。
    返回 (name, code) 或 None(解不出)。
    """
    value = (value or '').strip()
    if not value:
        return None
    cache = cache or _default_cache()

    if hint == 'code':
        code = _normalize_code(value)
        return ('', code) if code else None

    if hint == 'name':
        cached = cache.get('name:' + value)
        if cached:
            return cached
        if fetcher is None:
            return None
        if fetcher == '__default__':
            fetcher = _default_fetcher
        rows = parse_sina_suggest(fetcher(value))
        if not rows:
            return None
        name, code = rows[0]
        result = (name, code)
        cache.set('name:' + value, result)
        return result

    return None  # keyword 无需解析
