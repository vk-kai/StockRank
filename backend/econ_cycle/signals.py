# -*- coding: utf-8 -*-
"""决策信号灯(第四步):把阶段与指标翻译成"换工作 / 创业"窗口结论。

- 换工作窗口:以【岗位供给】指标为核心——PMI从业人员指数(企业是否在招人/裁人,
  48.7 仍<50=总体减员)是新订单落地前的最强信号;新订单/工业增速只代表生产热度,
  资本密集型产值增长不吸纳岗位,权重次之;失业率环比作滞后确认。
- 创业窗口:消费(生意的根,弱复苏低分) + 工业景气 + PPI(过高=小微企业成本挤压,
  不算利好) + 新订单。
每盏灯输出 绿/黄/红 + 触发的依据行,前端直接渲染。
"""
from . import db, engine


def _latest(code, as_of=None):
    """取指标最新值:按指标目录登记的 value_type 读序列。"""
    ind = next((i for i in db.get_indicators() if i['code'] == code), None)
    vt = (ind or {}).get('value_type') or 'level'
    s = db.get_series(code, value_type=vt, as_of=as_of)
    return s[-1] if s else None


def job_switch_light(as_of=None):
    """换工作信号灯:岗位供给(PMI从业人员)为王,生产类只作辅证。"""
    reasons, score = [], 0
    emp = _latest('PMI_EMP', as_of)
    if emp and emp[1] is not None:
        v = emp[1]
        if v >= 50:
            score += 40
            reasons.append('PMI从业人员指数 %.1f,企业总体在扩张岗位' % v)
        elif v >= 49:
            score += 20
            reasons.append('PMI从业人员指数 %.1f,就业收缩明显放缓,接近平衡' % v)
        elif v >= 48:
            score += 10
            reasons.append('PMI从业人员指数 %.1f,企业仍在净减员,坑位少竞争多' % v)
        else:
            reasons.append('PMI从业人员指数 %.1f,企业总体在裁减岗位' % v)
    order = _latest('PMI_ORDER', as_of)
    if order and order[1] is not None:
        v = order[1]
        if v >= 50:
            score += 20
            reasons.append('PMI新订单指数 %.1f,订单回暖是招人扩张的前奏' % v)
        elif v >= 49:
            score += 10
            reasons.append('PMI新订单指数 %.1f,订单接近荣枯线' % v)
        else:
            reasons.append('PMI新订单指数 %.1f,订单收缩,扩招尚早' % v)
    unemp = _latest('UNEMPLOY', as_of)
    if unemp and unemp[1] is not None:
        v = unemp[1]
        s = db.get_series('UNEMPLOY', value_type='level', as_of=as_of)
        prev = s[-2][1] if len(s) >= 2 else None
        if prev is not None:
            if v < prev:
                score += 10
                reasons.append('调查失业率 %.1f%%,环比回落' % v)
            elif v > prev:
                reasons.append('调查失业率 %.1f%%,环比上升(%.1f→%.1f),求职窗口偏紧' % (prev, prev, v))
            else:
                reasons.append('调查失业率 %.1f%%,环比持平' % v)
        else:
            reasons.append('调查失业率 %.1f%%' % v)
    m1 = _latest('M1_YOY', as_of)
    if m1 and m1[1] is not None:
        if m1[1] > 0:
            score += 10
            reasons.append('M1同比 %.1f%%,企业活钱为正,留存扩编的余粮' % m1[1])
        else:
            reasons.append('M1同比 %.1f%%,企业现金流紧,缩编压力大' % m1[1])
    ind = _latest('IND_YOY', as_of)
    if ind and ind[1] is not None:
        if ind[1] >= 6:
            score += 15
            reasons.append('工业增加值同比 %.1f%%,生产景气,用工带动强' % ind[1])
        elif ind[1] >= 3:
            score += 8
            reasons.append('工业增加值同比 %.1f%%,生产平稳(资本密集型,岗位弹性有限)' % ind[1])
        else:
            reasons.append('工业增加值同比 %.1f%%,生产偏弱' % ind[1])
    light = 'green' if score >= 55 else ('yellow' if score >= 40 else 'red')
    return dict(light=light, score=score, reasons=reasons)


def startup_light(as_of=None):
    """创业信号灯:消费是根(弱复苏低分),PPI过高算成本挤压而非利好。"""
    reasons, score = [], 0
    retail = _latest('RETAIL_YOY', as_of)
    if retail and retail[1] is not None:
        v = retail[1]
        if v > 2:
            score += 40
            reasons.append('社零同比 %.1f%%,消费热度高,生意好做' % v)
        elif v > 0.5:
            score += 15
            reasons.append('社零同比 %.1f%%,消费弱复苏,谨慎铺开' % v)
        elif v > 0:
            score += 5
            reasons.append('社零同比 %.1f%%,消费几乎零增长,需求端观望' % v)
        else:
            reasons.append('社零同比 %.1f%%,消费收缩' % v)
    ind = _latest('IND_YOY', as_of)
    if ind and ind[1] is not None:
        if ind[1] > 4:
            score += 25
            reasons.append('工业同比 %.1f%%,产业链景气' % ind[1])
        elif ind[1] >= 0:
            score += 10
            reasons.append('工业同比 %.1f%%,生产平稳' % ind[1])
        else:
            reasons.append('工业同比 %.1f%%,生产收缩' % ind[1])
    ppi = _latest('PPI_YOY', as_of)
    if ppi and ppi[1] is not None:
        v = ppi[1]
        if 0 < v <= 3:
            score += 30
            reasons.append('PPI同比 %.1f%%,温和涨价,定价空间好' % v)
        elif 3 < v <= 5.5:
            score += 10
            reasons.append('PPI同比 %.1f%%,上游涨价偏快,小微成本承压' % v)
        elif v > 5.5:
            reasons.append('PPI同比 %.1f%%,成本挤压明显,小生意毛利薄' % v)
        else:
            score += 5
            reasons.append('PPI同比 %.1f%%,通缩区,让利换量' % v)
    order = _latest('PMI_ORDER', as_of)
    if order and order[1] is not None:
        if order[1] >= 50:
            score += 10
            reasons.append('PMI新订单 %.1f,需求端订单在回暖' % order[1])
        else:
            reasons.append('PMI新订单 %.1f,订单偏弱' % order[1])
    light = 'green' if score >= 60 else ('yellow' if score >= 40 else 'red')
    return dict(light=light, score=score, reasons=reasons)


def overview(as_of=None):
    """页面仪表盘聚合:阶段(全国/西安) + 两盏灯。"""
    national = engine.judge('national', as_of=as_of, persist=as_of is None)
    xian = engine.judge('xian', as_of=as_of, persist=as_of is None)
    return dict(
        month=(national or {}).get('month'),
        national=national,
        xian=xian,
        job_switch=job_switch_light(as_of),
        startup=startup_light(as_of),
    )
