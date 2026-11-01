"""同花顺融资融券市场汇总采集（rzrq/board）。

数据源: https://data.10jqka.com.cn/market/rzrq/board/getRzrqPage/page/N/ajax/1/
每页 10 个交易日,默认抓 4 页 ≈ 40 个交易日。表格每行 17 个 td:
  [0]交易日期 [1-4]融资余额 沪/深/北/合计 [5-8]融资买入额 沪/深/北/合计
  [9-12]融券余量余额 沪/深/北/合计 [13-16]融资融券余额 沪/深/北/合计
单位均为亿元,日期格式 'YYYY-MM-DD'(内部归一为 'YYYYMMDD' 与旧缓存口径一致)。

反爬复用 data_processor.ths_client 的整套基建:
  Chromium 现场生成 hexin-v cookie(refresh_ths_cookie,10分钟缓存) +
  随机化请求头 + 401/403 强刷重试。仅做汇总页(日级数据),不走代理池。
"""
import requests

from ._common import error_logger
from .ths_client import (
    attach_fresh_ths_cookie, generate_random_headers, refresh_ths_cookie,
)

MARGIN_TOTAL_URL = 'https://data.10jqka.com.cn/market/rzrq/board/getRzrqPage/page/{page}/ajax/1/'
MARGIN_REFERER = 'https://data.10jqka.com.cn/market/rzrq/'


def _margin_headers():
    headers = generate_random_headers(referer=MARGIN_REFERER)
    headers['Accept'] = 'text/html, */*; q=0.01'
    headers['X-Requested-With'] = 'XMLHttpRequest'
    headers['sec-fetch-dest'] = 'empty'
    headers['sec-fetch-mode'] = 'cors'
    headers['sec-fetch-site'] = 'same-origin'
    return headers


def _parse_ths_float(text):
    """同花顺数值单元格 → float('' 不可解析返回 None)。"""
    try:
        s = (text or '').replace(',', '').strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def parse_ths_margin_html(html_content, request_url=''):
    """解析融资融券汇总页 tbody,每行 17 个 td。返回降序列表(最新在前)。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    table = (soup.find('table', class_='m-table J-ajax-table')
             or soup.find('table', class_=lambda c: c and 'm-table' in c))
    if not table or not table.find('tbody'):
        preview = (html_content or '(空响应)')[:300]
        error_logger.error(f"融资融券汇总页未找到数据表格 URL={request_url} 预览: {preview}")
        return []

    rows = []
    for tr in table.find('tbody').find_all('tr'):
        cols = tr.find_all('td')
        if len(cols) < 17:
            continue
        date_raw = cols[0].get_text(strip=True)  # '2026-10-16'
        if len(date_raw) != 10 or date_raw[4] != '-':
            continue
        rows.append({
            'date': date_raw.replace('-', ''),
            'rzye_sh': _parse_ths_float(cols[1].get_text(strip=True)),
            'rzye_sz': _parse_ths_float(cols[2].get_text(strip=True)),
            'rzye_bj': _parse_ths_float(cols[3].get_text(strip=True)),
            'rzye': _parse_ths_float(cols[4].get_text(strip=True)),      # 融资余额合计
            'buy': _parse_ths_float(cols[8].get_text(strip=True)),       # 融资买入额合计
            'rqye': _parse_ths_float(cols[12].get_text(strip=True)),     # 融券余量余额合计
            'rzrq': _parse_ths_float(cols[16].get_text(strip=True)),     # 两融余额合计
        })
    return rows


def fetch_ths_margin_summary(pages=4):
    """抓取融资融券市场汇总(默认 4 页 ≈ 40 个交易日)。

    返回按日期升序的列表 [{date,rzye,buy,rqye,rzrq,...}](老日期在前)。
    全部失败返回 [];部分页失败返回已抓到的(数据连续性由调用方判断)。
    """
    session = requests.Session()
    session.trust_env = False
    collected = {}
    for page in range(1, max(1, pages) + 1):
        url = MARGIN_TOTAL_URL.format(page=page)
        ok = False
        for retry in range(3):  # 每页独立重试:401 时强刷 cookie 再试
            try:
                headers = attach_fresh_ths_cookie(_margin_headers(),
                                                  force=(retry > 0))
                resp = session.get(url, headers=headers, timeout=15,
                                   verify=False, allow_redirects=True)
                if resp.status_code in (401, 403):
                    error_logger.warning(
                        f"融资融券汇总 page={page} 第{retry + 1}次 {resp.status_code},强刷cookie重试")
                    continue
                resp.raise_for_status()
                ctype = (resp.headers.get('Content-Type') or '').lower()
                if 'charset=gbk' in ctype or 'charset=gb2312' in ctype:
                    resp.encoding = 'GBK'
                elif resp.encoding == 'ISO-8859-1':
                    resp.encoding = 'GBK'
                parsed = parse_ths_margin_html(resp.text, url)
                if parsed:
                    for r in parsed:
                        collected[r['date']] = r
                    ok = True
                    break
                error_logger.warning(
                    f"融资融券汇总 page={page} 解析为空,重试中")
            except Exception as e:
                error_logger.error(f"融资融券汇总 page={page} 第{retry + 1}次异常: {e}")
        if not ok:
            error_logger.error(f"融资融券汇总 page={page} 最终失败,跳过该页")

    # 汇总页数据只增不改(交易所回填极少),日期降序抓取,升序返回
    return [collected[d] for d in sorted(collected.keys())]
