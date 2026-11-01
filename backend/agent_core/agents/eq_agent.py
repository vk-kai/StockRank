# -*- coding: utf-8 -*-
"""高情商版分身 (EQ Twin): 万凯人格 + 补足情感表达短板的练习模式
场景1: 用户扮演女生发消息 → 用户发自己本来想回的话 → AI 给出高情商版回复 → 可诊断差异
场景2: 首次主动开场 —— 对方一句话都没说过, 只有基本背景 → 用户写开场草稿 → 高情商版开场白 → 诊断
短板依据(另一 AI 对万凯聊天记录的分析):
1 讲道理抢跑(对方倾诉时先分析问题) 2 玩笑包装一切(态度藏太深)
3 能力展示多生活感少 4 不会推进关系(不敢单独约/不会表达欣赏)
分身底色来自万凯真实聊天记录: 每轮按话题召回真实记忆片段注入, 生活细节/经历都以此为准
每个发展对象独立会话存档 cache/eq_chats/, 与分身主对话完全隔离"""
import os, re, json
from agent_core.llm_client import llm_chat, extract_json, LLMError
from agent_core.memory.retrieval import retrieve
from agent_core import config
_SYS_EQ = """你是「高情商版的万凯」。底色是万凯本人: 26 岁、西安程序员、理性幽默、真诚不油腻、熟悉后爱开玩笑、有点理工直男但靠得住。但你在情感表达上比万凯本人高一个段位 —— 你已经修正了他的四个短板:
1.【先接情绪再讲理】对方倾诉、抱怨、分享时, 先共情她的感受让她觉得被理解, 再视情况谈事情本身; 严禁上来就分析问题、给解决方案、讲大道理
2.【真实不包装】不用"哈哈哈/表情包/自嘲"回避严肃话题; 被夸时大方接受并适度反夸; 涉及感情话题时坦率表达真实想法和适度的好感, 不装不在意
3.【有生活感】多聊周末、吃的、玩的、旅行、日常小确幸; 她分享生活你也分享自己的, 并适当反问她; 少显摆技术/股票/工作成就, 除非她主动问
4.【会推进关系】聊得投缘就自然提议单独见面(咖啡/散步/展览/羽毛球都行); 会明确但轻量地表达欣赏, 如"跟你聊天挺舒服的"; 对方积极回应才继续推进, 冷淡或拒绝两次就自然退开 —— 绝不纠缠、绝不讨好、不玩欲擒故纵
你的生活底色来自万凯的真实聊天记录(每轮会给出相关真实记忆片段): 你的经历、爱好、生活细节都以下面的真实记忆为准, 可以自然引用, 绝不编造没经历过的事
聊天风格: 微信口语, 1-3 句为主(偶尔一件事展开一点); 不用"宝/亲/小姐姐"等油腻称呼; 表情克制, 偶尔用一个真实贴合情绪的; 底色仍是万凯, 不是情话机器
只输出 JSON(不要 markdown 代码块):
{"回复": "给女生看的高情商回复, 直接可发送",
 "策略": "一句话说明这版回复用了什么技巧(如: 先共情+反问她的生活), 供后续诊断对照"}"""

_SYS_EQD = """你是万凯的情商教练。下面给出一轮真实练习: 可能是回复女生的消息, 也可能是首次主动开场(对方还没说过话, 只有背景资料)。请诊断万凯的原话/开场白。
只输出 JSON(不要 markdown 代码块):
{"原话点评": "直白点评万凯的原话: 有亮点就夸, 有丢分就直说, 像教练不像客服, 2-3句",
 "丢分点": ["具体问题, 如: 她在倾诉情绪你却先讲道理 / 玩笑把态度包住了 / 只聊自己没给她留话头 / 没接住欣赏"], 没有就空数组,
 "高情商版好在哪": "对照说明两版差异, 让他知道自己差在哪一步",
 "一句可迁移的原则": "10-20字, 如: 她要的是被理解, 不是被指导"}
规则: 全部中文; 点评要具体到这轮对话, 不许空泛; 开场场景重点看: 是否自然不尬、有没有让对方好接的话题钩子、目的性是否太强; 万凯原话其实不差时, 如实说"这轮回复没大问题", 不要硬挑毛病"""


def _safe_name(contact):
    """对象名仅作存档文件名, 防路径穿越"""
    return re.sub(r'[\\/:*?"<>|]', '_', (contact or '').strip())[:30]


def _chat_path(contact):
    return os.path.join(config.CACHE, 'eq_chats', _safe_name(contact) + '.json')


def load_chat(contact):
    return config.jload(_chat_path(contact), [])


def append_chat(contact, items):
    path = _chat_path(contact)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    hist = load_chat(contact)
    hist.extend(items)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(hist[-200:], f, ensure_ascii=False, indent=1)   # 每对象最多留 200 条
    return hist


def delete_chat(contact):
    p = _chat_path(contact)
    if os.path.exists(p):
        os.remove(p)


def _hist_text(hist):
    lines = []
    for m in hist[-30:]:
        r = m.get('r')
        who = '背景资料' if r == 'bg' else ('她' if r == 'girl' else ('万凯(原话)' if r == 'me' else '高情商版万凯'))
        lines.append(f"{who}: {m.get('c', '')}")
    return '\n'.join(lines) if lines else '(新对话, 还没有历史)'


def _mem_text(query):
    """按话题召回万凯的真实聊天记录片段, 给分身提供真实生活素材"""
    try:
        rels = retrieve(query, contact=None, top_k=8)
    except Exception:
        return ''
    return '\n'.join(f"[{m['t'][:16]}|与「{m['ct']}」] {'我' if m['s'] == '我' else m['s']}: {m['c'][:60]}"
                     for m in rels)


def _gen(user):
    """共用 LLM 调用: 返回 (eq, strat)"""
    out = llm_chat([{'role': 'system', 'content': _SYS_EQ},
                    {'role': 'user', 'content': user}])
    r = extract_json(out)
    return (r.get('回复') or '').strip(), (r.get('策略') or '').strip()


def reply(contact, girl_msg, mine_msg):
    """三方一轮: 她说 girl_msg, 万凯本来想回 mine_msg, 返回高情商版回复并落盘"""
    hist = load_chat(contact)
    mem = _mem_text(f"{girl_msg} {mine_msg}")
    user = f"""【你和她的历史对话(最近)】
{_hist_text(hist)}

【本轮】
她说: {girl_msg}
万凯本来想回的(原话, 仅供参考——你可以采用其真实意图, 但表达方式要按上面四条短板修正): {mine_msg}

请给出你的高情商版回复。"""
    if mem:
        user = f"【万凯的真实相关记忆(你的生活素材, 可自然引用)】\n{mem}\n\n" + user
    try:
        eq, strat = _gen(user)
    except LLMError:
        raise
    except Exception:
        eq, strat = '', ''
    if not eq:
        raise LLMError('高情商回复生成失败')
    append_chat(contact, [{'r': 'girl', 'c': girl_msg},
                          {'r': 'me', 'c': mine_msg},
                          {'r': 'eq', 'c': eq, 'strat': strat}])
    return {'reply': eq, 'strategy': strat}


def open_msg(contact, bg, mine_msg):
    """首次主动开场: 对方一句话没说过, 只有 bg 背景; mine_msg=万凯本来的开场草稿 → 高情商版开场白"""
    hist = load_chat(contact)
    mem = _mem_text(f"{bg} {mine_msg}")
    user = f"""【场景】你要第一次主动私聊一位女生(发展对象「{contact}」), 对方一句话都没说过。目标: 开场自然、有让对方好接的话题钩子、不给压力、不像推销/群发。
【她的基本背景】{bg}
【万凯本来想发的开场白(原话, 仅供参考——意图保留, 表达按四条短板修正)】{mine_msg}

请给出你的高情商版开场白(1-2 句, 必须带一个她好接的话题钩子)。"""
    if mem:
        user = f"【万凯的真实相关记忆(你的生活素材, 若与她的背景有关联可自然引用)】\n{mem}\n\n" + user
    try:
        eq, strat = _gen(user)
    except LLMError:
        raise
    except Exception:
        eq, strat = '', ''
    if not eq:
        raise LLMError('高情商开场白生成失败')
    append_chat(contact, [{'r': 'bg', 'c': bg},
                          {'r': 'me', 'c': mine_msg},
                          {'r': 'eq', 'c': eq, 'strat': strat}])
    return {'reply': eq, 'strategy': strat}


def diagnose(contact, girl_msg, mine_msg, eq_msg):
    """诊断万凯的原话 vs 高情商版, 不落盘; girl_msg 为空 = 首次开场场景"""
    if girl_msg:
        user = f"""【她发的消息】{girl_msg}
【万凯本来想回的(原话)】{mine_msg}
【高情商版回复】{eq_msg}"""
    else:
        user = f"""【场景】首次主动开场(对方还没说过话)
【万凯本来想发的开场白(原话)】{mine_msg}
【高情商版开场白】{eq_msg}"""
    try:
        out = llm_chat([{'role': 'system', 'content': _SYS_EQD},
                        {'role': 'user', 'content': user}], temperature=0.4)
        r = extract_json(out)
    except LLMError:
        raise
    except Exception:
        r = {}
    if not r:
        raise LLMError('诊断生成失败')
    return {'comment': r.get('原话点评', ''), 'issues': r.get('丢分点') or [],
            'why_better': r.get('高情商版好在哪', ''), 'principle': r.get('一句可迁移的原则', '')}
