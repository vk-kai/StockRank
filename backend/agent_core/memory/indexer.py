# -*- coding: utf-8 -*-
"""记忆索引层: 全量消息懒加载进内存 + 精确关键词搜索 + 上下文回查
原始数据只读; 消息位置 = (rel 文件相对路径, line 行号)"""
import os, re, json, threading
from agent_core import config
_mem_lock = threading.Lock()
_mem_index = None   # [{rel, line, t, s, c, cl, ct, ty}]
_mem_daily = None   # {'2022-02-09': n}


def display_name(fn):
    """文件名 '爸爸_wxid_xxx.jsonl' → 展示名 '爸爸'"""
    stem = fn[:-6] if fn.endswith('.jsonl') else fn
    for pat in (r'^(.*?)_wxid_[0-9a-zA-Z]+$', r'^(.*?)_\d+@chatroom$', r'^(.*?)_\d{5,}$'):
        m = re.match(pat, stem)
        if m and m.group(1):
            return m.group(1)
    return stem


def mem_index():
    """懒加载全量消息到内存: 文本检索 + 每日聚合共用一次遍历"""
    global _mem_index, _mem_daily
    if _mem_index is not None:
        return _mem_index
    with _mem_lock:
        if _mem_index is not None:
            return _mem_index
        idx, daily = [], {}
        for sub in ('私聊', '群聊'):
            d = os.path.join(config.DATA, sub)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not fn.endswith('.jsonl'):
                    continue
                rel = sub + '/' + fn
                ct = display_name(fn)
                with open(os.path.join(d, fn), encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            m = json.loads(line, strict=False)
                        except Exception:
                            continue
                        c = str(m.get('content', ''))
                        t = m.get('time', '')
                        idx.append({'rel': rel, 'line': i, 't': t, 's': m.get('speaker', ''),
                                    'c': c, 'cl': c.lower(), 'ct': ct, 'ty': m.get('type', 'text'),
                                    'w': (m.get('sender_wxid') or '').strip()})
                        day = t[:10]
                        if day:
                            daily[day] = daily.get(day, 0) + 1
        # 分身经历(网页端对话落盘, 见 memory/experience.py)并入检索语料:
        # 不进 daily 聚合 —— 数据档案的"每日消息数"只统计真实微信记录
        ep = os.path.join(config.KB, '分身经历.jsonl')
        if os.path.exists(ep):
            n_ep = 0
            with open(ep, encoding='utf-8') as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line, strict=False)
                    except Exception:
                        continue
                    ct = str(r.get('联系人', ''))[:60] or '对方'
                    for s, c in ((ct, str(r.get('对方消息', ''))), ('我', str(r.get('分身回复', '')))):
                        if not c:
                            continue
                        idx.append({'rel': '经历/分身经历.jsonl', 'line': i,
                                    't': str(r.get('时间', '')), 's': s, 'c': c,
                                    'cl': c.lower(), 'ct': ct, 'ty': 'text', 'w': ''})
                        n_ep += 1
            if n_ep:
                print(f'[记忆索引] 分身经历 {n_ep} 条', flush=True)
        _mem_index, _mem_daily = idx, daily
        print(f'[记忆索引] {len(idx)} 条消息, {len(daily)} 天', flush=True)
        return _mem_index


def mem_daily():
    mem_index()
    return _mem_daily or {}


def day_breakdown(day, month=False):
    """某天/某月每个联系人(含群)的消息分布 — 数据档案点击下钻用
    返回 [{name, is_group, n, mine, last_t, last_c}] 按消息量降序"""
    idx = mem_index()
    n_pre = 7 if month else 10
    pre = day[:n_pre]
    agg = {}   # (联系人, 是否群) -> [n, mine, last_t, last_c]
    for it in idx:
        t = it['t']
        if t[:n_pre] != pre:
            continue
        k = (it['ct'], it['rel'].startswith('群聊'))
        a = agg.get(k)
        if a is None:
            a = agg[k] = [0, 0, '', '']
        a[0] += 1
        if it['s'] == '我':
            a[1] += 1
        if t >= a[2]:
            a[2] = t
            a[3] = it['c']
    items = [{'name': k[0], 'is_group': k[1], 'n': a[0], 'mine': a[1],
              'last_t': a[2][11:16] if len(a[2]) > 16 else '', 'last_c': a[3]}
             for k, a in agg.items()]
    items.sort(key=lambda x: -x['n'])
    return items


def mem_search(q, contact=None, date_from=None, date_to=None, only_me=False, limit=40):
    """精确搜索: 所有关键词同时命中 (记忆搜索页用, 语义是"全部命中"而非"最相关")"""
    idx = mem_index()
    terms = [w.lower() for w in q.split() if w.strip()]
    if not terms:
        return []
    n_terms = len(terms)
    out = []
    for it in idx:
        if contact and it['ct'] != contact:
            continue
        if only_me and it['s'] != '我':
            continue
        day = it['t'][:10]
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        hit = sum(1 for w in terms if w in it['cl'])
        if hit == n_terms:
            out.append(it)
    out.sort(key=lambda x: x['t'], reverse=True)
    return out[:limit]


def mem_context(rel, line_no, n=10):
    """取某条消息前后各 n 条原始上下文"""
    if '..' in rel or '/' not in rel:
        return []
    sub, fn = rel.split('/', 1)
    if sub == '经历':
        p = os.path.join(config.KB, fn)   # 分身经历: 原文件在知识库目录
    elif sub in ('私聊', '群聊'):
        p = os.path.join(config.DATA, sub, fn)
    else:
        return []
    if not os.path.exists(p):
        return []
    lo = max(1, line_no - n)
    msgs = []
    with open(p, encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if i < lo:
                continue
            if i > line_no + n:
                break
            try:
                m = json.loads(line.strip(), strict=False)
            except Exception:
                continue
            m['_line'] = i
            m['_hit'] = (i == line_no)
            msgs.append(m)
    return msgs
