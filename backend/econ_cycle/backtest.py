# -*- coding: utf-8 -*-
"""历史回测(第五步):回放阶段判定,检验规则质量。

- 阶段带:逐月回放 → 前端背景色带(标注"规则回放,非事后标注")
- 命中率:复苏信号(early_recovery)出现后 3/6 个月,温度计分是否确实上行
输出结构化结果,阈值调整后重跑即可对比。
"""
import logging
from datetime import datetime

from . import db, engine

logger = logging.getLogger('econ_cycle')


def phase_bands(scope, months=None):
    """阶段带回放: [{month, phase, phase_cn, color, score}]。"""
    rows = engine.replay(scope, months=months)
    for r in rows:
        meta = engine.PHASE_LABELS.get(r['phase'], {})
        r['phase_cn'] = engine.PHASE_NAMES.get(r['phase'], r['phase'])
        r['color'] = meta.get('color', '#999')
    return rows


def hit_rate(scope='national', horizon=(3, 6)):
    """复苏信号命中率:early_recovery 信号后 horizon 个月,分数较信号月上行占比。

    样本不足时返回 None(诚实标注,不编造命中率)。
    """
    bands = phase_bands(scope)
    by_month = {b['month']: b['score'] for b in bands}
    months_sorted = sorted(by_month)
    idx = {m: i for i, m in enumerate(months_sorted)}
    results = {}
    for h in horizon:
        # 无条件基准:不看任何信号,所有月份 h 月后分数上行(>2分)的自然占比。
        # 信号命中率若与基准接近,说明信号没有额外预测力——诚实对比,防自我安慰。
        base_sig, base_hit = 0, 0
        for i, m in enumerate(months_sorted):
            j = i + h
            if j < len(months_sorted):
                base_sig += 1
                if by_month[months_sorted[j]] > (by_month[m] or 0) + 2:
                    base_hit += 1
        base_rate = round(base_hit / base_sig, 3) if base_sig else None
        signals, hits = 0, 0
        for i, m in enumerate(months_sorted):
            b = next(x for x in bands if x['month'] == m)
            if b['phase'] in ('early_recovery', 'bottoming'):
                j = i + h
                if j < len(months_sorted):
                    signals += 1
                    later = by_month[months_sorted[j]]
                    if later is not None and b['score'] is not None \
                            and later > b['score'] + 2:
                        hits += 1
        results[h] = dict(signals=signals, hits=hits,
                          rate=round(hits / signals, 3) if signals >= 5 else None,
                          baseline=base_rate)
    return results


def full_report(scope='national'):
    bands = phase_bands(scope)
    return dict(scope=scope, bands=bands, hit_rate=hit_rate(scope),
                generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
