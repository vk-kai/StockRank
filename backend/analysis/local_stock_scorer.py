# -*- coding: utf-8 -*-
"""全市场股票本地多因子打分器（零 AI 调用，替代 LLM 批量打分，省 token）。

背景：原 stock_scorer 用 LLM 对全市场 ~5000 只股票打 0-100 分，输入只有
{name, l1, l2, value(总市值元), pe}——AI 实质上也是在"行业景气 + 市值 + 估值"上做推断。
本模块用确定性规则复刻同样逻辑：

  行业景气基分(l1/l2 关键词匹配) + 市值档 + PE 估值档 + 板块代码 + 名称信号 + 确定性微抖动
  → 0-100 分（50 中性，≥50 红侧 / <50 绿侧），输出 {score, label, reason} 与 AI 版同构，
  scores.json / 云图着色 / 筛选 / 悬浮展示 全部零改动。

优点：5000 只毫秒级完成、可复现、无 token 开销；词表可直接在本文件维护。
局限：无法像 LLM 一样"认识"具体公司，护城河/管理层等软信息不参与评分。

切换开关：ai_config.json 设 "score_engine": "ai" 切回 LLM 打分；缺省 "local"。
"""
import re

# ============================== 行业景气规则（顺序即优先级，先专后泛） ==============================
# (关键词列表, 基分, 行业标签)
INDUSTRY_RULES = [
    (['半导体', '芯片', '晶圆', '光刻', '封测', '算力', '人工智能', '大模型', 'GPU', 'CPO', '光模块',
      '机器人', '减速器', '固态电池', '商业航天', '卫星', '低空经济', 'eVTOL', '创新药', 'CXO', 'GLP-1',
      '军工电子', '国产替代', '信创', '数据要素', '脑机', '量子'], 72, '高景气硬科技'),
    (['光伏', '储能', '锂电', '动力电池', '新能源车', '智能驾驶', '自动化', '激光', '工业母机',
      '医疗器械', '消费电子', '面板', '游戏', '传媒'], 65, '成长制造'),
    (['白酒', '食品', '饮料', '家电', '免税', '旅游', '医药', '中药', '疫苗', '美容护理'], 58, '白马消费医药'),
    (['银行', '保险', '券商', '证券', '期货', '多元金融'], 52, '金融'),
    (['电力', '电网', '水电', '核电', '风电', '公路', '铁路', '港口', '机场', '通信', '燃气', '水务', '环保'], 50, '公用稳定'),
    (['化工', '有色', '钢铁', '煤炭', '石油', '天然气', '航运', '养殖', '农业', '造纸', '水泥', '玻璃',
      '锂矿', '黄金', '铜', '铝', '稀土', '机械', '汽车'], 45, '周期制造'),
    (['房地产', '地产', '基建', '建筑', '装饰', '建材', '园林'], 38, '地产链'),
    (['教育', '院线', '会展'], 30, '承压行业'),
]

INDUSTRY_DEFAULT = (50, '一般行业')

# ============================== 市值档（value=总市值, 元） ==============================
def cap_factor(value):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0
    if v >= 2000e8:
        return 6, '超大市值'
    if v >= 500e8:
        return 4, '大市值'
    if v >= 100e8:
        return 2, '中市值'
    if v >= 30e8:
        return 0, '中小市值'
    if v > 0:
        return -3, '微盘'
    return 0, '市值未知'

# ============================== 估值档（PE） ==============================
def pe_factor(pe, industry_base):
    """PE 分档；高景气行业对高 PE 更宽容（惩罚减半）。"""
    growth = industry_base >= 65
    try:
        p = float(pe)
    except (TypeError, ValueError):
        return 0, 'PE未知'
    if p < 0:
        adj, label = (-5 if growth else -10), '亏损'
    elif p < 15:
        adj, label = 6, '低估值'
    elif p < 25:
        adj, label = 4, '估值偏低'
    elif p < 40:
        adj, label = 0, '估值合理'
    elif p < 60:
        adj, label = (-2 if growth else -4), '估值偏高'
    elif p < 100:
        adj, label = (-3 if growth else -7), '估值贵'
    else:
        adj, label = (-5 if growth else -10), '估值泡沫'
    return adj, label

# ============================== 名称信号 ==============================
NAME_THEME_WORDS = ('科技', '智能', '创新', '新能', '数字', '光电')
ST_RE = re.compile(r'ST|退')


def name_factor(name):
    """返回 (加分, 是否ST/退市风险)。题材词小加分（封顶2），ST 后续硬压。"""
    bonus = 0
    for w in NAME_THEME_WORDS:
        if w in (name or ''):
            bonus += 1
            if bonus >= 2:
                break
    return bonus, bool(ST_RE.search(name or ''))


def board_factor(code):
    head2 = code[:2]
    if code.startswith('688'):
        return 2      # 科创板：硬科技/高端制造
    if head2 in ('30',):
        return 1      # 创业板：成长
    if code[:1] in ('8', '4') or code.startswith('92'):
        return -3     # 北交所：流动性折价
    return 0


def label_from_score(score):
    """0-100 → 9 档标签（与 SCORE_BUCKETS 分带一致）。"""
    if score >= 90:
        return '顶级'
    if score >= 80:
        return '优秀'
    if score >= 70:
        return '较优'
    if score >= 60:
        return '尚可'
    if score >= 50:
        return '中性偏多'
    if score >= 41:
        return '中性偏空'
    if score >= 26:
        return '偏谨慎'
    if score >= 11:
        return '谨慎'
    return '极谨慎'


def _match_industry(l1, l2):
    """l2 优先（更细分），l1 兜底；按规则表顺序取第一个命中。"""
    for text in (l2, l1):
        if not text:
            continue
        for keywords, base, label in INDUSTRY_RULES:
            for kw in keywords:
                if kw in text:
                    return base, label, kw
    return INDUSTRY_DEFAULT[0], INDUSTRY_DEFAULT[1], ''


def _deterministic_jitter(code):
    """代码数字和 → ±1.5 的确定性微抖动：打散同档股票，保证云图区分度（每次运行结果一致）。"""
    s = sum(int(d) for d in code if d.isdigit())
    return (s % 7 - 3) * 0.5


def score_batch(batch):
    """对一批 [(code, info)] 本地打分，返回 {code: {score, label, reason}}。

    输入/输出与 _call_ai_batch 的归一化结果完全同构，可直接接 merge_batch_scores。
    reason 不含"信息不足"字样（该词被 insufficient 重评 scope 用作标记）。
    """
    out = {}
    for code, info in batch or []:
        name = info.get('name') or code
        l1, l2 = info.get('l1') or '', info.get('l2') or ''
        base, ind_label, _kw = _match_industry(l1, l2)

        cap_adj, cap_label = cap_factor(info.get('value'))
        pe_adj, pe_label = pe_factor(info.get('pe'), base)
        bd_adj = board_factor(code)
        theme_bonus, is_st = name_factor(name)

        score = base + cap_adj + pe_adj + bd_adj + min(theme_bonus, 2) + _deterministic_jitter(code)
        score = int(max(0, min(100, round(score))))

        if is_st:
            score = min(score, 15)  # ST/退市风险硬压到 0-15
            reason = 'ST/退市风险警示'
        else:
            reason = f'{ind_label}·{cap_label}·{pe_label}'[:30]

        out[code] = {
            'score': max(0, min(100, score)),
            'label': label_from_score(score),
            'reason': reason,
        }
    return out
