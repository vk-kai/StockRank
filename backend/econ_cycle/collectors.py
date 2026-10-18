# -*- coding: utf-8 -*-
"""数据采集器(最终版,源均已实测验证 2026-10)。

全国层 — akshare 宏观接口(1.18.60,本机已装,底层为国家统计局/央行公开数据):
  PMI/CPI/PPI/M1/M2/社融增量/工业增加值/社零/消费者信心
  注意:多数 DataFrame 最新数据在头部(降序),社融/工业为升序,统一归一化处理。
西安层 — 西安市统计局「最新发布」《XX年1—N月西安市经济运行情况》HTML 正文
  (月度数据栏目为 PDF 附件,故走 zxfb 图文版;正文含各指标累计同比,已核验)
高频层 — 交通运输部《城市轨道交通运营数据速报》(HTML,全国月度客运量)

每条数据落库带 capture_time/source/source_url;单源失败不影响其他源。
"""
import re
import logging
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import db

logger = logging.getLogger('econ_cycle')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
TIMEOUT = 20

# akshare 宏观指标配置:code→(函数名, 期间列, 值列, value_type, 升序?)
AK_PLAN = [
    dict(code='PMI', name='制造业PMI', layer='leading', region='national',
         unit='', fn='macro_china_pmi', period_col='月份',
         value_cols={'level': ('制造业-指数', False)}),
    dict(code='CPI_YOY', name='CPI同比', layer='coincident', region='national',
         unit='%', fn='macro_china_cpi', period_col='月份',
         value_cols={'yoy': ('全国-同比增长', False)}),
    dict(code='PPI_YOY', name='PPI同比', layer='leading', region='national',
         unit='%', fn='macro_china_ppi', period_col='月份',
         value_cols={'yoy': ('当月同比增长', False)}),
    dict(code='M1_YOY', name='M1同比', layer='leading', region='national',
         unit='%', fn='macro_china_money_supply', period_col='月份',
         value_cols={'yoy': ('货币(M1)-同比增长', False)}),
    dict(code='M2_YOY', name='M2同比', layer='leading', region='national',
         unit='%', fn='macro_china_money_supply', period_col='月份',
         value_cols={'yoy': ('货币和准货币(M2)-同比增长', False)}),
    dict(code='SHRZ', name='社会融资规模增量', layer='leading', region='national',
         unit='亿元', fn='macro_china_shrzgm', period_col='月份',
         value_cols={'level': ('社会融资规模增量', True)}),
    dict(code='IND_YOY', name='工业增加值同比', layer='coincident', region='national',
         unit='%', fn='macro_china_gyzjz', period_col='月份',
         value_cols={'yoy': ('同比增长', True)}, pub_col='发布时间'),
    dict(code='RETAIL_YOY', name='社零同比', layer='coincident', region='national',
         unit='%', fn='macro_china_consumer_goods_retail', period_col='月份',
         value_cols={'yoy': ('同比增长', False)}),
    dict(code='CONF_INDEX', name='消费者信心指数', layer='leading', region='national',
         unit='', fn='macro_china_xfzxx', period_col='月份',
         value_cols={'level': ('消费者信心指数-指数值', False)}),
]

# 国家统计局官网稿件的就业类指标(akshare 无分项/失业率,金十源被墙,直接抓统计局):
# - 每月《中国采购经理指数运行情况》:制造业 PMI 总值/新订单指数/从业人员指数(荣枯线 50)
# - 每月《国民经济运行情况》:全国城镇调查失业率(反向指标,越低越好)
# 用工是"换工作/创业"决策的直接依据,PMI 总值代表不了岗位(资本密集型产值增长不吸纳就业)
STATS_ZXFB = 'https://www.stats.gov.cn/sj/zxfb/'
STATS_PMI_PAT = re.compile(r'(\d{4})年(\d{1,2})月中国采购经理指数运行情况')
STATS_ECO_PAT = re.compile(r'(\d{4})年(\d{1,2})月(?:份)?国民经济')
STATS_GOV_PLAN = [
    # PMI_GOV 与 akshare 的 PMI 同源同义,layer='ref' 仅存档对照,不进温度计(防双计)
    dict(code='PMI_GOV', name='官方制造业PMI(统计局稿,存档)', layer='ref', unit=''),
    dict(code='PMI_ORDER', name='PMI新订单指数', layer='leading', unit=''),
    dict(code='PMI_EMP', name='PMI从业人员指数', layer='coincident', unit=''),
    dict(code='UNEMPLOY', name='城镇调查失业率', layer='lagging', unit='%'),
]


def collect_stats_gov(max_pages=12):
    """抓国家统计局最新发布稿件:PMI 三分项 + 调查失业率。

    列表页断连频繁,逐页重试;稿件正文按"二、中国非制造业"切分取制造业段,
    防止抓到非制造业分项。返回 dict(成功期数, 失败页)。
    """
    import time as _t
    from urllib.parse import urljoin

    def _get_retry(url, tries=3):
        for i in range(tries):
            try:
                r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                r.raise_for_status()
                r.encoding = r.apparent_encoding or 'utf-8'
                return r.text
            except Exception:
                if i == tries - 1:
                    return None
                _t.sleep(2)

    arts = {}
    fail_pages = 0
    for page in range(max_pages):
        suffix = 'index.html' if page == 0 else 'index_%d.html' % page
        html = _get_retry(urljoin(STATS_ZXFB, suffix))
        if not html:
            fail_pages += 1
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            t = a.get_text(strip=True)
            m = STATS_PMI_PAT.search(t)
            if m:
                arts.setdefault(('pmi', int(m.group(1)), int(m.group(2))), urljoin(STATS_ZXFB, a['href']))
                continue
            m = STATS_ECO_PAT.search(t)
            if m and '采购经理' not in t:
                arts.setdefault(('eco', int(m.group(1)), int(m.group(2))), urljoin(STATS_ZXFB, a['href']))

    got = 0
    for (kind, year, month), href in sorted(arts.items()):
        text_html = _get_retry(href)
        if not text_html:
            continue
        text = BeautifulSoup(text_html, 'html.parser').get_text(' ', strip=True)
        period = '%04d-%02d' % (year, month)
        points = []
        if kind == 'pmi':
            # 制造业段=非制造业章节之前(防抓非制造业分项)
            sec = text.split('二、中国非制造业')[0]
            for code, pat in (
                ('PMI_GOV', r'制造业采购经理指数\s*（\s*PMI\s*）\s*为\s*(\d+\.?\d*)\s*%'),
                ('PMI_ORDER', r'制造业新订单指数为\s*(\d+\.?\d*)\s*%|新订单指数为\s*(\d+\.?\d*)\s*%'),
                ('PMI_EMP', r'制造业从业人员指数为\s*(\d+\.?\d*)\s*%|从业人员指数为\s*(\d+\.?\d*)\s*%'),
            ):
                m = re.search(pat, sec)
                if m:
                    val = float(next(g for g in m.groups() if g))
                    points.append((code, val))
        else:  # eco 国民经济稿:全国城镇调查失业率(取第一处=全国)
            m = re.search(r'城镇调查失业率为\s*(\d+\.?\d*)\s*%', text)
            if m:
                points.append(('UNEMPLOY', float(m.group(1))))
        for code, val in points:
            db.upsert_series(code, [(period, val, '')], value_type='level',
                             source='stats.gov.cn', source_url=href)
            got += 1
    logger.info('[econ] 统计局就业指标采集: %d 点, 列表页失败 %d', got, fail_pages)
    return dict(points=got, fail_pages=fail_pages)

# 西安市统计局:经济运行情况正文指标(累计同比,单位 %)
# 正则统一捕获动词(增长/下降)与数值:"下降33.8%"必须取负——曾因丢负号导致方向反转
# gap 禁止跨句读/"等"字,但允许"(金额)亿元,"和"(不含农户)"固定片段:
# 防止"房地产开发投资等有不同表现;零售额增长1.9%"跨句误配,同时兼容"零售额1170.87亿元,下降10.1%"标准句式
XA_METRICS = [
    dict(code='XA_IND_YOY', name='西安规上工业增加值累计同比', layer='coincident',
         pat=r'(?:规模以上|规上)工业增加值(?:[\d.]+亿元，)?[^。%；，、等]{0,12}?(?P<verb>增长|下降)\s*(?P<val>-?\d+\.?\d*)\s*%'),
    dict(code='XA_FAI_YOY', name='西安固定资产投资累计同比', layer='leading',
         pat=r'固定资产投资(?:（不含农户）)?(?:[\d.]+亿元，)?[^。%；，、等]{0,12}?(?P<verb>增长|下降)\s*(?P<val>-?\d+\.?\d*)\s*%'),
    dict(code='XA_RETAIL_YOY', name='西安限上零售累计同比', layer='coincident',
         pat=r'(?:限额以上|限上)(?:企业（单位）|企业|单位)?消费品零售额(?:[\d.]+亿元，)?[^。%；，、等]{0,12}?(?P<verb>增长|下降)\s*(?P<val>-?\d+\.?\d*)\s*%'),
    dict(code='XA_FDI_YOY', name='西安房地产开发投资累计同比', layer='leading',
         # 负向前瞻排除列举句("...分别下降32.1%、25%"),避免把工业投资降幅误配给房地产
         pat=r'房地产开发投资(?![^。%；，、等]{0,15}分别)(?:[\d.]+亿元，)?[^。%；，、等]{0,12}?(?P<verb>增长|下降)\s*(?P<val>-?\d+\.?\d*)\s*%'),
]

XA_ZXFB_URL = 'https://tjj.xa.gov.cn/tjsj/zxfb/{}.html'
MOT_LIST_URL = 'https://www.mot.gov.cn/shuju/fenxigongbao/yunlifenxi/'


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or 'utf-8'
    return r.text


def _norm_period(text):
    """'2026年09月份'/'202604'/'2026-09'/'2026年1-8月'(取尾月) → 'YYYY-MM'。"""
    text = str(text or '')
    m = re.search(r'(\d{4})\s*年\s*(?:1[—\-~至]\s*(\d{1,2})|(\d{1,2}))\s*月', text)
    if m:
        month = int(m.group(2) or m.group(3))
        if 1 <= month <= 12:
            return '%s-%02d' % (m.group(1), month)
        return None
    m = re.match(r'^(\d{4})(\d{2})$', text.strip())
    if m and 1 <= int(m.group(2)) <= 12:
        return '%s-%02d' % (m.group(1), int(m.group(2)))
    m = re.match(r'^\s*(\d{4})-(\d{1,2})', text)
    if m and 1 <= int(m.group(2)) <= 12:
        return '%s-%02d' % (m.group(1), int(m.group(2)))
    return None


# ---------------- 全国层:akshare ----------------

def collect_akshare(codes=None):
    """按 AK_PLAN 抓全国指标全历史。"""
    import akshare as ak  # 延迟导入,采集时才需要
    summary = {}
    for p in AK_PLAN:
        if codes and p['code'] not in codes:
            continue
        try:
            df = getattr(ak, p['fn'])()
            total = 0
            for vt, (col, ascending) in p['value_cols'].items():
                pts = []
                for _, row in df.iterrows():
                    period = _norm_period(row.get(p['period_col']))
                    val = row.get(col)
                    if period is None or val is None:
                        continue
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        continue
                    pub = ''
                    if p.get('pub_col'):
                        pub = str(row.get(p['pub_col']) or '')
                    pts.append((period, val, pub))
                total += db.upsert_series(p['code'], pts, value_type=vt,
                                          source='akshare/' + p['fn'])
            summary[p['code']] = total
            logger.info('[econ] akshare %s: %s 条', p['code'], total)
        except Exception as e:
            summary[p['code']] = 'FAIL %s' % str(e)[:80]
            logger.warning('[econ] akshare %s 失败: %s', p['code'], e)
    return summary


# ---------------- 西安层:统计局 zxfb 正文 ----------------

XA_PERIOD_MAP = {'一季度': 3, '上半年': 6, '前三季度': 9}


def collect_xa_stats(max_pages=4):
    """抓《XX年…西安市经济运行情况》正文,抽各指标累计同比。

    标题变体:1—N月 / 一季度(3) / 上半年(6) / 前三季度(9)。
    """
    summary = {}
    arts = {}
    for page in range(1, max_pages + 1):
        try:
            soup = BeautifulSoup(_get(XA_ZXFB_URL.format(page)), 'html.parser')
            for a in soup.find_all('a', href=True):
                title = a.get_text(strip=True)
                m = re.search(r'(\d{4})年(1—(\d{1,2})月|上半年|一季度|前三季度)'
                              r'西安市经济运行情况', title)
                if m:
                    month = (int(m.group(3)) if m.group(3)
                             else XA_PERIOD_MAP[m.group(2)])
                    key = (int(m.group(1)), month)
                    arts.setdefault(key, a['href'])
        except Exception as e:
            logger.warning('[econ] xa zxfb 第%s页失败: %s', page, e)
    if not arts:
        return {'xa': 'FAIL 列表为空(栏目结构可能变更)'}
    for (year, month), href in sorted(arts.items()):
        try:
            if not href.startswith('http'):
                href = 'https://tjj.xa.gov.cn' + href
            text = BeautifulSoup(_get(href), 'html.parser').get_text(' ', strip=True)
            got = 0
            for mt in XA_METRICS:
                m = re.search(mt['pat'], text)
                if not m:
                    continue
                val = float(m.group('val'))
                if m.group('verb') == '下降' and val > 0:
                    val = -val  # "下降33.8%" → -33.8(统计局不带负号)
                db.upsert_series(mt['code'], [('%s-%02d' % (year, month), val, '')],
                                 value_type='cum_yoy', source='tjj.xa.gov.cn',
                                 source_url=href)
                got += 1
            summary['%s-%02d' % (year, month)] = got
        except Exception as e:
            summary['%s-%02d' % (year, month)] = 'FAIL %s' % str(e)[:60]
    return summary


# ---------------- 高频层:交通运输部地铁速报 ----------------

def collect_mot(max_articles=8):
    """全国城市轨道月度客运量(亿人次)。"""
    try:
        soup = BeautifulSoup(_get(MOT_LIST_URL), 'html.parser')
        links = [a['href'] for a in soup.find_all('a', href=True)
                 if '城市轨道交通运营数据速报' in a.get_text(strip=True)]
        summary = {}
        for href in links[:max_articles]:
            try:
                full = urljoin(MOT_LIST_URL, href)
                text = BeautifulSoup(_get(full), 'html.parser').get_text(' ', strip=True)
                m_m = re.search(r'(\d{4})年(\d{1,2})月', text)
                m_v = re.search(r'完成客运量\s*([\d.]+)\s*亿人次', text)
                if m_m and m_v:
                    period = '%s-%02d' % (m_m.group(1), int(m_m.group(2)))
                    summary[period] = db.upsert_series(
                        'METRO_CN', [(period, float(m_v.group(1)), '')],
                        value_type='level', source='mot.gov.cn', source_url=full)
            except Exception as e:
                logger.warning('[econ] mot 文章失败: %s', e)
        return summary or {'mot': '未解析到速报数据'}
    except Exception as e:
        return {'mot': 'FAIL %s' % str(e)[:80]}


def seed_indicators():
    """把采集配置登记为指标目录(幂等)。value_type=序列存储类型,引擎按它取数。"""
    rows = [dict(code=p['code'], name=p['name'], layer=p['layer'],
                 region=p['region'], unit=p['unit'], source='akshare',
                 freq='monthly', weight=1.0,
                 value_type=next(iter(p['value_cols']))) for p in AK_PLAN]
    rows += [dict(code=m['code'], name=m['name'], layer=m['layer'],
                  region='xian', unit='%', source='tjj.xa.gov.cn',
                  freq='monthly', weight=1.2, value_type='cum_yoy')
             for m in XA_METRICS]
    rows.append(dict(code='METRO_CN', name='全国城市轨道客运量', layer='coincident',
                     region='national', unit='亿人次', source='mot.gov.cn',
                     freq='monthly', weight=0.8, value_type='level'))
    # 上证指数月收盘:不参与温度计评分(layer=market),只用于"行情确认"复苏信号
    rows.append(dict(code='SH_INDEX', name='上证指数(月收盘)', layer='market',
                     region='national', unit='点', source='sina',
                     freq='monthly', weight=0.0, value_type='close'))
    # 国家统计局稿件:就业类直接决定"换工作/创业"灯,PMI_EMP 加权;失业率为反向指标
    rows += [dict(code=p['code'], name=p['name'], layer=p['layer'],
                  region='national', unit=p['unit'], source='stats.gov.cn',
                  freq='monthly', weight=1.2 if p['code'] == 'PMI_EMP' else 1.0,
                  value_type='level', invert=1 if p['code'] == 'UNEMPLOY' else 0)
             for p in STATS_GOV_PLAN]
    db.upsert_indicators(rows)
    return len(rows)


def collect_sh_index():
    """上证指数月收盘(新浪日线重采样)。用于复苏信号之"行情确认",不参与评分。"""
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol='sh000001')
    if df is None or df.empty:
        return dict(status='FAIL', got=0, error='empty')
    df['date'] = df['date'].astype(str)
    monthly = {}
    for d, c in zip(df['date'], df['close']):
        monthly[d[:7]] = round(float(c), 2)  # 月内最后一天收盘
    pts = sorted(monthly.items())
    db.upsert_series('SH_INDEX', [(p, v, None) for p, v in pts],
                     value_type='close', source='sina',
                     source_url='https://finance.sina.com.cn/realstock/company/sh000001/nc.shtml')
    return dict(status='OK', got=len(pts))


def run_all():
    """全量采集入口(定时任务/手动接口均走这里)。"""
    started = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    seed_indicators()
    result = {
        'started_at': started,
        'akshare': collect_akshare(),
        'stats_gov': collect_stats_gov(),
        'xa_stats': collect_xa_stats(),
        'mot': collect_mot(),
        'sh_index': collect_sh_index(),
    }
    logger.info('[econ] 采集完成: %s', result)
    return result
