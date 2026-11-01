# -*- coding: utf-8 -*-
"""AI 画像: 个人画像 + 联系人画像
联系人画像采用分层抽样(早/中/近期 + 高频话题 + 对方主动开启 + 密集互动),
取代原随机抽样 —— 覆盖更全面、多次生成结果更稳定, 且严格区分双方发言。"""
import os, json, datetime
from agent_core import config
from agent_core.llm_client import llm_chat, extract_json
from agent_core.knowledge import style_profile, facts, diff_by_contact, contact_info, safe_fn
from agent_core import cache_store
PROMPT_VER = 'v3'   # v3: 融入指尖时光日程数据源


def generate_me():
    s = style_profile()
    samples = [x for x in facts().get('代表性发言样本_50条', [])]
    try:
        from agent_core.analysis import daily_log
        daily = daily_log.digest()
    except Exception:
        daily = ''
    sys = """你是资深人物分析师。根据一个人微信聊天的量化风格数据、真实发言样本和本人手动记录的日程大事, 输出详细的个人画像。
只输出 JSON(不要 markdown 代码块):
{"一句话总结":"", "性格特点":["3-6条,每条有依据"], "说话方式":{"整体风格":"", "句式特点":"", "口头禅":"", "标点与表情":""},
"社交风格":"对不同人的态度差异", "兴趣与生活":["从话题和日程推断, 可含学过的技能、坚持的事、生活规律"], "活跃规律":"", "优点":"", "注意点":"给本人的小建议"}
全部用中文, 内容具体、有数据支撑, 不要空话。
日程记录是本人每天手动记的真实事项(比聊天推断更可信): 学过什么(如缠论/经济学/安全开发)、坚持做什么(复盘/健身/写行业笔记)、生活节奏(作息/出行/家务)都以它为准, 融入「兴趣与生活」和「活跃规律」。"""
    user = f"""【风格统计】
{json.dumps({k: v for k, v in s.items() if k != '分对象说话差异_top15'}, ensure_ascii=False)[:3500]}

【对不同人的差异】
{diff_by_contact()}

【真实发言样本】
{chr(10).join(samples[:50])}"""
    if daily:
        user += f"""

【指尖时光日程记录(本人手动记录的每日大事, 按月聚合)】
{daily}"""
    out = extract_json(llm_chat([{'role': 'system', 'content': sys},
                                 {'role': 'user', 'content': user}], temperature=0.4))
    fps = [cache_store.file_fp(os.path.join(config.KB, '我的风格档案.json')),
           cache_store.file_fp(os.path.join(config.KB, '我的事实记忆.json'))]
    try:
        fps.append(cache_store.file_fp(os.path.join(config.KB, '日常记录.json')))
    except Exception:
        pass
    cache_store.save(
        os.path.join(config.CACHE, 'profile_me.json'), out,
        cache_store.fingerprint(PROMPT_VER, *fps))
    return out


# ────────────────────────── 联系人画像(分层抽样) ──────────────────────────
def _stratified_sample(lines, cap=80):
    """分层抽样: [(标签, msg)] 按时间排序, 标签解释每条为什么被选中"""
    msgs = [m for m in lines
            if m.get('type', 'text') == 'text' and len(str(m.get('content', '')).strip()) >= 2]
    if not msgs:
        return []
    msgs.sort(key=lambda m: m.get('time', ''))
    n = len(msgs)
    picks, seen = [], set()

    def add(tag, m):
        key = (m.get('time'), str(m.get('content', ''))[:30])
        if key in seen:
            return
        seen.add(key)
        picks.append((tag, m))

    # 1) 早 / 中 / 近期: 均匀系统取样(而非随机), 近期权重更高
    third = max(1, n // 3)
    for tag, seg in (('早期', msgs[:third]), ('中期', msgs[third:2 * third]),
                     ('近期', msgs[2 * third:])):
        if not seg:
            continue
        k = 14 if tag == '近期' else 8
        step = max(1, len(seg) // k)
        for m in seg[::step][:k]:
            add(tag, m)

    # 2) 高频话题命中(两人都算, 但保留说话人标记)
    for w in (facts().get('话题高频词_top40') or [])[:8]:
        hits = [m for m in msgs if w in str(m.get('content', ''))]
        if hits:
            add('高频话题', hits[len(hits) // 2])

    # 3) 对方主动开启的对话(距上一条 > 6 小时且开口的是对方)
    prev_t, openers = None, []
    for m in msgs:
        try:
            cur = datetime.datetime.strptime(m.get('time', '')[:19], '%Y-%m-%d %H:%M:%S')
        except Exception:
            prev_t = None
            continue
        if prev_t is not None and (cur - prev_t).total_seconds() > 6 * 3600 \
                and m.get('speaker') != '我':
            openers.append(m)
        prev_t = cur
    if openers:
        step = max(1, len(openers) // 8)
        for m in openers[::step][:8]:
            add('对方主动开启', m)

    # 4) 密集互动窗口(10 分钟桶内消息最多的 3 段)
    buckets = {}
    for i, m in enumerate(msgs):
        key = m.get('time', '')[:15]   # 精确到 10 分钟
        buckets.setdefault(key, []).append(i)
    for key in sorted(buckets, key=lambda k: -len(buckets[k]))[:3]:
        for i in buckets[key][:5]:
            add('密集互动', msgs[i])

    picks.sort(key=lambda x: x[1].get('time', ''))
    return picks[:cap]


def _find_source(name):
    for kind in ('私聊', '群聊'):
        p = os.path.join(config.DATA, kind)
        fn = f"{safe_fn(name)}_"
        if os.path.isdir(p):
            for f2 in os.listdir(p):
                if f2.startswith(fn) and f2.endswith('.jsonl'):
                    return os.path.join(p, f2)
    return None


def _group_member_lines(name):
    """群友(无私聊): 从其发言过的所有群聊文件汇总本人文本消息(附群名)"""
    out = []
    gdir = os.path.join(config.DATA, '群聊')
    if not os.path.isdir(gdir):
        return out
    for fn in os.listdir(gdir):
        if not fn.endswith('.jsonl'):
            continue
        gname = fn[:-len('.jsonl')]
        p = os.path.join(gdir, fn)
        try:
            with open(p, encoding='utf-8') as f:
                for l in f:
                    if not l.strip():
                        continue
                    try:
                        m = json.loads(l, strict=False)
                    except Exception:
                        continue
                    if m.get('speaker') == name and (m.get('type') or 'text') == 'text':
                        m['group'] = gname
                        out.append(m)
        except Exception:
            continue
    out.sort(key=lambda m: m.get('time', ''))
    return out


def generate_contact(name, progress=None):
    def _p(s):
        if progress:
            try:
                progress(s)
            except Exception:
                pass
    info = contact_info(name)
    if not info:
        from agent_core.llm_client import LLMError
        raise LLMError(f'联系人「{name}」不存在')
    _p(f'正在定位与「{name}」的原始聊天文件…（档案统计共 {info.get("总消息", 0)} 条消息）')
    src = _find_source(name)
    lines = []
    is_groupfriend = (info.get('类别') == '群友') or (not src and info.get('主群'))
    if src:
        with open(src, encoding='utf-8') as f:
            lines = [json.loads(l, strict=False) for l in f if l.strip()]
        _p(f'文件读取完成：共载入 {len(lines)} 条原始记录')
    elif is_groupfriend:
        lines = _group_member_lines(name)
        ng = len({m.get('group') for m in lines})
        _p(f'「{name}」是群友（无 1:1 私聊），已从 {ng} 个群聊文件汇总其 {len(lines)} 条发言')
    else:
        _p('未找到本地原始聊天文件，将仅用统计档案生成')
    sample = _stratified_sample(lines)
    n_text = sum(1 for m in lines if m.get('type', 'text') == 'text' and len(str(m.get('content', '')).strip()) >= 2)
    _p(f'分层抽样完成：{n_text} 条文本消息中抽出 {len(sample)} 条代表样本'
       '（早期/中期/近期均匀取样 + 高频话题 + 对方主动开启 + 密集互动）')
    _p(f'AI 正在通读 {len(sample)} 条抽样对话并分析性格…（约需 1-2 分钟）')
    if is_groupfriend:
        dial = '\n'.join(f"[{tag}|{m['time'][5:16]}|群:{m.get('group', '')[:12]}] {m['speaker']}: {m['content']}"
                         for tag, m in sample)
    else:
        dial = '\n'.join(f"[{tag}|{m['time'][5:16]}] {m['speaker']}: {m['content']}"
                         for tag, m in sample)
    sys = """你是资深人物分析师。根据"我"(万凯)和某联系人的真实微信对话样本, 分析这个联系人是什么样的人。
样本每行开头中括号是抽样标签(早期/中期/近期/高频话题/对方主动开启/密集互动), 说明该句为何入选。
只输出 JSON(不要 markdown 代码块):
{"身份推测":"", "性格特点":["3-6条"], "说话方式":"", "与我的关系":"", "聊天氛围":"", "典型对话":[{"谁":"", "说了":""}],"备注":""}
全部中文, 具体、有对话依据, 不要空话。
注意区分「我」和对方的话 —— 不要把双方的表达混成一个人的性格。"""
    user = f"""联系人: {name}{('（群友：无 1:1 私聊，样本是该联系人各群里的公开发言，行尾「群:xx」标注发言所在群）') if is_groupfriend else ''}
统计: 总消息{info.get('总消息', 0)}条, 对方发{info.get('对方发言', 0)}条, 我发{info.get('我的发言', 0)}条, 圈层{info.get('圈层猜测', '')}, 时间跨度 {info.get('首次', '')[:10]} 至 {info.get('末次', '')[:10]}{(', 主要活跃群: ' + info.get('主群', '')) if info.get('主群') else ''}

【分层对话样本(按时间排序)】
{dial if dial else '(无文本对话)'}"""
    out = None
    for i, temp in enumerate((0.4, 0.3)):   # AI 偶发输出非法 JSON → 自动重试一次
        try:
            out = extract_json(llm_chat([{'role': 'system', 'content': sys},
                                         {'role': 'user', 'content': user}], temperature=temp))
            break
        except Exception:
            if i:
                raise
            _p('AI 输出格式异常，正在自动重试…')
    cache_store.save(
        os.path.join(config.CACHE, f'contact_{safe_fn(name)}.json'), out,
        cache_store.fingerprint(PROMPT_VER, cache_store.file_fp(src or 'none'), str(len(lines))))
    return out
