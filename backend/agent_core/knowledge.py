# -*- coding: utf-8 -*-
"""Agent知识库 读取层: 风格档案 / 事实记忆 / 联系人关系 / 对话范例(分层回退)"""
import os, re, json, random
from agent_core import config
def style_profile():
    return config.jload(os.path.join(config.KB, '我的风格档案.json'), {})


def facts():
    return config.jload(os.path.join(config.KB, '我的事实记忆.json'), {})


def contacts():
    base = config.jload(os.path.join(config.KB, '联系人关系档案.json'), [])
    gf = group_friends()
    if not gf:
        return base
    names = {c.get('姓名') for c in base}
    return base + [g for g in gf if g.get('姓名') not in names]


def group_friends():
    """提炼的群友联系人(独立文件, 重建知识库不会丢失)"""
    return config.jload(os.path.join(config.KB, '群友名单.json'), [])


def save_group_friends(lst):
    with open(os.path.join(config.KB, '群友名单.json'), 'w', encoding='utf-8') as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)


def contact_info(name):
    for c in contacts():
        if c.get('姓名') == name:
            return c
    return None


def circle_of(name):
    info = contact_info(name)
    return info.get('圈层猜测', '') if info else ''


def safe_fn(s):
    return re.sub(r'[\\/:*?"<>|]+', '_', s)[:40]


def style_summary():
    """风格档案 → 给 prompt 用的精简文本"""
    s = style_profile()
    if not s:
        return '(无风格数据)'
    lines = [f"- 平均每条消息 {s['平均长度_字']} 字(中位 {s['中位长度_字']}), "
             f"≤5字占 {s['长度分布']['≤5字']}%, >30字仅 {s['长度分布']['>30字']}% —— 说话简短"]
    lines.append(f"- 每千条: 感叹号{s['标点频率_每千条']['感叹号']} 问号{s['标点频率_每千条']['问号']} "
                 f"省略号{s['标点频率_每千条']['省略号']} 波浪号{s['标点频率_每千条']['波浪号']}")
    lines.append(f"- 带笑(哈哈类)比例 {s['带笑_比例%']}%, 带微信表情比例 {s['带微信表情_比例%']}%")
    kc = [x['句'] for x in s['口头禅_高频完整短句_top30'][:15]]
    lines.append(f"- 高频口头禅: {', '.join(kc)}")
    wz = [x['词'] for x in s['高频词组_top50'][:20]]
    lines.append(f"- 高频词: {', '.join(wz)}")
    hours = s.get('活跃时段_按小时', {})
    if hours:
        top_h = sorted(hours.items(), key=lambda x: -x[1])[:5]
        lines.append(f"- 常活跃时段: {', '.join(h for h, _ in top_h)}")
    return '\n'.join(lines)


def diff_for_contact(name):
    """我对某联系人的专属说话差异(来自风格档案统计), 没有则空串"""
    s = style_profile()
    v = (s.get('分对象说话差异_top15') or {}).get(name)
    if not v:
        return ''
    return (f"平均每条 {v['平均长度']} 字; 对TA常说的开头: "
            + ', '.join(v['对该联系人高频短句_top8'][:6]))


def diff_by_contact():
    s = style_profile()
    d = s.get('分对象说话差异_top15', {})
    out = []
    for name, v in list(d.items())[:10]:
        out.append(f"· 对「{name}」: 平均{v['平均长度']}字, 常说 {', '.join(v['对该联系人高频短句_top8'][:5])}")
    return '\n'.join(out)


def frag_text(f):
    return f"[{f.get('contact', '')} {f.get('time', '')[:10]}]\n" + '\n'.join(
        f"{'我' if m.get('speaker') == '我' else m.get('speaker', '')}: {m.get('content', '')}"
        for m in f.get('messages', []))


# ────────────────────────── 对话范例(分层回退, 拒绝跨圈层乱抓) ──────────────────────────
_PUNCT = re.compile(r'[，。！？,.!?~…\s（）()【】\[\]]')
_ex_cache = {}   # contact -> (mtime, frags)


def _bigrams(t):
    s = _PUNCT.sub('', t or '')
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _examples_of(contact):
    p = os.path.join(config.KB, '对话范例库', safe_fn(contact) + '.jsonl')
    if not os.path.exists(p):
        return []
    try:
        mt = os.stat(p).st_mtime
    except OSError:
        return []
    hit = _ex_cache.get(contact)
    if hit and hit[0] == mt:
        return hit[1]
    frags = []
    try:
        with open(p, encoding='utf-8') as f:
            frags = [json.loads(l, strict=False) for l in f if l.strip()]
    except Exception:
        frags = []
    _ex_cache[contact] = (mt, frags)
    return frags


def _pick(frags, message, limit):
    """有消息时按 2-gram 重叠挑最贴近当前场景的片段; 没有则随机"""
    if message:
        gs = _bigrams(message)
        frags = sorted(frags, key=lambda f: -len(gs & _bigrams(frag_text(f))))
    else:
        frags = list(frags)
        random.shuffle(frags)
    return frags[:limit]


def load_examples(contact, message='', limit=6):
    """分层回退:
    1. 本联系人的真实范例 (按当前消息场景挑最相关的)
    2. 同圈层联系人的范例 (语气最接近的人群)
    3. 最活跃联系人的通用范例 (仅保底语感)
    返回 (frags, level, 来自); level∈{本人,同圈层,全局,无} — 没有合适范例就返回空, 宁少勿错
    """
    frags = _examples_of(contact)
    if frags:
        return _pick(frags, message, limit), '本人', contact
    circle = circle_of(contact)
    if circle:
        pool = []
        same = [c['姓名'] for c in contacts()
                if c.get('圈层猜测') == circle and c.get('姓名') != contact and _examples_of(c['姓名'])]
        same.sort(key=lambda n: -(contact_info(n) or {}).get('总消息', 0))
        for n in same[:5]:
            pool.extend(_examples_of(n)[:12])
        if pool:
            return _pick(pool, message, limit), '同圈层', circle
    top = [c['姓名'] for c in contacts() if _examples_of(c['姓名'])]
    top.sort(key=lambda n: -(contact_info(n) or {}).get('总消息', 0))
    pool = []
    for n in top[:5]:
        pool.extend(_examples_of(n)[:12])
    if pool:
        return _pick(pool, message, limit), '全局', '全局'
    return [], '无', ''


def load_contact_profile(name):
    """联系人 AI 画像缓存(裸结果, 兼容新旧格式), 没有则 None"""
    from agent_core.cache_store import load as cs_load
    r, _ = cs_load(os.path.join(config.CACHE, f'contact_{safe_fn(name)}.json'))
    return r
