# -*- coding: utf-8 -*-
"""群聊模拟: 主要成员性格分析(程序统计 + LLM 速写, 缓存) + 群整体模拟回复

- members(group): 读群 jsonl 统计主要成员(消息数/占比/平均字长/深夜占比/样本)
- personas(group): LLM 一次性生成群氛围 + 各主要成员性格速写, 版本化缓存
- reply_group(group, message, hist): 一条消息 → 多个成员先后冒泡(贴合各自风格)
"""
import os
import re
import json
import glob
import threading
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent_core.config import DATA, CACHE, jload, atomic_write_json
from agent_core.llm_client import llm_chat, extract_json

_lock = threading.Lock()
_cache_f = os.path.join(CACHE, 'group_personas.json')


def _group_file(group):
    safe = re.sub(r'[\\/:*?"<>|]', '_', group)
    hits = glob.glob(os.path.join(DATA, '群聊', f'{safe}_*.jsonl'))
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


def members(group):
    """程序统计群主要成员(纯数据, 无 LLM)"""
    fp = _group_file(group)
    if not fp:
        return []
    st = {}   # speaker → {n, chars, late, last_ts, recent:[], words:Counter}
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                m = json.loads(line)
            except Exception:
                continue
            sp = (m.get('speaker') or '').strip()
            c = (m.get('content') or '').strip()
            if not sp or sp == '我' or not c or c.startswith('['):
                continue
            d = st.setdefault(sp, {'n': 0, 'chars': 0, 'late': 0, 'last_ts': '',
                                   'recent': [], 'words': {}})
            d['n'] += 1
            d['chars'] += len(c)
            t = m.get('time', '')
            if t:
                d['last_ts'] = max(d['last_ts'], t)
                try:
                    if int(t[11:13]) >= 23 or int(t[11:13]) < 6:
                        d['late'] += 1
                except Exception:
                    pass
            if len(c) <= 40 and len(d['recent']) < 400:
                d['recent'].append(f'[{t[5:16] if t else ""}] {c}')
            for w in re.findall(r'[\u4e00-\u9fa5]{2,4}', c):
                d['words'][w] = d['words'].get(w, 0) + 1
    if not st:
        return []
    total = sum(v['n'] for v in st.values())
    ranked = sorted(st.items(), key=lambda kv: -kv[1]['n'])
    # 主要成员: 占比>=2% 或 top10, 至少 10 条
    main = [(k, v) for k, v in ranked if v['n'] >= max(10, total * 0.02)][:10]
    if len(main) < 3:
        main = ranked[:6]
    out = []
    for k, v in main:
        words = [w for w, _ in sorted(v['words'].items(), key=lambda kv: -kv[1])[:5]]
        out.append({'name': k, 'n': v['n'], 'pct': round(v['n'] * 100.0 / total, 1),
                    'avg_len': round(v['chars'] / max(1, v['n']), 1),
                    'late_pct': round(v['late'] * 100.0 / max(1, v['n']), 1),
                    'last': v['last_ts'], 'words': words[:5],
                    'samples': v['recent'][-8:]})
    return out


def personas(group, progress=None):
    """群氛围 + 主要成员性格速写(LLM, 版本化缓存)"""
    with _lock:
        data = jload(_cache_f, {})
    ent = (data.get('groups') or {}).get(group)
    if ent and ent.get('v') == 2:
        return ent
    ms = members(group)
    if not ms:
        return {'tone': '群数据不足', 'members': [], 'generated_at': ''}

    desc = '\n'.join(
        f"- {m['name']}: {m['n']}条({m['pct']}%), 平均{m['avg_len']}字, "
        f"深夜发言{m['late_pct']}%, 高频词{m['words']}, 最近发言样本: "
        + ' | '.join(s.split('] ', 1)[-1][:30] for s in m['samples'][-5:])
        for m in ms)
    prompt = f"""以下是微信群「{group}」中主要成员的发言统计数据(均为程序统计的真实数据):
{desc}

请为这个群生成模拟人设, 严格返回 JSON:
{{"tone":"群整体氛围,一句话","members":[{{"name":"成员名(必须与上面完全一致)","persona":"2-3句性格与在群里的角色速写,口语化","style":"说话风格要点:句长/口头禅/表情使用/常用梗"}}]}}

要求: persona 必须从统计数据和发言样本推断, 不得凭空编造; style 里引用样本中的真实用词。"""
    try:
        if progress:
            progress(f'正在分析「{group}」的 {len(ms)} 位主要成员…')
        txt = llm_chat([{'role': 'user', 'content': prompt}], temperature=0.3)
        r = extract_json(txt)
        by = {m['name']: m for m in ms}
        mem = [x for x in r.get('members', []) if x.get('name') in by]
        ent = {'v': 2, 'tone': (r.get('tone') or '').strip(),
               'members': [{'name': x['name'], 'persona': x.get('persona', ''),
                            'style': x.get('style', ''), **by[x['name']]} for x in mem],
               'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    except Exception as e:
        # LLM 失败 → 退回纯统计
        ent = {'v': 2, 'tone': f'(性格速写生成失败: {e}; 以下为程序统计)',
               'members': [dict(m, persona='', style='') for m in ms],
               'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    with _lock:
        data = jload(_cache_f, {})
        data.setdefault('groups', {})[group] = ent
        atomic_write_json(_cache_f, data)
    return ent


def _recent_group_lines(group, k=16):
    fp = _group_file(group)
    if not fp:
        return []
    lines = []
    with open(fp, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
            if len(lines) > 4000:
                lines = lines[-4000:]
    out = []
    for line in lines[-200:]:
        try:
            m = json.loads(line)
        except Exception:
            continue
        c = (m.get('content') or '').strip()
        if not c or len(c) > 60 or c.startswith('[图片]') or c.startswith('[链接'):
            continue
        out.append(f"{m.get('speaker','?')}: {c}")
    return out[-k:]


def reply_group(group, message, hist=None, progress=None):
    """一条消息 → 群里多个成员先后冒泡。hist: [{'speaker','text'}] 本会话上下文"""
    ent = personas(group, progress=progress)
    ms = ent.get('members') or []
    if not ms:
        raise RuntimeError('该群没有可分析的主要成员')
    names = '、'.join(m['name'] for m in ms)
    pl = '\n'.join(f"- {m['name']}(占比{m['pct']}: {m['persona']} 风格: {m['style']})"
                   for m in ms)
    rl = _recent_group_lines(group)
    rl_s = ('\n'.join(rl)) if rl else '(无)'
    h = hist or []
    hs = '\n'.join(f"{x.get('speaker','我')}: {x.get('text','')}" for x in h[-10:]) or '(无)'
    prompt = f"""你在模拟微信群「{group}」的聊天。群氛围: {ent.get('tone','')}

群里可能冒泡的主要成员及人设:
{pl}

这个群最近的聊天(真实记录):
{rl_s}

本会话最近消息:
{hs}

现在「我」在群里发了新消息: {message}

请模拟群里成员的真实反应, 严格返回 JSON:
{{"replies":[{{"speaker":"成员名","text":"回复内容"}}, ...]}}

规则:
1. 1~4 位成员先后冒泡, 每人一条; 谁冒泡取决于话题和性格(与谁相关谁回, 有人可以潜水不回)
2. 每条回复的句长、语气、表情使用必须贴合该成员的人设与风格
3. 成员之间可以互相接梗、抬杠、玩这个群的梗
4. 名字只能从: {names} 中选
5. 内容要像真实的群聊碎片, 不要长篇大论, 不要总结腔"""
    if progress:
        progress('正在让群成员们冒泡…')
    txt = llm_chat([{'role': 'user', 'content': prompt}], temperature=0.9)
    r = extract_json(txt)
    valid = {m['name'] for m in ms}
    out = []
    for x in (r.get('replies') or []):
        sp = (x.get('speaker') or '').strip()
        t = (x.get('text') or '').strip()
        if sp in valid and t:
            out.append({'speaker': sp, 'text': t[:200]})
    if not out:  # 兜底: 最活跃成员
        out = [{'speaker': ms[0]['name'], 'text': (r.get('replies') or [{}])[0].get('text', '…')[:200]}]
    return {'replies': out[:4]}
