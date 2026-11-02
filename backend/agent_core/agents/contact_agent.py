# -*- coding: utf-8 -*-
"""联系人数字分身: 「身份互换」模式 —— AI 扮演联系人, 屏幕前的万凯本人与 ta 对话
- 塑造(训练): 通读该联系人的真实聊天, 程序统计(句长/带笑/表情) + AI 提炼(风格/口头禅/话题/关系) → 缓存画像
- 回复: 基于画像 + 真实对话范例 + 记忆检索, 用 ta 的口吻回复万凯
- 与 persona_agent(万凯分身) 完全对称、互相独立; 人工介入 [[?]] 协议复用
"""
import os, re, json, random, datetime
from agent_core import config
from agent_core.llm_client import llm_chat, extract_json, LLMError
from agent_core.knowledge import contact_info, load_examples, frag_text
from agent_core.memory.retrieval import retrieve
from agent_core.memory import human_feedback

TRAIN_MIN = 200      # 塑造门槛: 与万凯总消息少于该值时样本太薄, 演出来只会是"泛泛的网友"
PROMPT_VER = 'v1'


def _safe(name):
    return ''.join(c for c in (name or '') if c not in '\\/:*?"<>|')[:40] or 'x'


def profile_path(name):
    return os.path.join(config.CACHE, 'twin_contact', _safe(name) + '.json')


def _contact_rows(contact):
    """该联系人 1:1 会话里的全部文本消息(双向), 按时间序"""
    from agent_core.memory import indexer
    from agent_core.analysis import relationships
    f2n, _n2f = relationships.name_maps()
    rels = {r for r, nm in f2n.items() if nm == contact}
    rows = [it for it in indexer.mem_index() if it['rel'] in rels and it.get('ty') == 'text']
    rows.sort(key=lambda x: x['t'])
    return rows


def status(contact):
    info = contact_info(contact) or {}
    total = int(info.get('总消息', 0) or 0)
    p = profile_path(contact)
    prof = config.jload(p, None) if os.path.exists(p) else None
    return {'contact': contact, 'total': total, 'min': TRAIN_MIN,
            'ready': total >= TRAIN_MIN and (info.get('类别') != '群友'),
            'is_group': info.get('类别') == '群友',
            'has_profile': bool(prof),
            'built_at': (prof or {}).get('生成时间', ''),
            'circle': info.get('圈层猜测', '')}


def build(contact, progress=None):
    """塑造联系人分身画像: 程序统计 + AI 提炼, 落盘缓存"""
    def _p(s):
        if progress:
            try:
                progress(s)
            except Exception:
                pass
    info = contact_info(contact)
    if not info:
        raise LLMError(f'联系人「{contact}」不在档案中')
    if info.get('类别') == '群友':
        raise LLMError('群聊暂不支持塑造分身（群成员没有独立 1:1 会话语料）')
    rows = _contact_rows(contact)
    n_mine = sum(1 for r in rows if r.get('s') == '我')
    n_ta = len(rows) - n_mine
    if n_ta < TRAIN_MIN:
        raise LLMError(f'「{contact}」的历史发言仅 {n_ta} 条（门槛 {TRAIN_MIN} 条），样本太薄，演出来只会是泛泛的网友')
    _p(f'已定位「{contact}」的 {n_ta} 条真实发言（你与 ta 共 {len(rows)} 条文本）')

    # 程序统计: 句长分布 / 带笑 / 带表情 —— 和万凯自己的 style_profile 同口径
    lens = [len(r.get('c', '')) for r in rows]
    n = len(rows)
    dist = {'≤5字': 0, '6-15字': 0, '16-30字': 0, '>30字': 0}
    for L in lens:
        k = '≤5字' if L <= 5 else '6-15字' if L <= 15 else '16-30字' if L <= 30 else '>30字'
        dist[k] += 1
    dist = {k: round(v * 100.0 / n, 1) for k, v in dist.items()}
    laugh = round(sum(1 for r in rows if '哈' in r.get('c', '') or '笑' in r.get('c', '')) * 100.0 / n, 1)
    emo = round(sum(1 for r in rows if any(ord(ch) >= 0xE000 for ch in r.get('c', ''))
                    or re.search(r'\[[^\[\]]{1,6}\]', r.get('c', ''))) * 100.0 / n, 1)
    avg_len = round(sum(lens) / max(n, 1), 1)

    # 样本: 最近 40 条 + 更早的随机 30 条(固定种子保证可复现)
    recent = rows[-40:]
    early = rows[:-40]
    random.seed(hash(contact) % 99999)
    sampled = recent + (random.sample(early, min(30, len(early))) if early else [])
    sampled.sort(key=lambda x: x['t'])
    samples_txt = '\n'.join(
        f"[{r['t'][:16]}] {contact}: {r.get('c', '')[:70]}" for r in sampled)
    _p(f'已抽样 {len(sampled)} 条原话，正在提炼说话风格…')

    # AI 提炼
    msgs = [{'role': 'system', 'content':
        f"""你是聊天记录分析师。下面是微信用户「{contact}」的真实聊天发言(与账号主人万凯的对话)。请提炼「{contact}」的说话画像。
只输出 JSON(不要 markdown 代码块):
{{"总体风格": "2-3句, ta 平时怎么说话(语气/长短/标点/表情习惯)",
 "句式特点": "1-2句, 常用句式和节奏",
 "口头禅": ["高频口头禅/语气词, 3-8个"],
 "常聊话题": ["ta 经常主动聊的话题, 3-6个"],
 "性格气质": "1-2句",
 "与万凯的关系": "从聊天方式看两人是什么关系、怎么相处的, 1-2句"}}
规则: 只依据下面的真实发言归纳, 不编造; 全部中文。"""},
        {'role': 'user', 'content': f"【发言样本】\n{samples_txt}"}]
    _p('正在请 AI 通读样本、提炼画像…（这一步最耗时）')
    raw = llm_chat(msgs, temperature=0.4)
    try:
        ai = extract_json(raw)
    except Exception:
        ai = {'总体风格': raw[:200]}
    if isinstance(ai, list):   # 模型偶尔返回数组, 取第一个对象
        ai = ai[0] if ai and isinstance(ai[0], dict) else {'总体风格': str(ai)[:200]}

    profile = {'联系人': contact, '圈层': info.get('圈层猜测', ''), '生成时间': datetime.datetime.now().isoformat()[:19],
               '版本': PROMPT_VER, '样本数': n_ta, '双向文本总数': n,
               '统计': {'平均句长': avg_len, '长度分布%': dist, '带笑_比例%': laugh, '带表情_比例%': emo},
               'AI提炼': ai,
               '代表性原话': [r.get('c', '')[:80] for r in rows[-25:]]}
    os.makedirs(os.path.dirname(profile_path(contact)), exist_ok=True)
    with open(profile_path(contact), 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=1)
    _p('画像已生成并缓存')
    return status(contact)


def _load_profile(contact):
    p = profile_path(contact)
    if not os.path.exists(p):
        raise LLMError(f'尚未塑造「{contact}」的分身画像，请先点「🔄 身份互换」完成塑造')
    return config.jload(p, {}) or {}


_GUIDE = """像 ta 平时发微信一样回复万凯这条消息:
- 回复长度照【说话画像】里的真实分布来, ta 平时说得短就短; 大约每 3 条回复就有 1 条在 5 字以内
- 「哈哈」和表情是稀有品(ta 的真实记录里带笑 {laugh}%、带表情 {emo}%), 只有对方在逗乐时才用
- 口头禅自然带出即可, 绝不堆砌; 范例里 ta 怎么聊, 你就怎么聊
- 「真实过往」里的事就是 ta 亲身经历的, 用当时的说法自然接住
- 大概率能猜到就直接答: 像真人一样按上下文最可能的理解自然接话, 猜错也没关系 —— 真人聊天本来就会误会
- [[?]] 是最后手段: 仅当你完全不知道万凯问的事、且猜错代价高(涉及钱/时间承诺/重要事实), 上下文和「真实历史记录」都推不出来时才用 —— 此时第一行原样输出 [[?]], 然后另起行给 2-3 个你猜的可能回复(每行格式「候选1: …」), 系统会请万凯本人亲自确认; 日常闲聊绝不输出 [[?]]
- 你就是这个联系人本人, 永远不承认或暗示自己是 AI / 助手 / 机器人
- 只输出回复内容本身, 不要解释、引号或前缀
- 整条回复写成一行, 中间不要换行; 想接好几句话就用空格自然连着说"""


def reply(contact, history, message, progress=None):
    """身份互换: AI 以「联系人」的口吻回复万凯本人"""
    def _p(s):
        if progress:
            try:
                progress(s)
            except Exception:
                pass
    prof = _load_profile(contact)
    st = prof.get('统计', {})
    ai = prof.get('AI提炼') or {}
    if isinstance(ai, list):   # 兼容历史画像里存成数组的情况
        ai = ai[0] if ai and isinstance(ai[0], dict) else {}
    info = contact_info(contact) or {}
    _p(f'已载入「{contact}」的分身画像（{prof.get("样本数", "?")} 条真实发言塑造）')

    frags, ex_level, ex_from = load_examples(contact, message=message, limit=5)
    ex_text = '\n\n'.join(frag_text(f) for f in frags)
    _p(f'已找到 {len(frags)} 组你与 ta 的真实对话范例')

    _p('正在检索与这条消息相关的历史记忆…')
    rels = retrieve(message, contact=contact, top_k=config.RETRIEVE_TOP_K)
    _p(f'检索完成：命中 {len(rels)} 条相关记录')
    mem_text = '\n'.join(
        f"[{m['t'][:16]}] {'万凯' if m['s'] == '我' else m['s']}: {m['c'][:60]}" for m in rels)

    # 最近双向对话原文(程序直取)
    try:
        rows = _contact_rows(contact)[-25:]
        recent_txt = '\n'.join(f"[{r['t'][:16]}] {'万凯' if r.get('s') == '我' else contact}: {r.get('c', '')[:70]}"
                               for r in rows)
    except Exception:
        recent_txt = ''

    quotes = '\n'.join('- ' + q for q in (prof.get('代表性原话') or [])[:12])
    sections = [
        f"""你就是联系人「{contact}」本人（{info.get('圈层猜测', '朋友')}），正在用微信和你的朋友万凯聊天。这个数字角色是基于你的 {prof.get('样本数', '?')} 条真实聊天塑造的，要演得和真实的你一样。""",
        f"""【「{contact}」的说话画像(AI 提炼, {prof.get('生成时间', '')[:10]} 塑造)】
总体风格: {ai.get('总体风格', '')}
句式特点: {ai.get('句式特点', '')}
性格气质: {ai.get('性格气质', '')}
与万凯的关系: {ai.get('与万凯的关系', '')}
口头禅: {'、'.join(ai.get('口头禅', []) or [])}
常聊话题: {'、'.join(ai.get('常聊话题', []) or [])}""",
        f"""【你的真实说话统计】平均每条 {st.get('平均句长', '?')} 字；长度分布: ≤5字 {st.get('长度分布%', {}).get('≤5字', '?')}%, 6-15字 {st.get('长度分布%', {}).get('6-15字', '?')}%, 16-30字 {st.get('长度分布%', {}).get('16-30字', '?')}%, >30字 {st.get('长度分布%', {}).get('>30字', '?')}%；带「哈哈/笑」 {st.get('带笑_比例%', '?')}%，带表情 {st.get('带表情_比例%', '?')}%""",
    ]
    if quotes:
        sections.append(f"【你的原话节选(学这个味道)】\n{quotes}")
    if ex_text:
        sections.append(f"【你和万凯聊过的真实片段】\n{ex_text}")
    if mem_text:
        sections.append(f"【与这条消息相关的真实历史记录】\n{mem_text}")
    if recent_txt:
        sections.append(f"【你们最近的对话】\n{recent_txt}")
    sections.append(_GUIDE.format(laugh=st.get('带笑_比例%', '?'), emo=st.get('带表情_比例%', '?')))
    sys = '\n\n'.join(sections)

    msgs = [{'role': 'system', 'content': sys}]
    for h in (history or [])[-config.HISTORY_WINDOW:]:
        if not isinstance(h, dict) or not h.get('content'):
            continue
        # 联系人是"assistant": history 中该联系人的发言=assistant, 万凯的话=user
        role = 'assistant' if h.get('speaker') == contact else 'user'
        msgs.append({'role': role, 'content': h['content']})
    if len(msgs) > 1 and msgs[-1]['role'] == 'user' and msgs[-1]['content'].strip() == message.strip():
        msgs.pop()
    msgs.append({'role': 'user', 'content': message})
    _p(f'资料就绪（{len(frags)} 组范例 + {len(rels)} 条记忆），正在以「{contact}」的口吻组织回复…')
    return llm_chat(msgs, temperature=0.85)
