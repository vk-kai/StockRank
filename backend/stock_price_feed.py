# -*- coding: utf-8 -*-
"""自选股行情数据源:新浪主力 + 腾讯兜底,自动切换。

新浪 hq.sinajs.cn 字段顺序:
  0 名称,1 今开,2 昨收,3 现价,4 最高,5 最低,...,30 日期,31 时间
腾讯 qt.gtimg.cn 字段(以 ~ 分隔):
  1 名称,2 代码,3 现价,4 昨收,5 今开,...,33 最高,34 最低
"""
import re

from core.logger import get_logger

logger = get_logger('stock_feed')

SINA_URL = 'https://hq.sinajs.cn/list={codes}'
TENCENT_URL = 'https://qt.gtimg.cn/q={codes}'


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_sina(text, codes):
    """解析新浪批量返回 -> {code: {price,pct,open,prev_close,high,low,ts}}。"""
    out = {}
    if not text:
        return out
    for code in codes:
        m = re.search(r'hq_str_' + re.escape(code) + r'="([^"]*)"', text)
        if not m:
            continue
        f = m.group(1).split(',')
        if len(f) < 6 or not f[1]:
            continue
        try:
            price = _f(f[3])
            prev_close = _f(f[2])
            pct = round((price - prev_close) / prev_close * 100, 3) if prev_close else 0.0
            ts = f'{f[30]} {f[31]}' if len(f) > 31 and f[30] else ''
            out[code] = {
                'price': price, 'open': _f(f[1]), 'prev_close': prev_close,
                'high': _f(f[4]), 'low': _f(f[5]), 'pct': pct, 'ts': ts,
            }
        except Exception as e:
            logger.warning(f'新浪解析失败 {code}: {e}')
    return out


def parse_tencent(text, codes):
    """解析腾讯批量返回 -> {code: quote}。"""
    out = {}
    if not text:
        return out
    for code in codes:
        m = re.search(r'v_' + re.escape(code) + r'="([^"]*)"', text)
        if not m:
            continue
        f = m.group(1).split('~')
        if len(f) < 6:
            continue
        try:
            price = _f(f[3])
            prev_close = _f(f[4])
            pct = round((price - prev_close) / prev_close * 100, 3) if prev_close else 0.0
            high = _f(f[33]) if len(f) > 33 else price
            low = _f(f[34]) if len(f) > 34 else price
            openp = _f(f[5]) if len(f) > 5 else price
            out[code] = {
                'price': price, 'open': openp, 'prev_close': prev_close,
                'high': high, 'low': low, 'pct': pct, 'ts': '',
            }
        except Exception as e:
            logger.warning(f'腾讯解析失败 {code}: {e}')
    return out


def _default_sina_fetch(codes):
    import requests
    from core.config import get_random_user_agent
    try:
        resp = requests.get(SINA_URL.format(codes=','.join(codes)), headers={
            'User-Agent': get_random_user_agent(),
            'Referer': 'https://finance.sina.com.cn/',
        }, timeout=8)
        resp.encoding = 'gbk'  # 新浪行情返回 gbk
        return resp.text
    except Exception as e:
        logger.warning(f'新浪行情请求失败: {e}')
        return ''


def _default_tencent_fetch(codes):
    import requests
    from core.config import get_random_user_agent
    try:
        resp = requests.get(TENCENT_URL.format(codes=','.join(codes)), headers={
            'User-Agent': get_random_user_agent(),
        }, timeout=8)
        resp.encoding = 'gbk'
        return resp.text
    except Exception as e:
        logger.warning(f'腾讯行情请求失败: {e}')
        return ''


def get_quotes(codes, sina_fetcher=None, tencent_fetcher=None):
    """批量取报价,新浪优先,空/失败切腾讯。返回 {code: quote}。"""
    codes = [c for c in codes if c]
    if not codes:
        return {}
    sina_fetcher = sina_fetcher or _default_sina_fetch
    tencent_fetcher = tencent_fetcher or _default_tencent_fetch

    out = parse_sina(sina_fetcher(codes), codes)
    missing = [c for c in codes if c not in out]
    if missing:
        tqq = parse_tencent(tencent_fetcher(codes), codes)
        for c in missing:
            if c in tqq:
                out[c] = tqq[c]
    return out
