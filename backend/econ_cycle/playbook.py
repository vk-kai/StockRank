# -*- coding: utf-8 -*-
"""周期知识库(第五步扩充):指标解读 / 周期路径 / 复苏传导链 / 时间预判。

- INDICATOR_GUIDE:每个指标"怎么读、多少算好、为什么"——前端指标卡解释来源
- PHASE_PATH:五阶段路径(数据表现+该阶段对策)——前端周期路径图来源
- CHAIN:复苏传导链(订单→生产→价格→活钱→就业→消费)及各环节先后的原因
- build_forecast:结合历史规律的动态预判(新订单连续过线起点 + 2~4 季度滞后 → 就业窗口)
"""
from datetime import datetime

from . import db

# ---------------- 指标解读(前端展示用) ----------------

INDICATOR_GUIDE = {
    'PMI_ORDER': dict(
        name='PMI新订单指数', how='荣枯线 50。>50 = 企业接到的新订单在变多。',
        good='连续 3 个月 ≥50,且走高', bad='连续 <49 且下行',
        why='复苏链条的第一环:需求预期改善时企业最先进货下订单,成本最低、最容易反悔。'
            '它转好不代表好日子来了,但它是"需求止跌"最早的信号。'),
    'PMI': dict(
        name='制造业PMI', how='荣枯线 50。>50 = 制造业整体在扩张(不是萎缩)。',
        good='≥51 并站稳 3 个月', bad='<49',
        why='生产端热度。注意:PMI 过线只代表"生产在恢复",资本密集型行业(芯片/新能源大厂)'
            '产值增长不等于招人,不能直接当"好找工作"的证据。'),
    'PMI_GOV': dict(
        name='官方PMI(统计局稿)', how='与 PMI 同源同义,系统存档对照用,不参与评分。',
        good='同 PMI', bad='同 PMI',
        why='保留独立官方源做交叉核验,防止单一数据源(金十)被墙后失明。'),
    'PMI_EMP': dict(
        name='PMI从业人员指数', how='荣枯线 50。>50 = 被调查企业总体在净增岗位;<50 = 总体在净减员。',
        good='≥50(回到 50 上方,换工作窗口才真正打开)', bad='<48.5(减员加速)',
        why='**全系统最硬的"岗位多少"数据**——直接问企业"这个月比上月多招人还是少招人"。'
            '企业扩编是最贵、最不可逆的决定(社保/赔偿/管理成本),所以它是复苏最后一环,'
            '订单转好后通常还要 2~4 个季度它才过线。盯岗位就盯它。'),
    'UNEMPLOY': dict(
        name='城镇调查失业率', how='越低越好。全国口径 5% 左右是常态。',
        good='环比回落', bad='连续 2 月以上上行',
        why='滞后确认指标:失业率见顶回落 = 就业市场实质性好转的官方盖章。'
            '它好转时换工作窗口通常已经开了 1~2 个月(领先指标先动)。'),
    'M1_YOY': dict(
        name='M1同比(企业活钱)', how='>0 = 企业账上活钱在增长;数字越大扩张余粮越足。',
        good='>3% 且上行', bad='<0(活钱萎缩,缩编/砍预算压力大)',
        why='企业活期存款增速。企业要先"手里有钱"才谈得上扩编和投资,'
            'M1 负增长时期极少有加薪行情。'),
    'M2_YOY': dict(
        name='M2同比(广义货币)', how='全社会的钱的水位,7%~9% 常态。',
        good='稳中有升', bad='快速下滑(信用收缩)',
        why='背景板指标:决定整体流动性环境,不直接指示复苏,但水位太低时任何复苏都难持续。'),
    'SHRZ': dict(
        name='社会融资规模增量', how='当月全社会从金融体系拿到的钱。看同比多增/少增。',
        good='同比多增(政府/企业真在借钱扩张)', bad='同比大幅少增',
        why='借钱是扩张的前置动作。政府债前置发力时它先起来,要剔除政府债看企业中长贷才纯——'
            '系统暂用总量, interpret 时注意。'),
    'IND_YOY': dict(
        name='工业增加值同比', how='全国规上工业产出增速。5% 上下算平稳,6%+ 偏强。',
        good='≥6%', bad='<3%',
        why='生产端体感。它好≠岗位多(资本密集型),但在复苏链上排第二环:'
            '订单落地后企业第一反应是开足产能,不是招人。'),
    'RETAIL_YOY': dict(
        name='社会消费品零售同比', how='全社会消费增速。2%+ 才算健康,0 附近 = 基本零增长。',
        good='>2% 且上行', bad='<0(消费收缩)',
        why='复苏最后一环:就业稳了→收入涨了→才敢消费。反过来它也是创业的直接需求面:'
            '消费 0 增长时开店做生意,本质是在抢存量。'),
    'CPI_YOY': dict(
        name='CPI同比(物价)', how='0~3% 为健康区。<0 = 通缩(需求差到降价也卖不动);>3 = 过热。',
        good='1~2% 温和正增长', bad='连续 <0',
        why='内需温度计。通缩时期企业"以价换量",利润薄→不加薪→消费更弱,是负循环信号。'),
    'PPI_YOY': dict(
        name='PPI同比(工业品出厂价)', how='0~3% 温和正 = 产业链有定价空间;>5.5 = 上游涨价过快。',
        good='0~3%', bad='>5.5(小微企业成本被挤压)或 <-1(通缩)',
        why='对打工人:温和正 = 提薪空间;对创业者:过高 = 进货成本涨在先、售价涨不动,毛利被压。'),
    'CONF_INDEX': dict(
        name='消费者信心指数', how='100 为中性。2018 年前常态 120 左右,2022 年后跌到 85~90 区间。',
        good='回升并向 100 修复', bad='再创新低',
        why='预期指标:人只有相信未来收入会好,才敢加杠杆消费。它领先大件消费(房/车/装修)。'),
    'METRO_CN': dict(
        name='城市轨道客运量', how='主要城市地铁人流,看同比。', good='同比正增长',
        bad='同比下滑',
        why='高频"脚投票"数据:人流恢复领先线下消费、餐饮、市面热闹程度。'),
    'XA_IND_YOY': dict(
        name='西安工业增加值(累计同比)', how='统计局累计口径,系统已差分还原为单月近似。',
        good='单月转正并走高', bad='连续下行',
        why='西安工业以半导体/汽车/新能源为主,产值弹性大但岗位弹性一般——'
            '看它判断西安经济动能,别直接换算成"西安工作好找"。'),
    'XA_FAI_YOY': dict(
        name='西安固定资产投资(累计同比)', how='累计口径含房地产。', good='降幅收窄/转正',
        bad='降幅扩大',
        why='西安近年固投受"保回迁"项目调整影响深跌,数字夸张时先看房地产分项,'
            '剔除后再看基建/产业投资的真实动能。'),
    'XA_RETAIL_YOY': dict(
        name='西安限上零售(累计同比)', how='限额以上企业零售,累计口径已差分。', good='转正',
        bad='降幅扩大',
        why='西安消费的直接体感数据。降幅连续收窄 = 本地生意环境在回暖。'),
    'XA_FDI_YOY': dict(
        name='西安房地产开发投资(累计同比)', how='累计口径。', good='降幅收窄',
        bad='深跌不止',
        why='西安房地产关联基建/建材/中介大量就业,它的深跌会拖累本地就业市场,'
            '是西安"体感比全国冷"的重要原因。'),
}

# ---------------- 周期路径(阶段+表现+对策) ----------------

PHASE_PATH = [
    dict(phase='downturn', name='持续恶化', color='#e05252',
         sign='新订单<49连跌 · M1下探 · 社零负增长 · 从业人员<48',
         action='保住现金流:不裸辞、不加杠杆、砍掉亏损副业;现金为王,等灯亮。'),
    dict(phase='bottoming', name='低位企稳', color='#d9a441',
         sign='新订单止跌回49+ · M1走平 · 工业稳住 · 失业率见顶',
         action='开始准备但别行动:更新简历、补技能、盘点人脉;创业只做调研和轻试水。'),
    dict(phase='early_recovery', name='复苏初期', color='#7fb069',
         sign='新订单连续≥50 · PMI≥50 · 社零转正 · 从业人员仍<50(岗位还没回来)',
         action='换工作黄金准备期:企业已加单、竞争者还没动,投简历面试正当时;'
                '创业轻资产试水(一个人能跑通的最小闭环),重投入等岗位确认。'),
    dict(phase='expansion', name='上行', color='#3d8f5f',
         sign='从业人员≥50 · 失业率回落 · M1加速 · 社零>3%',
         action='兑现期:跳槽涨薪的黄金窗口(企业抢人);创业可加大投入,招人扩张。'),
    dict(phase='overheating', name='过热', color='#c2703d',
         sign='从业人员>51 · PPI>5.5 · M1冲顶回落 · CPI/社零高增',
         action='别追高:周期顶部跳槽=高位接盘;创业控杠杆、囤现金,准备过冬。'),
]

# ---------------- 复苏传导链(为什么有先后) ----------------

CHAIN = [
    dict(key='PMI_ORDER', name='订单', first=True,
         why='需求预期刚改善,企业先进货接单——成本最低、反悔最容易,所以最先动。'),
    dict(key='PMI', name='生产',
         why='订单落地必须生产,产能利用率先于用工恢复——开机器比招人便宜。'),
    dict(key='PPI_YOY', name='价格',
         why='生产放量后原料补库存,工业品价格回升——利润和提薪空间从这里来。'),
    dict(key='M1_YOY', name='活钱',
         why='货款回笼,企业账上活钱多起来——有钱才谈得上扩编。'),
    dict(key='PMI_EMP', name='就业',
         why='扩编最贵最不可逆(社保/赔偿/管理成本)。企业先用加班、外包、临时工消化订单,'
             '确认复苏是真的才招人——比订单晚 2~4 个季度。'),
    dict(key='RETAIL_YOY', name='消费',
         why='就业稳了收入才涨,收入涨了才敢消费——最后一环,也是下一轮周期的起点。'),
]


def build_forecast(as_of=None):
    """历史规律预判:新订单连续≥50 的起点 + 2~4 季度滞后 → 就业窗口预估。

    规则:
    - 找 PMI_ORDER 最近一段"连续 ≥50"的起点月
    - 滞后 6~12 个月(2~4 季度)为预估窗口
    - 失效条件:期间新订单跌破 49 → 计时作废
    诚实声明:这是历史规律推演,不是预测;只有 PMI_EMP 过线才是确认。
    """
    ind = next((i for i in db.get_indicators() if i['code'] == 'PMI_ORDER'), None)
    vt = (ind or {}).get('value_type') or 'level'
    s = db.get_series('PMI_ORDER', value_type=vt, as_of=as_of)
    if not s:
        return dict(ready=False, reason='暂无新订单数据')
    streak_start, streak_months = None, 0
    for p, v, _ in s:  # 序列升序
        if v is not None and v >= 50:
            if streak_months == 0:
                streak_start = p
            streak_months += 1
        elif v is not None and v < 49:  # 跌破49重置
            streak_start, streak_months = None, 0
        # 49~50 之间:不断链但也算不上"站稳",不计月
    latest_v = s[-1][1]
    latest_p = s[-1][0]
    out = dict(
        ready=bool(streak_start and streak_months >= 2),
        order_streak_start=streak_start,
        order_streak_months=streak_months,
        order_latest_period=latest_p,
        order_latest=latest_v,
        lag_note='历史规律:订单连续过线后 2~4 个季度(6~12 个月)从业人员指数跟上',
        confirm='以 PMI 从业人员指数 ≥50 为最终确认,期间新订单跌破 49 则重新计时',
        disclaimer='预判=历史规律推演,不是承诺。系统每月自动重算。',
    )
    if out['ready']:
        y, m = int(streak_start[:4]), int(streak_start[5:7])
        e = (y * 12 + m - 1) + 6   # 起点+6月
        l = (y * 12 + m - 1) + 12  # 起点+12月
        fmt = lambda t: '%d-%02d' % (t // 12, t % 12 + 1)
        out.update(earliest=fmt(e), latest=fmt(l),
                   window_text='%s ~ %s' % (fmt(e), fmt(l)))
    else:
        out.update(window_text='暂未形成:需要新订单连续 2 个月 ≥50 才开始计时')
    return out


def build_conclusion(item):
    """首页一句话结论:headline(判断) + 水平/趋势/最大压力/复苏信号 四格。

    只用真实指标推导,不编数据:
    - headline 按五态给固定白话
    - trend 由同步指标多数趋势态决定
    - pressure = 贡献分最低的指标(白话模板)
    - signal = 领先指标中"好转中"的占比
    """
    if not item or not item.get('indicators'):
        return None
    inds = item['indicators']
    phase = item.get('phase')
    score = item.get('score')
    headlines = {
        'downturn': '经济仍在下行通道,先保住现金流',
        'bottoming': '经济仍处低位,复苏尚未确认',
        'early_recovery': '订单已回暖,岗位还没跟上——卡在复苏初期',
        'expansion': '经济确认上行,就业正在改善',
        'overheating': '经济偏热,扩张的同时注意风险',
    }
    # 趋势:同步指标多数态(已剔除 ref 存档层)
    sync = [i for i in inds if i.get('layer') in ('coincident', 'leading')]
    rising = sum(1 for i in sync if i.get('state') == 'rising')
    falling = sum(1 for i in sync if i.get('state') == 'falling')
    if rising >= falling and rising > 0:
        trend_text, trend_cls = '多数指标好转中', 'up'
    elif falling > rising:
        trend_text, trend_cls = '多数指标仍在走弱', 'down'
    else:
        trend_text, trend_cls = '整体走平,待方向确认', 'flat'
    # 最大压力:贡献分最低的指标
    worst = min(inds, key=lambda i: i.get('score', 50))
    pressure_map = {
        'XA_FDI_YOY': '房地产投资深跌,拖累本地就业',
        'XA_FAI_YOY': '固定资产投资大幅收缩',
        'XA_RETAIL_YOY': '本地消费疲弱',
        'RETAIL_YOY': '全国消费几乎零增长',
        'PMI_EMP': '企业仍在净减员,岗位难找',
        'UNEMPLOY': '失业率仍在高位',
        'M1_YOY': '企业活钱不足,扩张意愿弱',
        'CPI_YOY': '内需物价偏弱,通缩压力',
        'CONF_INDEX': '消费者信心低迷',
        'SHRZ': '社会融资偏弱,扩张资金少',
        'PPI_YOY': '工业品价格异常',
        'IND_YOY': '工业生产偏弱',
        'METRO_CN': '出行人流未恢复',
    }
    pressure = dict(
        name=worst.get('name'), value=worst.get('value'),
        text=pressure_map.get(worst.get('code'), worst.get('name') + '偏弱'))
    # 复苏信号:领先指标好转占比(订单+社融+信心+固投)
    lead = [i for i in inds if i.get('layer') == 'leading']
    if lead:
        up = sum(1 for i in lead if i.get('state') == 'rising')
        ratio = up / len(lead)
        if ratio >= 0.5:
            signal = dict(cls='on', text='已出现(%d/%d项领先指标好转)' % (up, len(lead)))
        elif up > 0:
            signal = dict(cls='weak', text='初步苗头(%d/%d项好转,未过半)' % (up, len(lead)))
        else:
            signal = dict(cls='off', text='尚不充分,等待订单/融资回暖')
    else:
        signal = dict(cls='off', text='暂无领先指标数据')
    level_text = '高位' if score >= 65 else ('中位偏上' if score >= 50 else ('中位偏下' if score >= 40 else '低位'))
    return dict(
        headline=headlines.get(phase, '数据不足'),
        phase_cn=item.get('phase_cn'), score=score,
        level_text=level_text, month=item.get('month'),
        trend=dict(text=trend_text, cls=trend_cls),
        pressure=pressure, signal=signal,
    )


def playbook(as_of=None):
    """汇总:指标解读 + 周期路径 + 传导链 + 预判。"""
    return dict(
        guide=INDICATOR_GUIDE,
        phase_path=PHASE_PATH,
        chain=CHAIN,
        forecast=build_forecast(as_of),
        generated=datetime.now().strftime('%Y-%m-%d'),
    )
