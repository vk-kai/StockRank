# -*- coding: utf-8 -*-
"""技能与经历提炼: 把四年的真实聊天 + 本人手动日程大事, 提炼为
「我会的技能(分类)」和「这几年做的事(按年份, 详细)」
数据源优先级: 指尖时光日程(手动记录, 最可信) > 话题高频词 > 发言样本 > AI 画像"""
import os
from agent_core import config
from agent_core.llm_client import llm_chat, extract_json
from agent_core.knowledge import facts, style_profile, diff_by_contact
from agent_core import cache_store
PROMPT_VER = 'v1'


def _load_cached(fn):
    try:
        r, _ = cache_store.load(os.path.join(config.CACHE, fn))
        return r or {}
    except Exception:
        return {}


def generate_skills():
    s = style_profile()
    f = facts()
    samples = list(f.get('代表性发言样本_50条') or [])
    topics = list(f.get('话题高频词_top40') or [])
    try:
        from agent_core.analysis import daily_log
        daily = daily_log.digest()
    except Exception:
        daily = ''
    me = _load_cached('profile_me.json')
    tl = _load_cached('timeline.json')
    tl_years = (tl.get('年份') if isinstance(tl, dict) else None) or []

    sys = """你是资深的职业规划师兼人生梳理师。根据一个人四年的真实聊天统计数据、代表性发言、本人手动记录的日程大事和已有的人生时间线, 输出:
1)「技能」: 他会什么, 分类整理(如: 技术开发/金融投资/思维方法/生活技能/软技能), 每条技能后面用括号注明依据来源(日程记录/聊天话题/发言风格); 只写有依据的, 没把握的绝不编造
2)「这几年」: 2022-2026 按年份整理, 每年 3-8 件具体的事 —— 学了什么、做了什么项目/尝试、坚持了什么、生活重要节点; 描述要具体详细(做什么、为什么做、结果怎样), 依据日程大事与聊天证据, 不许编造日程里没有的大事
3)「一句话」: 30 字内概括这个人最突出的能力组合
只输出 JSON(不要 markdown 代码块):
{"技能": [{"类别": "", "技能": ["技能名（依据）"]}],
 "这几年": [{"年份": "2023", "主题": "", "事情": ["详细描述...", "..."]}],
 "一句话": ""}"""
    import json as _j
    stats = {k: v for k, v in s.items() if k != '分对象说话差异_top15'}
    user = f"""【风格统计】
{_j.dumps(stats, ensure_ascii=False)[:2500]}

【对不同人的差异】
{diff_by_contact()}

【话题高频词】
{', '.join(topics[:40])}

【代表性发言样本】
{chr(10).join(samples[:50])}"""
    if me:
        user += f"""

【已有 AI 画像(性格/兴趣, 供参考交叉印证)】
兴趣与生活: {'; '.join(me.get('兴趣与生活') or [])}
性格特点: {'; '.join((me.get('性格特点') or [])[:4])}"""
    if tl_years:
        import json as _j2
        user += f"""

【已有人生时间线(事件标题摘要, 供参考)】
{_j2.dumps([{'年': y.get('年'), '主题': y.get('主题'), '事件': [e.get('标题') for e in (y.get('事件') or [])[:8]]} for y in tl_years], ensure_ascii=False)[:2500]}"""
    if daily:
        user += f"""

【指尖时光日程记录(本人每天手动记录的真实事项, 按月聚合 —— 最可信的技能与经历来源)】
{daily}"""

    out = extract_json(llm_chat([{'role': 'system', 'content': sys},
                                 {'role': 'user', 'content': user}], temperature=0.3))
    fps = [cache_store.file_fp(os.path.join(config.KB, '我的风格档案.json')),
           cache_store.file_fp(os.path.join(config.KB, '我的事实记忆.json'))]
    try:
        fps.append(cache_store.file_fp(os.path.join(config.KB, '日常记录.json')))
    except Exception:
        pass
    cache_store.save(os.path.join(config.CACHE, 'profile_skills.json'), out,
                     cache_store.fingerprint(PROMPT_VER, *fps))
    return out
