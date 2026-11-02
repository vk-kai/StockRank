# -*- coding: utf-8 -*-
"""沙盘推演: 「强化版分身」—— 比万凯本人更聪明、且非常了解万凯的参谋
综合: 个人画像(性格/说话方式) + 技能清单 + 人生时间线 + 真实聊天检索 + 人工纠正记忆
场景: 拿捏不定的事 / 想预测某件事 → 输出「以你的人设会怎么做 → 各方案推演 → 明确建议」
与知己的区别: 知己引用原话回答"你是什么样的人", 沙盘推演用你的全部人设推演"接下来该怎么做"""
import os
from agent_core import config
from agent_core.llm_client import llm_chat, extract_json, LLMError
from agent_core.knowledge import facts, style_summary
from agent_core.memory.retrieval import retrieve
from agent_core.memory import human_feedback

PROMPT_VER = 'v1'

_SYS = """你是万凯的「强化版数字分身」—— 底色是他本人, 但比他更冷静、更有谋略、更懂人性: 你完全了解他的性格、技能、这些年的经历、行为模式和致命弱点。用户遇到拿捏不定的事或想预测某件事时, 你做三件事:
1.【还原】以他的人设, 他大概率会怎么做(基于他的真实行为模式, 不是理想化的他)
2.【推演】把他可选的每条路都走一遍: 短期会怎样、长期会怎样、有什么风险, 用他的性格和技能去推, 结论要贴合他这个人
3.【给招】作为比他聪明的自己, 给出明确倾向和理由 —— 该补他的短板就直说(如: 按你的性格你会把话憋着/你会先讲道理, 这次试试先…), 但不否定他这个人
要求: 全部中文, 说人话不空泛; 判断必须挂在他真实的人设和经历上(下面会给出证据); 涉及风险直言不讳, 但最后给人可行的一步; 不许打官腔、不许"建议咨询专业人士"式套话。
只输出 JSON(不要 markdown 代码块):
{"本质": "这件事真正的问题是什么, 一句话戳破",
 "默认走向": "以万凯的人设/习惯, 他不加干预大概率会怎么做、结局如何, 2-3句",
 "推演": [{"方案": "可选方案(含'什么都不做')", "短期": "", "长期": "", "风险": ""}],
 "建议": "强化版分身的明确建议: 选哪条路、第一步做什么、要避开他哪个惯性",
 "依据": ["支撑判断的真实经历/性格证据, 2-4条, 具体到事"],}"""


def _load_cached(fn):
    try:
        from agent_core import cache_store
        r, _ = cache_store.load(os.path.join(config.CACHE, fn))
        return r or {}
    except Exception:
        return {}


def _context(issue):
    secs = []
    me = _load_cached('profile_me.json')
    if me:
        secs.append(f"""【万凯的画像】
性格特点: {'; '.join((me.get('性格特点') or [])[:6])}
说话方式: {me.get('说话方式', {}).get('整体风格', '') if isinstance(me.get('说话方式'), dict) else ''}
兴趣与生活: {'; '.join((me.get('兴趣与生活') or [])[:8])}
社交风格: {me.get('社交风格', '')}
注意点(他的短板): {me.get('注意点', '')}""")
    sk = _load_cached('profile_skills.json')
    if sk:
        lines = [f"· {c.get('类别', '')}: {', '.join((c.get('技能') or [])[:8])}" for c in (sk.get('技能') or [])]
        if lines:
            secs.append('【万凯会的技能】\n' + '\n'.join(lines))
        if sk.get('一句话'):
            secs.append('【一句话人设】' + sk['一句话'])
    try:
        tl = _load_cached('timeline.json')
        yrs = (tl.get('年份') or []) if isinstance(tl, dict) else []
        ev_lines = []
        for y in yrs[-4:]:
            for e in (y.get('事件') or [])[:6]:
                ev_lines.append(f"· {y.get('年', '')} {e.get('标题', '')}: {(e.get('描述') or '')[:60]}")
        if ev_lines:
            secs.append('【这些年的关键经历】\n' + '\n'.join(ev_lines[-24:]))
    except Exception:
        pass
    try:
        rels = retrieve(issue, contact=None, top_k=10)
        if rels:
            mem = '\n'.join(f"[{m['t'][:16]}|与「{m['ct']}」] {'我' if m['s'] == '我' else m['s']}: {m['c'][:60]}"
                            for m in rels)
            secs.append('【与这件事相关的万凯真实聊天记录】\n' + mem)
    except Exception:
        pass
    fb = human_feedback.context_note(issue)
    if fb:
        secs.append(fb)
    secs.append('【万凯的说话风格】\n' + style_summary()[:400])
    f_ = facts()
    topics = ', '.join((f_.get('话题高频词_top40') or [])[:25])
    if topics:
        secs.append('【万凯平时聊什么】\n' + topics)
    return '\n\n'.join(secs)


def run(issue, options='', history=None):
    """issue=拿不定的事/想预测的事; options=可选方案(可选); history=[{q,a}] 追问上下文"""
    issue = (issue or '').strip()
    if not issue:
        raise ValueError('先把事情说清楚')
    ctx = _context(issue)
    user = f"""【万凯拿不定的事 / 想预测的事】
{issue[:1500]}"""
    if options:
        user += f"\n\n【他在考虑的方案】{str(options)[:600]}"
    if history:
        prev, last = history[:-1], history[-1]
        lines = []
        for h in prev:
            if isinstance(h, dict) and h.get('q'):
                lines.append(f"追问: {str(h.get('q'))[:200]}\n你的结论(摘要): {str(h.get('a'))[:400]}")
        if lines:
            user += '\n\n【本次沙盘的前几轮(供延续, 不要重复结论)】\n' + '\n---\n'.join(lines)
        user += f"\n\n【本次要回答的追问】{str(last.get('q'))[:300]}\n请基于前面的沙盘结论回答这个追问(同样按 JSON 结构输出, 没有的字段给空)。"
    user = f"【万凯的真实档案(判断必须基于这些)】\n{ctx}\n\n{'-'*20}\n{user}"
    try:
        out = llm_chat([{'role': 'system', 'content': _SYS},
                        {'role': 'user', 'content': user}], temperature=0.5)
        r = extract_json(out)
    except LLMError:
        raise
    except Exception:
        r = {}
    if not r or not (r.get('本质') or r.get('建议') or r.get('默认走向')):
        raise LLMError('沙盘推演生成失败，请重试')
    return {'essence': r.get('本质', ''),
            'default': r.get('默认走向', ''),
            'paths': [{'plan': p.get('方案', ''), 'short': p.get('短期', ''),
                       'long': p.get('长期', ''), 'risk': p.get('风险', '')}
                      for p in (r.get('推演') or []) if isinstance(p, dict)],
            'advice': r.get('建议', ''),
            'evidence': r.get('依据') or []}
