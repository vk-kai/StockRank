# -*- coding: utf-8 -*-
"""第三人称记忆分析引擎: 不扮演任何人, 基于真实聊天数据回答关于「万凯」的问题
与第一人称分身完全独立 —— 结构化输出 {回答, 关键事实[含原文证据+置信], 不确定信息}
"""
import os, json
from agent_core import config
from agent_core.llm_client import llm_chat, extract_json, LLMError
from agent_core.knowledge import contacts, contact_info, facts, style_summary, load_contact_profile
from agent_core.memory.retrieval import retrieve
from agent_core.memory import human_feedback  # 人工介入闭环: 注入本人纠正记忆 + 低确定性判定

PROMPT_VER = 'v3'

_SYS = """你是「万凯」的私人记忆分析师, 服务于他的个人数字分身系统。用户会问关于万凯本人、他的朋友、关系与经历的问题, 你以第三人称、基于下方提供的真实聊天数据做客观分析。
只输出 JSON(不要 markdown 代码块):
{"回答": "2-5句, 直接回答用户的问题, 客观但口语化",
 "无法回答": false,
 "关键事实": [{"事实": "一句具体结论", "证据": [{"时间": "YYYY-MM-DD HH:MM", "对象": "与谁的聊天", "说话人": "万凯/对方", "原文": "聊天原话摘录"}], "置信": "高/中/低"}],
 "不确定信息": ["回答后的补充备注: 哪些点证据较弱/可进一步查证, 供用户参考; 大多数时候就是空数组, 严禁为了凑数硬写"],
 "候选回答": []}
规则:
1. 只用下方提供的真实数据回答, 绝不编造。性格/习惯/关系风格这类问题, 基于行为证据做侧写推断是完全允许且鼓励的 —— 只要结论挂靠了「关键事实」里的原文证据, 就不算数据不足
2. 「无法回答」= true 仅限一种情况: 用户问的核心问题在提供的所有数据里完全找不到任何依据(如问某次具体约定但记录里毫无痕迹); 此时「回答」写明缺什么数据, 并在「候选回答」里给出 2-3 个基于不同假设的猜测。其余情况一律 false, 大胆回答
3. 「不确定信息」只是备注, 不代表回答不了; 能回答的问题就不要写它
4. 每条关键事实必须至少附一条原文证据, 原文必须从提供的记录中原样摘录
5. 「回答」就是给用户看的话, 不要暴露 JSON 结构
6. 当用户问到两人之间的「梗 / 暗号 / 外号 / 内部笑话 / 习惯 / 私下称呼」时, 主动从相关记录里找出双方独有的玩笑、重复出现的梗、特殊称呼和默契, 并引用原话; 记录里确实找不到就明说「记录里没发现明显的梗」
7. 涉及敏感隐私(住址、证件、财务)一律模糊处理
8. 预测/趋势/局势类问题: 你不是算命先生 —— 先从【已梳理的相关人生事件】【万凯个人画像】提炼"他现在在哪、正在做什么", 再结合【近期公开信息】(网络检索)给出分析; 每个判断都要注明依据是"他的历史轨迹"还是"公开时事"; 时事部分如信息不足要明确说"没法实时核实", 绝不把猜测说成确定的事实; 最终落点应是具体的建议而非空泛预测
9. 全部中文"""

_SYS_ORACLE = """你是「知己」——陪伴万凯多年、读过他全部微信聊天记录的挚友, 但绝不是普通老友: 你比他更聪明、见识更广, 平时紧跟时事新闻、政策动向、经济和行业趋势, 是那种"既懂他、又看得清外面世界"的清醒人。他拿不定的事、看不透的人、想预测的局, 都会来找你聊。因为看过他所有的聊天, 你比任何人都了解他和他的每段关系; 因为够聪明有见识, 你总能在聊完事实后多给一层他自己没想到的洞察 —— 尤其是把政策/行业/大环境和他的个人处境连起来看。用户(万凯本人或他授权的人)会向你提问, 你像老朋友聊天一样回答。
只输出 JSON(不要 markdown 代码块):
{"回答": "像朋友聊天那样回答, 口语、直接、有温度, 可以吐槽可以共情, 不打官腔; 2-6句",
 "无法回答": false,
 "关键事实": [{"事实": "一句具体结论", "证据": [{"时间": "YYYY-MM-DD HH:MM", "对象": "与谁的聊天", "说话人": "万凯/对方", "原文": "聊天原话摘录"}], "置信": "高/中/低"}],
 "不确定信息": ["回答后的补充备注: 哪些点证据较弱/可进一步查证; 大多数时候就是空数组, 严禁为了凑数硬写"],
 "候选回答": []}
规则:
1. 你的底色是"懂他的朋友", 不是AI客服: 说话自然, 偶尔引用他自己的原话点醒他("你自己去年还跟XX说过…")
2. 事实全部来自下方真实数据, 绝不编造。性格/习惯这类问题, 基于行为证据做侧写推断是完全允许且鼓励的 —— 只要挂靠了原文证据就大胆说, 别动不动"没直接聊过"
3. 「无法回答」= true 仅限一种情况: 核心问题在所有提供的数据里完全找不到依据; 此时「回答」像朋友一样坦白"这个我真没印象, 别瞎猜", 并在「候选回答」里给出 2-3 个不同假设下的猜测。其余一律 false
4. 「不确定信息」只是给用户的备注, 不是弃答声明; 能回答就不要写
5. 每条关键事实必须至少附一条原文证据, 原文从提供的记录中原样摘录
6. 问到「梗 / 暗号 / 外号 / 习惯 / 私下称呼」时主动从记录里找双方独有的默契并引用原话
7. 涉及敏感隐私(住址、证件、财务)一律模糊处理
8. 预测/趋势/局势类问题: 你不是算命先生 —— 先从【已梳理的相关人生事件】【万凯个人画像】提炼"他现在在哪、正在做什么", 再结合【近期公开信息】(网络检索)给出分析; 每个判断都要注明依据是"他的历史轨迹"还是"公开时事"; 时事部分如信息不足要明确说"没法实时核实", 绝不把猜测说成确定的事实; 最终落点应是具体的建议而非空泛预测
9. 时事/政策是你的主场: 只要问题涉及政策、新规、社保公积金、楼市、就业、行业、经济、AI 等外部世界, 主动结合【近期公开信息】把宏观面讲透 —— 政策怎么变、对他意味着什么、和聊天记录里他的处境怎么对上; 但公开信息和他的个人记录要分开说清, 检索结果里没有的就直说"这个我没查到实信", 绝不编新闻
10. 你的洞察要"比他多想一步": 朋友式聊天是底色, 但每个回答尽量带一个他自己没想到的角度/风险/机会 —— 这是他来找你而不是找普通朋友的原因
11. 全部中文"""

_SYS_ADVICE = """你是「万凯」的决策顾问。用户(万凯本人)遇到一件新事拿不定主意, 会问「你觉得万凯会怎么做 / 这么做有什么优缺点 / 有什么不妥」。你要基于下方真实聊天数据所反映的万凯性格与行为模式来推演。
只输出 JSON(不要 markdown 代码块):
{"回答": "给用户看的完整决策咨询, 用\\n分四段: 一、【过去的万凯会怎么做】——基于历史行为模式的推断, 注明是推断并挂靠证据(如: 你在2025-03曾对XX说\\"…\\"，说明你倾向…); 二、【这样做的优缺点】——各1-3条, 具体、贴他的性格, 不空泛; 三、【有没有不妥】——只列有真实依据的隐忧, 严禁为了凑数硬找不妥, 确实没有就明确写\\"按你描述的情况, 没发现明显不妥\\"; 四、【建议】——一句可执行的话",
 "无法回答": false,
 "关键事实": [{"事实": "一句具体结论", "证据": [{"时间": "YYYY-MM-DD HH:MM", "对象": "与谁的聊天", "说话人": "万凯/对方", "原文": "聊天原话摘录"}], "置信": "高/中/低"}],
 "不确定信息": ["回答后的补充备注, 大多数时候就是空数组, 严禁为了凑数硬写"],
 "候选回答": []}
规则:
1. 推演必须挂靠真实证据: 每个行为模式判断都要能对应到关键事实里的证据; 绝不编造万凯没做过的事
2. 新事情本身聊天记录里没有, 这不是错误 —— 推演依据是万凯的性格和他在过去类似情境下的真实选择, 因此「无法回答」几乎总应该是 false(仅当万凯在数据里没有任何可挂靠的行为模式时才 true)
3. 「有没有不妥」宁缺毋滥: 没有真实依据就直说没有
4. 「不确定信息」「候选回答」仅配合「无法回答」= true 使用, 其余时候为空
5. 涉及敏感隐私(住址、证件、财务)一律模糊处理
6. 「回答」直接给用户看, 不要暴露 JSON 结构; 全部中文"""

_ADVICE_PAT = None

# 预测/局势类问题: 需要补充网络时事检索(个人聊天记录里没有"现在的世界")
_FUTURE_PAT = None


def _needs_web(message):
    import re as _re
    global _FUTURE_PAT
    if _FUTURE_PAT is None:
        _FUTURE_PAT = _re.compile(
            r'预测|预判|推演未来|未来.{0,6}(工作|方向|趋势|怎么|如何)|会变成什么样|'
            r'局势|形势|行情|大环境|就业|行业趋势|风口|新闻|最近外界|今年.{0,8}(趋势|局势)|'
            # 外部世界类: 政策/民生/经济/AI —— 知己的时事见识靠检索兜底
            r'政策|新规|出台|征求意见|文件精神|'
            r'楼市|房价|房市|限购|首付|房贷|公积金|社保|医保|养老金|退休|税|利率|汇率|'
            r'裁员|失业|招聘|找工作|跳槽|考公|考编|体制|国企|铁饭碗|外包|'
            r'经济|衰退|通胀|牛市|熊市|股市|A股|基金|理财|黄金|'
            r'AI|人工智能|大模型|机器人|前景|趋势|怎么看.{0,10}(行业|公司|单位|政策|形势)')
    return bool(_FUTURE_PAT.search(message or ''))


def _web_news(message, progress=None):
    """Bing 检索与问题相关的近期时事(无需 key)。任何失败都返回空串, 绝不阻塞回答。"""
    import re as _re, urllib.request, urllib.parse
    q = _re.sub(r'[，。？！、,\.\?!~\[E\]【】（）()]', ' ', message)[:40].strip()
    if not q:
        return ''
    try:
        if progress:
            progress('正在检索近期相关时事/新闻…')
        url = 'https://cn.bing.com/search?q=' + urllib.parse.quote(q) + '&count=8'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9'})
        html = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', 'ignore')
        items = _re.findall(r'<li class="b_algo".*?<h2>.*?<a[^>]*>(.*?)</a>.*?</h2>.*?(?:<p[^>]*>(.*?)</p>)?',
                            html, _re.S)
        out, seen = [], set()
        for title, snip in items:
            clean = lambda s: _re.sub(r'<[^>]+>', '', s or '').strip()
            t, s = clean(title), clean(snip)[:160]
            if t and t not in seen:
                seen.add(t)
                out.append(f'· {t}' + (f'：{s}' if s else ''))
            if len(out) >= 5:
                break
        if out and progress:
            progress(f'已获取 {len(out)} 条近期公开信息')
        return '\n'.join(out)
    except Exception:
        if progress:
            progress('时事检索不可用（网络受限），将仅基于你的个人数据回答')
        return ''


def _is_advice(message):
    """决策咨询类提问: 拿不定主意问'万凯会怎么做/优缺点/不妥'"""
    global _ADVICE_PAT
    import re as _re
    if _ADVICE_PAT is None:
        _ADVICE_PAT = _re.compile(
            r'拿不定主意|会怎么做|该怎么做|该怎么办|怎么选|怎么处理|优缺点|不妥|'
            r'要不要|值不值得|帮我拿主意|帮我决策|帮我分析下.{0,8}(该|选)|建议我怎么')
    return bool(_ADVICE_PAT.search(message or ''))

_HIST_N = 6


def _mentioned_contacts(text, hint=None):
    names = []
    if hint and contact_info(hint):
        names.append(hint)
    for c in contacts():
        n = c.get('姓名') or ''
        if n and len(n) >= 2 and n in text and n not in names:
            names.append(n)
    return names[:3]


def who(message):
    """识别提问中提到的人物候选(供前端弹窗确认)。
    匹配: 完整档案名 / 括号内别名(如 🌨加油鸭🌈(桃姐) 的'桃姐') / 去掉符号装饰的昵称。"""
    import re as _re
    msg = message
    cands = []
    for c in contacts():
        n = c.get('姓名') or ''
        if not n or n == '新朋友':
            continue
        hit = ''
        if len(n) >= 2 and n in msg:
            hit = n
        else:
            aliases = set()
            for m2 in _re.findall(r'[（(]([^）)]{1,15})[）)]', n):
                if len(m2) >= 2:
                    aliases.add(m2)
            clean = _re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', n)
            if len(clean) >= 2:
                aliases.add(clean)
            for a in aliases:
                if a in msg:
                    hit = a
                    break
        if hit:
            cands.append({'name': n, 'hit': hit, 'total': c.get('总消息', 0),
                          'last': (c.get('末次') or '')[:10], 'circle': c.get('圈层猜测', '')})
    cands.sort(key=lambda x: -x.get('total', 0))
    return cands[:6]


def _load_events():
    return config.jload(os.path.join(config.CACHE, 'events.json'), [])


def answer(history, message, contact_hint=None, extra_context=None, progress=None, confirm_names=None,
           persona=None):
    def _p(s):
        if progress:
            try:
                progress(s)
            except Exception:
                pass
    _p('正在定位相关人物与事件…')
    advice = _is_advice(message)
    if advice:
        _p('已识别为决策咨询类问题：将先检索万凯的真实行为模式，再推演他会怎么做…')
    if confirm_names:
        # 用户已在弹窗中确认过的人物, 直接采用(校验存在于档案)
        mentioned = [n for n in confirm_names[:4] if contact_info(n)]
        _p('已按你的确认锁定 {} 位人物：{}'.format(len(mentioned), '、'.join(mentioned) or '无'))
    else:
        mentioned = _mentioned_contacts(message, contact_hint)
    if mentioned:
        _p('已识别 {} 位相关人物：{}'.format(len(mentioned), '、'.join(mentioned[:5])))

    try:
        from agent_core.memory import indexer as _ix0
        n_corpus = len(_ix0.mem_index())
    except Exception:
        n_corpus = 0

    # 人物资料
    profiles = []
    for n in mentioned:
        info = contact_info(n) or {}
        line = (f"· {n}: {info.get('圈层猜测', '')}关系, 共聊 {info.get('总消息', 0)} 条"
                f"(万凯发 {info.get('我的发言', 0)} 条), {info.get('首次', '')[:10]} ~ {info.get('末次', '')[:10]}")
        cached = load_contact_profile(n)
        if cached:
            line += '\n  此前 AI 画像: ' + json.dumps(cached, ensure_ascii=False)[:600]
        profiles.append(line)

    # 事件记忆(时间线校验通过的事件): 提到人时只带相关事件;
    # 预测/局势类问题即使没提到人, 也带上全部事件(回答"我现在在干嘛、接下来怎么走"需要人生轨迹)
    events = []
    want_all = _needs_web(message)
    if mentioned or want_all:
        for ev in _load_events():
            blob = json.dumps(ev, ensure_ascii=False)
            if not mentioned or any(n in blob for n in mentioned):
                events.append(f"· [{ev.get('年','')}-{ev.get('月','')}] {ev.get('标题','')}: {ev.get('描述','')}")
    events = events[:12]

    # 相关聊天证据: 多人问题时对每个提到的人分别检索(各自享受联系人加成), 合并去重
    _p(f'正在从 {n_corpus} 条历史消息中检索原始聊天记录…')
    if len(mentioned) > 1:
        seen, merged = set(), []
        for n in mentioned:
            for m in retrieve(message, contact=n, top_k=8):
                key = (m.get('rel'), m.get('line'))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(m)
        # 按原有相关度近似保序: 每人首轮结果优先, 简单按时间混合
        rels = merged[:14]
    else:
        rels = retrieve(message, contact=mentioned[0] if mentioned else None, top_k=14)
    rels.sort(key=lambda m: m.get('t', ''))  # 时间序, 便于模型读上下文
    # 模板化系统消息(撤回/红包/拍一拍)信息密度低, 最多保留 2 条, 防止挤占文本证据
    sys_cnt, filt = 0, []
    for m in rels:
        c = m.get('c', '')
        is_sys = '撤回了一条消息' in c or c.startswith(('你领取了', '领取了')) or '拍了拍' in c
        if is_sys:
            sys_cnt += 1
            if sys_cnt > 2:
                continue
        filt.append(m)
    rels = filt
    _p(f'检索完成：命中 {len(rels)} 条相关记录'
       + (f'，已过滤 {sys_cnt} 条模板消息' if sys_cnt > 2 else '')
       + ('，另直取 2 人近期对话原文' if len(mentioned) > 1 else ''))
    mem_text = '\n'.join(
        f"[{m['t'][:16]} | {m['ct']} | {'万凯' if m['s'] == '我' else m['s']}] {m['c'][:80]}"
        for m in rels)

    # 近期真实对话原文(程序直取而非检索): 保证分析永远基于该联系人最近的真实交流,
    # 避免检索偏差导致"明明有大量聊天却分析不出东西"
    try:
        from agent_core.memory import indexer as _ix
        from agent_core.analysis import relationships as _rl
        f2n, _n2f = _rl.name_maps()
        blocks = []
        for n in mentioned[:2]:
            rels_n = {r for r, nm in f2n.items() if nm == n}
            rows = [it for it in _ix.mem_index() if it['rel'] in rels_n and it.get('ty') == 'text']
            is_gf = (contact_info(n) or {}).get('类别') == '群友'
            if not rows and is_gf:
                # 群友: 无 1:1 会话, 按发言人从群聊里汇总
                rows = [it for it in _ix.mem_index() if it['s'] == n and it.get('ty') == 'text']
            rows.sort(key=lambda x: x['t'])
            if rows:
                if is_gf:
                    txt = '\n'.join(f"[{m['t'][:16]}|{m['ct'][:14]}] {n}: {m['c'][:70]}"
                                    for m in rows[-25:])
                    blocks.append(f"· 「{n}」在群里的最近发言(共{len(rows)}条文本, 取最近25条):\n{txt}")
                else:
                    txt = '\n'.join(f"[{m['t'][:16]}] {'万凯' if m['s'] == '我' else n}: {m['c'][:70]}"
                                    for m in rows[-25:])
                    blocks.append(f"· 与{n}的最近对话(共{len(rows)}条文本, 取最近25条):\n{txt}")
                _p(f'已调取{"「" + n + "」" if is_gf else "与「" + n + "」的"}最近 25 条原文'
                   f'（共 {len(rows)} 条文本消息）')
        recent_txt = '\n'.join(blocks)
    except Exception:
        recent_txt = ''

    f_ = facts()
    samples = '\n'.join('- ' + x for x in (f_.get('代表性发言样本_50条') or [])[:10])
    hist_txt = '\n'.join(
        f"{'万凯(我)' if (h or {}).get('speaker') == '我' else '分析师'}: {h.get('content', '')}"
        for h in (history or [])[-_HIST_N:] if isinstance(h, dict) and h.get('content'))

    parts = [f"【问题】{message}"]
    if hist_txt:
        parts.append(f"【最近对话】\n{hist_txt}")
    parts.append(f"【提到的人物资料】\n" + ('\n'.join(profiles) if profiles else '(未提到具体联系人)'))
    if events:
        parts.append("【已梳理的相关人生事件】\n" + '\n'.join(events))
    parts.append(f"""【相关真实聊天记录(可作证据引用)】
{mem_text if mem_text else '(未检索到相关记录)'}""")
    if recent_txt:
        parts.append(f"【近期真实对话原文(程序直取, 优先作为了解双方互动的依据)】\n{recent_txt}")
    if extra_context:
        parts.append(f"【关系网络结构化背景(程序统计, 优先可信)】\n{extra_context}")
    if want_all:
        web = _web_news(message, _p)
        if web:
            parts.append(f"【近期公开信息(网络检索自 Bing, 截取摘要)】\n{web}")
        else:
            parts.append("【近期公开信息】(检索不可用, 请基于你的知识回答并在回答中注明无法获取实时信息)")
        # 日程大事: 本人手动记录的每日事项, 是"他现在在干什么"最直接的依据
        try:
            from agent_core.analysis import daily_log as _dlog
            dd = _dlog.digest()
            if dd:
                parts.append(f"【指尖时光日程记录(本人手动记录的每日大事, 按月聚合)】\n{dd}")
        except Exception:
            pass
    try:
        from agent_core.simulation.engine import sim_note_for
        sim = sim_note_for(contact_hint or '', limit=4)
        if sim:
            parts.append(f"{sim}\n(以上为虚拟推演, 回答涉及这些内容时必须注明【虚拟推演】)")
    except Exception:
        pass
    fb = human_feedback.context_note(message, contact=contact_hint or '')
    if fb:
        parts.append(fb)
    parts.append(f"【万凯风格速览】\n{style_summary()[:600]}")
    if samples:
        parts.append(f"【万凯代表性发言(节选)】\n{samples}")
    # 已生成的个人画像: 问答"我是怎样的人"类问题时的关键背景, 缺了模型会误以为数据不足
    try:
        me_prof = config.jload(os.path.join(config.CACHE, 'profile_me.json'), None)
        if isinstance(me_prof, dict) and me_prof:
            me_txt = json.dumps(me_prof, ensure_ascii=False)[:1600]
            parts.append(f"【万凯个人画像(AI 依据全部数据生成, 可直接引用其中的性格/习惯结论)】\n{me_txt}")
    except Exception:
        pass
    user = '\n\n'.join(parts)
    _p(f'证据就绪（{len(rels)} 条检索记录 + 近期对话原文 + {len(events)} 条人生事件），正在整理证据链并生成分析…（约需 1-2 分钟）')

    # 旁观者人设: 朋友口吻; 决策咨询类仍走顾问 prompt(本就是给建议的语境)
    sys = _SYS_ADVICE if advice else (_SYS_ORACLE if persona == 'oracle' else _SYS)
    out = extract_json(llm_chat([{'role': 'system', 'content': sys},
                                 {'role': 'user', 'content': user}], temperature=0.5))
    reply_text = out.get('回答') or ''
    if isinstance(reply_text, list):
        reply_text = ' '.join(str(x) for x in reply_text)
    # 低确定性判定(程序化): 仅当模型明确"无法回答"(核心问题无数据)或回答为空时才触发人工介入;
    # 「不确定信息」「低置信事实」只是备注, 不再触发弹窗 —— 避免开放性问题几乎必弹窗的过敏感问题
    cands = out.get('候选回答') or []
    if isinstance(cands, str):
        cands = [cands]
    nr = out.get('无法回答')
    refused = nr is True or (isinstance(nr, str) and nr.strip().lower() in ('true', '是', 'yes'))
    unsure = refused or not (reply_text or '').strip()
    return {'reply': (reply_text or '(AI 未返回回答)').strip(), 'analysis': out,
            'unsure': bool(unsure), 'candidates': [str(c).strip()[:200] for c in cands if str(c).strip()][:3]}
