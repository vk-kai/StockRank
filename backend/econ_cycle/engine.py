# -*- coding: utf-8 -*-
"""周期判定引擎(第二步):单指标加工 → 温度计评分 → 阶段判定。

- 累计口径还原:西安数据是 1—N 月累计同比,做差分近似还原单月同比
- 月度K线:前值开盘/当值收盘/两者极值为高低(项目惯例,用于趋势判定)
- 温度计:各指标近 3 月趋势打分加权合成 0-100
- 阶段:五态规则(可解释),依据清单随结果落库
- 历史回放:按月逐点判定(as_of 截断),用于周期规律图与回测
"""
import json
import logging
from datetime import datetime

from . import db

logger = logging.getLogger('econ_cycle')

PHASES = ['downturn', 'bottoming', 'early_recovery', 'expansion', 'overheating']
PHASE_NAMES = {
    'downturn': '持续恶化', 'bottoming': '低位企稳',
    'early_recovery': '复苏初期', 'expansion': '上行', 'overheating': '过热',
}
PHASE_LABELS = {  # 前端色带用
    'downturn': {'cn': '持续恶化', 'color': '#e05252', 'kind': 'bad'},
    'bottoming': {'cn': '低位企稳', 'color': '#d9a441', 'kind': 'flat'},
    'early_recovery': {'cn': '复苏初期', 'color': '#7fb069', 'kind': 'good'},
    'expansion': {'cn': '上行', 'color': '#3d8f5f', 'kind': 'good'},
    'overheating': {'cn': '过热', 'color': '#c2703d', 'kind': 'warn'},
}


# ---------------- 单指标加工 ----------------

def derive_monthly_from_cum(cum_pairs):
    """累计同比 → 单月同比近似。

    设 1—N 月累计同比为 C(N),单月同比 M(N) 满足近似线性合成:
    M(N) = (N*C(N) - (N-1)*C(N-1))。首月=累计值。
    精度受权重口径影响,作为趋势近似足够(页面标注"单月值由累计差分近似")。
    """
    out = []
    prev_period, prev_cum = None, None
    for period, cum in cum_pairs:
        y, m = int(period[:4]), int(period[5:7])
        if m == 1 or prev_period is None:
            out.append((period, cum))
        elif prev_period == '%s-%02d' % (y, m - 1):
            approx = (m * cum - (m - 1) * prev_cum) / 1.0
            out.append((period, round(approx, 2)))
        else:  # 序列断裂,只能用累计值近似该月
            out.append((period, cum))
        prev_period, prev_cum = period, cum
    return out


def monthly_kline(pairs):
    """月度K线:open=前值 close=当值 high/low=两者极值。返回 [(period,o,h,l,c)]。"""
    kl = []
    for i in range(len(pairs)):
        period, close = pairs[i][0], pairs[i][1]
        prev = pairs[i - 1][1] if i else close
        kl.append((period, prev, max(prev, close), min(prev, close), close))
    return kl


def trend_state(pairs, lookback=3):
    """近 lookback 月趋势态:rising / falling / flat,以及斜率估计。"""
    vals = [v for _, v in pairs if v is not None][-lookback:]
    if len(vals) < 2:
        return 'flat', 0.0
    diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
    slope = sum(diffs) / len(diffs)
    if slope > 0.15:
        return 'rising', slope
    if slope < -0.15:
        return 'falling', slope
    return 'flat', slope


# 水平值类指标(非同比,不能用 0 中心映射):历史分位评分
# PMI_ORDER/PMI_EMP/PMI_GOV 均为荣枯线型指数,统一走分位
LEVEL_CODES = {'PMI', 'METRO_CN', 'SHRZ', 'CONF_INDEX',
               'PMI_GOV', 'PMI_ORDER', 'PMI_EMP', 'UNEMPLOY'}


def score_indicator_by_code(code, pairs, layer, invert=False):
    """单指标贡献分 0-100。

    - PMI:以 50 为荣枯线性映射
    - 其他水平值类(METRO/SHRZ/CONF/PMI 分项/失业率):近 60 期历史分位(0-100)
    - 同比类:以 0 为荣枯线性映射
    - 动量分统一按 3 月斜率
    - invert=True(失业率等"越低越好"):水平分与动量分同时反转
    """
    vals = [(p, v) for p, v in pairs if v is not None]
    if not vals:
        return None
    latest = vals[-1][1]
    state, slope = trend_state(vals)
    if code == 'PMI':
        level_score = 50 + (latest - 50) * 2.0
    elif code in LEVEL_CODES:
        window = [v for _, v in vals[-61:]]
        below = sum(1 for v in window if v <= latest)
        level_score = below / len(window) * 100.0
    else:
        level_score = 50 + latest * 2.0
    mom_score = 50 + max(min(slope * 15.0, 30), -30)
    if invert:
        level_score = 100 - level_score
        mom_score = 100 - mom_score
        # 反转后"下降"才是利好:趋势态语义对调
        state = {'rising': 'falling', 'falling': 'rising'}.get(state, state)
    s = 0.6 * max(min(level_score, 100), 0) + 0.4 * max(min(mom_score, 100), 0)
    return round(s, 1), state, slope, latest


# ---------------- 温度计与阶段 ----------------

def compute_score(region, as_of=None):
    """区域温度计:指标贡献分按权重合成 0-100。region=national/xian。"""
    inds = [i for i in db.get_indicators(region=region)
            if i['layer'] in ('leading', 'coincident')]
    if not inds:
        return None
    total_w, acc = 0.0, 0.0
    parts = []
    for ind in inds:
        if ind['region'] == 'xian':  # 西安为累计同比口径,先差分还原单月
            cum = [(p, v) for p, v, _ in db.get_series(
                ind['code'], value_type='cum_yoy', as_of=as_of)]
            pairs = derive_monthly_from_cum(cum)
        else:  # 全国按指标目录登记的存储类型取数(level/yoy)
            pairs = [(p, v) for p, v, _ in
                     db.get_series(ind['code'],
                                   value_type=ind.get('value_type') or 'level',
                                   as_of=as_of)]
        got = score_indicator_by_code(ind['code'], pairs, ind['layer'],
                                      invert=bool(ind.get('invert')))
        if got:
            s, state, slope, latest = got
            acc += s * ind['weight']
            total_w += ind['weight']
            parts.append(dict(code=ind['code'], name=ind['name'], layer=ind['layer'],
                              value=latest, state=state, slope=round(slope, 2),
                              score=s))
    if total_w == 0:
        return None
    return dict(score=round(acc / total_w, 1), indicators=parts)


def decide_phase(score, month, persist=True):
    """五态规则(可解释)。score+动量结构决定阶段,依据=构成清单摘要。

    规则要点:
    - 分数与动量双低 → downturn;分数低但动量止跌 → bottoming
    - 分数中高 + 领先指标多数上行 → early_recovery
    - 分数高 + 同步指标多数上行 → expansion;分数极高 + 动量回落 → overheating
    """
    if not score:
        return None
    s = score['score']
    inds = score.get('indicators', [])
    lead = [i for i in inds if i['layer'] == 'leading']
    coin = [i for i in inds if i['layer'] == 'coincident']
    lead_up = sum(1 for i in lead if i['state'] == 'rising') if lead else 0
    coin_up = sum(1 for i in coin if i['state'] == 'rising') if coin else 0
    mom = [i['slope'] for i in inds]
    avg_slope = sum(mom) / len(mom) if mom else 0.0

    if s >= 68 and avg_slope < 0 and len(inds) >= 3:
        phase = 'overheating'
        reason = '分数高位但边际动量转负,警惕过热'
    elif s >= 58 and coin_up >= max(1, len(coin) // 2):
        phase = 'expansion'
        reason = '分数偏高且同步指标多数上行'
    elif s >= 48 and lead_up >= max(1, (len(lead) + 1) // 2):
        phase = 'early_recovery'
        reason = '领先指标多数改善,同步尚未确认'
    elif s < 42 and avg_slope < -0.1:
        phase = 'bottoming' if avg_slope > -0.5 else 'downturn'
        reason = ('恶化速度放缓,出现企稳迹象' if phase == 'bottoming'
                  else '分数与动量双低,仍在恶化')
    elif s < 45:
        phase = 'bottoming'
        reason = '分数低位,动量趋稳'
    else:
        phase = 'early_recovery' if avg_slope > 0 else 'bottoming'
        reason = '中性区域,按动量方向归类'

    if persist:
        db.save_phase('__pending__', month, phase, s,
                      json.dumps({'reason': reason,
                                  'lead_up': lead_up, 'coin_up': coin_up,
                                  'detail': inds}, ensure_ascii=False))
    return phase, s, reason


def judge(scope, month=None, as_of=None, persist=True):
    """对外主入口:scope=national/xian。as_of 给定时回放历史。"""
    score = compute_score(scope, as_of=as_of)
    if not score:
        return None
    month = month or (db.get_series('PMI', as_of=as_of) or [('_',)])[-1][0]
    phase, s, reason = decide_phase(score, month, persist=False)
    if persist:
        db.save_phase(scope, month, phase, s,
                      json.dumps({'reason': reason,
                                  'indicators': score['indicators']},
                                 ensure_ascii=False))
    return dict(scope=scope, month=month, phase=phase,
                phase_cn=PHASE_NAMES[phase], score=s, reason=reason,
                indicators=score['indicators'])


def replay(scope, months=None):
    """历史回放:逐月 as_of 判定,产出阶段带(供规律图与回测)。"""
    base = db.get_series('PMI')
    if not base:
        return []
    all_months = [p for p, _, _ in base]
    months = months or all_months[-96:]
    out = []
    for m in months:
        try:
            r = judge(scope, month=m, as_of=m, persist=False)
        except Exception as e:
            logger.warning('[econ] 回放 %s 失败: %s', m, e)
            continue
        if r:
            out.append(dict(month=m, phase=r['phase'], score=r['score']))
    return out
