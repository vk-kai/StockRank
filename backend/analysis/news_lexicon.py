# -*- coding: utf-8 -*-
"""本地新闻利好利空分析器（零 AI 调用，替代 LLM 新闻判断，省 token）。

设计目标：
- 输出与原 AI 分析完全兼容的字段结构，下游零改动：
  批量路径 → dict(level/impact_type/event_type/core_event/reason/impact_market/related_sector/action_suggestion)
  单条路径 → Markdown 文本，标题行 `# X级（XX/100）` 供 extract_score_from_analysis 提取评分，
             分数进入 news_analysis_cache → 前端情绪分走势（compute_overall_score 兼容）。
- 算法：A股财经事件模式库（正则）+ 情感词典 + 幅度修饰词 + 否定词处理。
  命中带权事件 → 累加到 50 分基线 → 夹取 0-100。
- 局限（相对 AI）：无法理解长上下文与隐含逻辑（如"金价跌→利空黄金利好金店"）。
  规则抓的是高频、模式化事件（业绩预增/中标/回购/立案调查等），这类事件占日常新闻大头。

切换规则（无需额外配置）：AI 未启用 → 直接走本模块；AI 启用 → 先走 LLM，
LLM 失败（预算耗尽/限流/超时/解析失败）自动回退本模块（见 ai_analyzer.batch_analyze_news/analyze_news）。
词表均可直接在本文件维护扩充。
"""
import re
import time

# ============================== 事件模式库 ==============================
# (正则, 权重, 事件名, 是否重大事件, 板块提示)
# 权重：正=利好 / 负=利空，直接加到 50 分基线上。
EVENT_RULES = [
    # ---- 利好事件 ----
    (r'(业绩预(增|盈)|预增|扭亏为盈|净利润?(同比)?(增|升)(长|幅)?\s*[0-9一二三四五六七八九十百千.%]+|净利.{0,6}超预期)', 22, '业绩预增', True, []),
    (r'(中标|中选|赢得了?标|获得.{0,8}(订单|合同|项目)|签署.{0,8}(合同|订单)|签订.{0,8}(合同|订单|协议))', 18, '中标/签单', True, []),
    (r'(并购|重组|收购|借壳|资产注入)', 20, '并购重组', True, []),
    (r'(回购|注销.{0,4}回购股份)', 16, '股份回购', False, []),
    (r'(增持)', 14, '股东增持', False, []),
    (r'(获批|获得批准|核准注册|取得.{0,6}注册证|获得.{0,6}资质)', 18, '产品/资质获批', False, []),
    (r'(涨价|提价|价格上调|上调.{0,6}价格)', 14, '产品涨价', False, []),
    (r'(分红|派息|特别分红|提高分红)', 10, '分红派息', False, []),
    (r'(技术?.{0,4}突破|攻克.{0,6}难题|打破.{0,8}(垄断|封锁))', 16, '技术突破', False, []),
    (r'(政策|规划|方案|意见|措施|补贴).{0,12}(支持|扶持|利好|加快|推动|加码|发力)', 18, '政策利好', True, []),
    (r'(大额|巨额|重大)?合同.{0,8}(签订|落地|生效)', 16, '合同落地', True, []),
    (r'(满产满销|供不应求|订单.?排满|产能利用率?.{0,6}(满|高))', 14, '供不应求', False, []),
    (r'(降价?.{0,6}(抢|占)(市场|份额)|市占率.{0,6}(提升|上升)|份额.{0,6}提升)', 10, '份额提升', False, []),
    (r'(与.{1,12}(华为|英伟达|特斯拉|苹果|小米|比亚迪|腾讯|阿里|字节).{0,8}(合作|签约|达成))', 14, '大厂合作', False, []),
    (r'(纳入.{0,8}指数|调入.{0,8}(指数|样本)|MSCI|富时罗素)', 10, '纳入指数', False, []),
    (r'(摘帽|撤销.{0,6}风险警示|脱帽)', 14, 'ST摘帽', False, []),
    # ---- 利空事件 ----
    (r'(立案(调查|侦查)?)', -35, '立案调查', True, []),
    (r'(业绩预(减|亏)|预亏|首亏|净利润?(同比)?(下|减|降)(滑|少|低)?\s*[0-9一二三四五六七八九十百千.%]+|净利.{0,6}不及预期)', -24, '业绩预亏', True, []),
    (r'(减持)', -18, '股东减持', False, []),
    (r'(质押)', -10, '股权质押', False, []),
    (r'(行政处罚|罚款|警示函|监管函|问询函|通报批评|公开谴责)', -25, '监管处罚', True, []),
    (r'(退市|终止上市|退市风险|触及.{0,6}退市)', -40, '退市风险', True, []),
    (r'(诉讼|仲裁|被起诉|涉诉)', -12, '诉讼仲裁', False, []),
    (r'(冻结|查封|扣押)', -18, '资产冻结', False, []),
    (r'(破产|重整申请|清算)', -35, '破产风险', True, []),
    (r'(降价?.{0,6}(竞争|战)|价格战|降价潮)', -12, '价格战', False, []),
    (r'(政策|规定|条例|办法).{0,12}(限制|收紧|禁止|整顿|处罚|趋严)', -20, '政策收紧', True, []),
    (r'(安全事故|爆炸|坍塌|火灾|泄漏)', -25, '安全事故', True, []),
    (r'(召回)', -18, '产品召回', False, []),
    (r'(失去.{0,6}(订单|合同|客户)|终止.{0,6}(合作|合同)|解除.{0,6}(合同|协议))', -16, '丢单/解约', False, []),
    (r'(商誉减值|计提减值|资产减值)', -22, '资产减值', True, []),
    (r'(戴帽|被实施.{0,6}风险警示|披星戴帽)', -28, 'ST戴帽', True, []),
    (r'(股东.{0,6}(平仓|强平)|爆仓)', -20, '平仓风险', True, []),
    (r'(停产|停工|检修)', -12, '停产停工', False, []),
    (r'(解禁)', -8, '限售解禁', False, []),
    (r'(辞职|离职|卸任).{0,8}(董(事)?长|总经理|高管|财务总监)', -8, '高管变动', False, []),
]

# 幅度修饰词：放大/缩小命中权重
MAGNIFIER_RE = re.compile(r'(巨额|重大|大幅|超预期|创.{0,4}新高|历史性|龙头|全球|首次|数百亿|数十亿|上百亿)')
DAMPENER_RE = re.compile(r'(小幅|部分| slight|一般|例行|意向|框架|拟|筹划中|传闻|据悉|或将被)')

# 否定词：命中前 2 字符内出现 → 反向并衰减
NEGATION_WORDS = ('不', '未', '无', '难', '非', '没', '终止', '取消')

# 中性内容压制：纯叙事/意向/人事/论坛类，没有强事件时向 50 拉回
NEUTRAL_TOPIC_RE = re.compile(r'(框架协议|战略合作意向|签署备忘录|论坛|峰会|讲话|致辞|参观|调研接待|机构调研|投资者关系|人事任免|聘任|聘请|例会|年报问询回复)')

# 行情异动类 → event_type
MARKET_MOVE_RE = re.compile(r'(涨停|跌停|闪崩|跳水|异动|拉升|大跌|大涨|暴涨|暴跌|触及涨停|封板|炸板)')

# 影响市场
US_MARKET_RE = re.compile(r'(美联储|美股|纳指|纳斯达克|道琼|标普|美元|特斯拉|苹果|英伟达|微软|meta|openai)')
GLOBAL_MARKET_RE = re.compile(r'(原油|opec|黄金|白银|地缘|关税|汇率|离岸人民币|全球市场|海外市场|大宗商品)')

# 延迟影响类
DELAYED_IMPACT_RE = re.compile(r'(规划|中长期|未来.{0,4}(三年|五年)|愿景|蓝图|趋势|深化|逐步)')

# ============================== 板块关键词 → 板块/龙头 ==============================
# (板块名, [关键词], 龙头展示名)。顺序即匹配优先级，先长词后短词。
SECTOR_RULES = [
    ('半导体', ['半导体', '芯片', '晶圆', '光刻', '封测', '存储芯片', '先进制程'], '中芯国际/北方华创'),
    ('AI算力', ['算力', '人工智能', '大模型', 'AI', 'CPO', '光模块', '数据中心', '智算'], '寒武纪/中际旭创'),
    ('机器人', ['机器人', '人形机器人', '减速器', '执行器', '伺服'], '汇川技术/绿的谐波'),
    ('消费电子', ['消费电子', '果链', '苹果链', '面板', '折叠屏', 'AIPC'], '立讯精密/京东方'),
    ('光伏', ['光伏', '组件', '硅片', '电池片', '逆变器', '钙钛矿'], '隆基绿能/阳光电源'),
    ('锂电池', ['锂电', '动力电池', '储能电池', '电解液', '正极', '负极', '隔膜', '固态电池'], '宁德时代/亿纬锂能'),
    ('新能源车', ['新能源车', '电动汽车', '智能驾驶', '自动驾驶', '汽车零部件', '整车'], '比亚迪/赛力斯'),
    ('创新药', ['创新药', 'CXO', '医药研发', 'GLP-1', 'ADC', '疫苗'], '恒瑞医药/药明康德'),
    ('医疗器械', ['医疗器械', '医疗设备', '骨科', 'IVD', '体外诊断'], '迈瑞医疗'),
    ('白酒', ['白酒', '名酒', '酒企'], '贵州茅台/五粮液'),
    ('食品饮料', ['食品', '饮料', '乳业', '调味品', '预制菜', '零食'], '伊利股份/东鹏饮料'),
    ('银行', ['银行', '信贷', '存款利率', 'LPR'], '招商银行/工商银行'),
    ('券商', ['券商', '证券行业', '投行', '经纪业务'], '中信证券/东方财富'),
    ('保险', ['保险', '寿险', '财险'], '中国平安'),
    ('房地产', ['房地产', '地产', '物业', '商品房', '楼市'], '保利发展/万科A'),
    ('军工', ['军工', '国防', '导弹', '航空发动机', '军贸', '军品'], '中航沈飞/中航西飞'),
    ('贵金属有色', ['黄金', '白银', '稀土', '铜价', '铝价', '锂矿', '有色金属', '钴', '镍'], '紫金矿业/北方稀土'),
    ('煤炭', ['煤炭', '焦煤', '动力煤', '煤价'], '中国神华'),
    ('钢铁', ['钢铁', '特钢', '钢材', '铁矿石'], '宝钢股份'),
    ('化工', ['化工', '纯碱', '磷化工', '化肥', '农药', '钛白粉', 'MDI'], '万华化学'),
    ('石油石化', ['原油', '石油', '油价', 'OPEC', '天然气', 'LNG'], '中国石油/中国海油'),
    ('农业养殖', ['生猪', '猪价', '猪肉', '养殖', '种业', '转基因', '水产'], '牧原股份/隆平高科'),
    ('电力公用', ['电力', '电网', '特高压', '核电', '风电', '水电', '绿电', '虚拟电厂'], '长江电力/国电南瑞'),
    ('通信', ['通信', '5G', '6G', '卫星互联网', '光通信', '运营商'], '中兴通讯/中际旭创'),
    ('计算机', ['软件', '信创', '操作系统', '数据库', '网络安全', '国产替代', '数据要素', '数字经济'], '金山办公/太极股份'),
    ('传媒游戏', ['游戏', '传媒', '影视', '短剧', '出版', '电竞', '版号'], '腾讯控股/恺英网络'),
    ('航运港口', ['航运', '集运', '港口', '物流', '运价', 'BDI'], '中远海控'),
    ('航空机场', ['航空', '机场', '民航', '客机', 'C919'], '中国国航'),
    ('基建建筑', ['基建', '建筑', '一带一路', '市政', '城中村'], '中国建筑'),
    ('工程机械', ['工程机械', '挖掘机', '起重机', '挖机'], '三一重工/恒立液压'),
    ('家电', ['家电', '白电', '空调', '冰箱', '洗衣机', '厨电'], '美的集团/格力电器'),
    ('旅游酒店', ['旅游', '酒店', '免税', '文旅', '出行链'], '中国中免'),
    ('环保', ['环保', '固废', '污水', '垃圾焚烧', '环境治理'], '瀚蓝环境'),
    ('氢能', ['氢能', '燃料电池', '电解槽', '加氢站'], '亿华通'),
    ('商业航天', ['商业航天', '卫星', '火箭', '星链', '太空'], '中国卫通'),
    ('低空经济', ['低空经济', 'eVTOL', '无人机', '通航'], '亿航智能'),
    ('汽车整车', ['汽车', '车市', '乘用车', '新势力'], '比亚迪/赛力斯'),
]


def _find_event_hits(text):
    """返回命中事件列表 [(事件名, 权重, 是否重大, 板块提示, 原始匹配串)]，按事件名去重。"""
    hits = []
    seen = set()
    for pattern, weight, name, major, sectors in EVENT_RULES:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        if name in seen:
            continue
        seen.add(name)
        w = float(weight)
        # 幅度修饰
        if MAGNIFIER_RE.search(text):
            w *= 1.25
        elif DAMPENER_RE.search(text):
            w *= 0.7
        # 否定检测：命中前 2 字符
        pre = text[max(0, m.start() - 2):m.start()]
        if any(neg in pre for neg in NEGATION_WORDS):
            w = -w * 0.8
        hits.append((name, w, major, sectors, m.group(0)))
    return hits


def _match_sectors(text):
    """返回命中板块名列表（最多 4 个）。"""
    out = []
    for name, keywords, _leader in SECTOR_RULES:
        for kw in keywords:
            if kw.lower() in text.lower():
                out.append(name)
                break
        if len(out) >= 4:
            break
    return out


def analyze_news_local(title, content=''):
    """本地规则分析单条新闻，返回与原 AI 批量分析同构的 dict。

    字段：score/level/impact_type/event_type/core_event/reason/impact_market/related_sector/action_suggestion
    """
    title = (title or '').strip()
    text = f'{title} {content or ""}'.strip() or title
    text = re.sub(r'\s+', ' ', text)[:2000]

    score = 50.0
    hits = _find_event_hits(text)
    has_major = False
    pos_names, neg_names = [], []
    for name, w, major, _sectors, _raw in hits:
        score += w
        has_major = has_major or major
        (pos_names if w > 0 else neg_names if w < 0 else []).append(name)

    # 中性内容压制：仅弱事件（|权重|<=14）且无重大事件时，向 50 拉回 40%
    weak_only = hits and all(abs(w) <= 14 for _n, w, _mj, _s, _r in hits)
    if NEUTRAL_TOPIC_RE.search(text) and (not hits or weak_only) and not has_major:
        score = 50 + (score - 50) * 0.6
    # 无任何方向性命中 → 纯中性叙事
    if not hits:
        score = 50.0

    score = int(max(0, min(100, round(score))))

    # 相关板块：事件提示 + 文本匹配
    sectors = _match_sectors(text)

    # 影响市场
    if US_MARKET_RE.search(text):
        impact_market = '美股'
    elif GLOBAL_MARKET_RE.search(text):
        impact_market = '全球'
    else:
        impact_market = 'A股'

    # 事件类型 / 影响时滞
    event_type = '行情异动' if MARKET_MOVE_RE.search(text) else '新闻'
    impact_type = '延迟影响' if DELAYED_IMPACT_RE.search(text) else '即时影响'

    # 级别与推送建议（is_important_news 消费：level=='重大' or action=='立即推送'）
    # 强分（≥70/≤30）直接判重大；重大事件模式命中且偏离开中性 15 分以上也判重大
    if score >= 70 or score <= 30 or (has_major and abs(score - 50) >= 15):
        level = '重大'
    else:
        level = '一般'
    action_suggestion = '立即推送' if level == '重大' else '忽略'

    # 一句话核心事件
    if pos_names and (score >= 55 or not neg_names):
        core_event = f"利好：{'、'.join(pos_names[:2])}"
    elif neg_names:
        core_event = f"利空：{'、'.join(neg_names[:2])}"
    else:
        core_event = title[:40] if title else '中性资讯'

    # 影响逻辑
    sector_txt = f"，关联板块：{'、'.join(sectors)}" if sectors else ''
    if pos_names or neg_names:
        kw_txt = '、'.join((pos_names + neg_names)[:3])
        direction = '利好' if score >= 55 else ('利空' if score <= 45 else '方向不明')
        reason = f"命中{direction}要素『{kw_txt}』{sector_txt}，规则评分 {score}/100"
    else:
        reason = f"未命中方向性事件要素，按中性资讯处理{sector_txt}"

    return {
        'score': score,
        'level': level,
        'impact_type': impact_type,
        'event_type': event_type,
        'core_event': core_event,
        'reason': reason,
        'impact_market': impact_market,
        'related_sector': sectors,
        'action_suggestion': action_suggestion,
    }


def _sector_leader(name):
    for sname, _kws, leader in SECTOR_RULES:
        if sname == name:
            return leader
    return '--'


def format_markdown(analysis, title=''):
    """把本地分析 dict 渲染成与原 AI 单条分析同构的 Markdown。

    标题行 `# X级（XX/100）` 保证 extract_score_from_analysis 可提取评分。
    """
    score = int(analysis.get('score') or 50)
    if score >= 55:
        grade = '利好'
    elif score <= 45:
        grade = '利空'
    else:
        grade = '中性'
    core = analysis.get('core_event') or title[:40] or '中性资讯'
    sectors = analysis.get('related_sector') or []

    lines = [f"# {grade}（{score}/100）", '', f"📌 {core}", '']
    if sectors:
        lines += ['| 赛道 | 龙头 |', '|---|---|']
        for s in sectors[:3]:
            lines.append(f"| {s} | **{_sector_leader(s)}** |")
        lines.append('')
    if grade == '中性':
        lines += ['兑现度：⏳无实质影响', '持续性：📈短期', '主线概率：🚀低', '',
                  f"结论：⚖️ {analysis.get('reason', '中性资讯，无明确方向')}"]
    elif grade == '利好':
        lines += ['兑现度：⏳即期（规则判定，事件类）', '持续性：📈中期', '主线概率：🚀中高', '',
                  f"结论：✅ {analysis.get('reason', '')}"]
    else:
        lines += ['兑现度：⏳即期（规则判定，事件类）', '持续性：📉关注事态演进', '主线概率：🚀低', '',
                  f"结论：⚠️ {analysis.get('reason', '')}"]
    lines.append('')
    lines.append('> 本地词典规则分析（非AI）：命中事件模式与板块关键词自动判定，复杂语境可能存在偏差')
    return '\n'.join(lines)


def analyze_batch_local(news_items):
    """批量本地分析。news_items: [{id,title,content},...] → {id: analysis_dict}。"""
    out = {}
    for item in news_items or []:
        nid = item.get('id')
        if not nid:
            continue
        out[nid] = analyze_news_local(item.get('title', ''), item.get('content', ''))
    return out


def analyze_news_local_sync(title, content):
    """单条分析入口：返回 {success, analysis(markdown), duration}，与 analyze_news 返回结构一致。"""
    start = time.time()
    result = analyze_news_local(title, content)
    md = format_markdown(result, title)
    return {
        'success': True,
        'analysis': md,
        'duration': round((time.time() - start) * 1000, 1),
    }
