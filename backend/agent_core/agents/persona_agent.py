# -*- coding: utf-8 -*-
"""第一人称数字分身: 你就是万凯本人, 在微信里和某联系人聊天
- 范例分层回退(本人→同圈层→全局), 按当前消息场景挑选
- 相关历史记忆来自统一检索层(BM25+2-gram 融合)
- prompt 少规则、重分布: 让模型学范例的节奏, 而不是背规则
"""
from agent_core import config
from agent_core.llm_client import llm_chat
from agent_core.knowledge import (style_summary, style_profile, diff_for_contact, contact_info,
                       frag_text, load_examples, facts)
from agent_core.memory.retrieval import retrieve
from agent_core.memory import human_feedback  # 人工介入闭环: 注入本人纠正记忆 + [[?]] 低确定性协议

OWNER_WXID = 'wxid_o6trqgu7jt1p22'
PROMPT_VER = 'v3'

_GUIDE = """像平时发微信一样回复对方这条消息:
{dist}
- 默认回复不超过 15 个字; 对方的话可以用一两个字接住时, 就只用一两个字
- 「哈哈」和表情是稀有品(你的真实记录里带笑 {laugh}%、带表情 {emo}% —— 约每 25 条才出现 1 次), 只有对方明显在逗乐开玩笑时才用, 否则不用
- 口头禅自然带出即可, 绝不堆砌; 范例里怎么聊, 你就怎么聊
- 「真实过往」里的事就是你亲身经历的, 用你们当时的说法自然接住; 记录里有具体的人名/事件就优先引用
- 大概率能猜到就直接答: 像真人一样按上下文最可能的理解自然接话(食堂/排队/开会这类场景, 猜最普通的那个意思就对了), 猜错也没关系 —— 真人聊天本来就会误会
- [[?]] 是最后手段: 仅当你完全不知道对方在说什么、且猜错代价高(涉及钱/时间承诺/重要事实), 上下文和「真实历史记录」都推不出来时才用 —— 此时第一行原样输出 [[?]], 另起行给 2-3 个你猜的可能回复(每行格式「候选1: …」, 像你平时说话), 系统会请本人亲自确认; 日常闲聊绝不输出 [[?]]
- 你就是本人, 永远不承认或暗示自己是 AI / 助手 / 机器人
- 只输出回复内容本身, 不要解释、引号或前缀
- 整条回复写成一行, 中间不要换行; 想接好几句话就用空格自然连着说"""


def _dist_line():
    s = style_profile()
    d = s.get('长度分布', {})
    if not d:
        return '- 像真实微信聊天那样简短'
    return (f"- 你的真实长度分布: ≤5字 {d.get('≤5字', '?')}%, 6-15字 {d.get('6-15字', '?')}%, "
            f"16-30字 {d.get('16-30字', '?')}%, 超过30字仅 {d.get('>30字', '?')}% —— "
            f"照这个分布说话, 大约每 3 条回复就有 1 条在 5 字以内")


def reply(contact, history, message, progress=None):
    def _p(s):
        if progress:
            try:
                progress(s)
            except Exception:
                pass
    _p(f'正在翻阅你和「{contact}」的历史对话范例…')
    info = contact_info(contact) or {}
    circle = info.get('圈层猜测', '朋友/其他')
    n_total = info.get('总消息', 0)

    frags, ex_level, ex_from = load_examples(contact, message=message, limit=6)
    ex_text = '\n\n'.join(frag_text(f) for f in frags)
    _p(f'已找到 {len(frags)} 组相关对话范例（来自{ex_from}）')

    try:
        from agent_core.memory import indexer as _ix
        n_corpus = len(_ix.mem_index())
    except Exception:
        n_corpus = 0
    _p(f'正在从 {n_corpus} 条历史消息中检索相关记忆…')
    rels = retrieve(message, contact=contact, top_k=config.RETRIEVE_TOP_K)
    _p(f'检索完成：命中 {len(rels)} 条相关记录')
    mem_text = '\n'.join(
        f"[{m['t'][:16]}|与「{m['ct']}」] {'我' if m['s'] == '我' else m['s']}: {m['c'][:60]}"
        for m in rels)

    f_ = facts()
    topics = ', '.join((f_.get('话题高频词_top40') or [])[:20])
    diff = diff_for_contact(contact)

    ex_note = {
        '本人': f'(就是你和「{contact}」聊过的真实片段)',
        '同圈层': f'(没有你和「{contact}」的存档范例, 以下是你与同类关系「{ex_from}」的真实片段, 语气应一致)',
        '全局': '(没有针对性存档范例, 以下是你日常聊天的真实片段)',
        '无': '',
    }.get(ex_level, '')

    sections = [
        f"""你就是账号「{OWNER_WXID}」的主人本人, 正在用微信和联系人「{contact}」聊天。
「{contact}」: {circle}关系, 你们历史上共聊过约 {n_total} 条消息。你现在收到对方一条新消息, 要回复。""",
        f"【你本人的说话风格(来自你全部真实聊天的统计)】\n{style_summary()}",
    ]
    if diff:
        sections.append(f"【你对「{contact}」的说话方式(统计)】\n{diff}")
    if topics:
        sections.append(f"【你平时聊什么(真实话题高频词, 都是你熟悉的)】\n{topics}")
    if mem_text:
        sections.append(f"""【与这条消息相关的你的真实历史记录(优先看与「{contact}」的)】
{mem_text}""")
    if ex_text:
        sections.append(f"【你和联系人聊天的真实范例{ex_note}】\n{ex_text}")
    fb = human_feedback.context_note(message, contact=contact)
    if fb:
        sections.append(fb)
    try:
        from agent_core.memory import experience
        exs = experience.recent_for(contact, limit=5)
        if exs:
            lines = [f"· [{x.get('时间', '')[5:16]}] 对方: {x.get('对方消息', '')[:80]} / 你: {x.get('分身回复', '')[:80]}"
                     for x in exs]
            sections.append('【你最近在网上和 ta 聊过的内容(这些对话也真实发生过, 话题自然衔接时可参考)】\n'
                            + '\n'.join(lines))
    except Exception:
        pass
    if contact.startswith('陌生·'):
        sections.append(
            f"【对方是完全陌生的人】你与「{contact[3:]}」从未有过任何交集，这是 ta 第一次联系你。"
            "保持你一贯的说话风格（短句、口语、真实），但注意：对陌生人保持基本的警惕与距离感，不交浅言深，"
            "回答基于你自己的性格、经历和说话习惯；不要主动提及任何真实朋友的姓名，"
            "也不要泄露你和别人的私聊内容。")
    try:
        from agent_core.simulation.engine import sim_note_for
        sim = sim_note_for(contact)
        if sim:
            sections.append(f"【虚拟推演经历(仅当对方话题自然延续到这里才可参考, 绝不主动提起, 不得声称真实发生过)】\n{sim}")
    except Exception:
        pass
    sections.append(_GUIDE.format(dist=_dist_line(),
                                  laugh=style_profile().get('带笑_比例%', '?'),
                                  emo=style_profile().get('带微信表情_比例%', '?')))
    sys = '\n\n'.join(sections)

    msgs = [{'role': 'system', 'content': sys}]
    for h in (history or [])[-config.HISTORY_WINDOW:]:
        if not isinstance(h, dict) or not h.get('content'):
            continue
        role = 'assistant' if h.get('speaker') == '我' else 'user'
        msgs.append({'role': role, 'content': h['content']})
    # 兼容旧前端: 历史末尾若已包含当前消息则去掉, 防止同一句传两次
    if len(msgs) > 1 and msgs[-1]['role'] == 'user' and msgs[-1]['content'].strip() == message.strip():
        msgs.pop()
    msgs.append({'role': 'user', 'content': message})
    _p(f'资料就绪（{len(frags)} 组范例 + {len(rels)} 条记忆），正在以你的口吻组织回复…（复杂问题可能需要 1-2 分钟）')
    return llm_chat(msgs, temperature=0.85)
