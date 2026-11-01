# -*- coding: utf-8 -*-
"""关系网络数据层: 结构化计算为主, AI 分析为辅
- 直接边: 万凯↔联系人 (私聊统计, 可信)
- 共同群边: 联系人↔联系人 —— 仅代表"同群", 不等于真实关系, 展示时必须标注
- 按年统计: 每段关系每年消息量 → 关系演变 / 疏远检测
- 深夜长聊: 间隔≤30分钟的连续消息算一个会话, 识别"哪天和谁聊到几点"
- 桥梁人物: 同群对象跨越多个圈层的联系人
全部一次遍历懒构建, 结果缓存到 cache/relationships.json
"""
import os, re, threading, datetime
from collections import Counter
from agent_core import config
from agent_core.knowledge import contacts
from agent_core.memory import indexer

_lock = threading.Lock()
_data = None

_BUCKET = ('家人', '同事/工作', '朋友/其他')


def _bucket(cir):
    return cir if cir in _BUCKET else '其他'


def _parse(t):
    try:
        return datetime.datetime.strptime(t[:19], '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def _canon(s):
    """匹配用规范化: 去空格/下划线 + 忽略大小写 (档案姓名把 _ 换成了空格)"""
    return ''.join(ch for ch in s.casefold() if ch not in ' _')


def _name_maps():
    """文件 → 档案姓名 / wxid → 档案姓名
    档案姓名是净化版(去账号尾巴、_换空格), 正则不可靠, 用档案姓名本身做前缀匹配"""
    prof = {c['姓名'] for c in contacts()}
    by_canon = {}
    for n in prof:
        by_canon.setdefault(_canon(n), n)
    canon_sorted = sorted(by_canon.items(), key=lambda x: -len(x[0]))

    def resolve(raw):
        """原始名(文件名净化前) → 档案姓名"""
        if raw in prof:
            return raw
        return by_canon.get(_canon(raw))

    file2name, wx2name = {}, {}
    for sub in ('私聊', '群聊'):
        d = os.path.join(config.DATA, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith('.jsonl'):
                continue
            stem, rel = fn[:-6], sub + '/' + fn
            m = re.match(r'^(.+?)_wxid_(.+)$', stem)
            if m:
                name = resolve(m.group(1)) or m.group(1)
                file2name[rel] = name
                wx2name.setdefault(m.group(2), name)
                continue
            m = re.match(r'^(.+)_\d+@chatroom$', stem)
            if m:
                file2name[rel] = resolve(m.group(1)) or m.group(1)
                continue
            # 无 _wxid_ 标记: 姓名_账号, 用档案姓名 canon 前缀匹配
            best, boundary = None, -1
            for cn, n in canon_sorted:
                i, pos = 0, -1
                for j, ch in enumerate(stem):
                    if ch in ' _':
                        continue
                    if i < len(cn) and ch.casefold() == cn[i]:
                        i += 1
                        if i == len(cn):
                            pos = j + 1
                            break
                if pos > boundary:
                    best, boundary = n, pos
            if best:
                file2name[rel] = best
                if boundary < len(stem):
                    acc = stem[boundary:].lstrip('_')
                    if re.fullmatch(r'[\w\-.@]{4,}', acc):
                        wx2name.setdefault(acc, best)
    return file2name, wx2name


_nm_cache = None


def name_maps():
    """文件→档案姓名 / wxid→档案姓名 (模块级缓存)"""
    global _nm_cache
    if _nm_cache is None:
        _nm_cache = _name_maps()
    return _nm_cache


def _build():
    idx = indexer.mem_index()
    file2name, wx2name = name_maps()
    circle_of = {c.get('姓名'): _bucket(c.get('圈层猜测', '')) for c in contacts()}

    # 1) 私聊: 每联系人按年统计(总量+我方占比), 键=档案姓名
    per_year = {}
    by_rel = {}
    for it in idx:
        if it['rel'].startswith('私聊/'):
            y = it['t'][:4]
            if y:
                name = file2name.get(it['rel'], it['ct'])
                yy = per_year.setdefault(name, {}).setdefault(y, {'n': 0, 'mine': 0, 'm': {}})
                yy['n'] += 1
                mm = it['t'][5:7]
                if mm:
                    yy['m'][mm] = yy['m'].get(mm, 0) + 1
                if it['s'] == '我':
                    yy['mine'] += 1
            by_rel.setdefault(it['rel'], []).append(it)

    # 2) 群 → 成员wxid 集合
    # 文件名导出时剥掉了 wxid_ 前缀, 群消息里保留完整前缀 → 注册别名双向匹配
    alias = dict(wx2name)
    for k, v in wx2name.items():
        alias.setdefault('wxid_' + k, v)
    group_members = {}
    for it in idx:
        if it['rel'].startswith('群聊/') and it.get('w'):
            group_members.setdefault(it['ct'], set()).add(it['w'])

    # 3) 联系人之间的共同群边(仅"同群"证据, 非真实关系), wxid 归一到档案姓名
    shared = {}
    for g, members in group_members.items():
        present = sorted({alias[wx] for wx in members if wx in alias})
        if len(present) < 2 or len(present) > 400:
            continue
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                shared.setdefault((present[i], present[j]), []).append(g)
    shared_edges = [{'a': wa, 'b': wb, 'n': len(gs), 'groups': gs[:6]}
                    for (wa, wb), gs in shared.items()]
    shared_edges.sort(key=lambda x: -x['n'])

    # 4) 深夜长聊会话: 私聊内消息间隔≤30分钟连续算一段
    sessions = []
    for rel, items in by_rel.items():
        name = file2name.get(rel, items[0]['ct'] if items else '')
        cur = None
        for it in items:
            t = _parse(it['t'])
            if cur and t and (t - cur['_end']).total_seconds() <= 1800:
                cur['n'] += 1
                cur['mine'] += 1 if it['s'] == '我' else 0
                if t > cur['_end']:
                    cur['_end'] = t
                    cur['end'] = it['t'][:16]
            else:
                if cur:
                    sessions.append(cur)
                cur = None if not t else {'ct': name, 'start': it['t'][:16],
                                          '_end': t, 'end': it['t'][:16], 'n': 1,
                                          'mine': 1 if it['s'] == '我' else 0}
        if cur:
            sessions.append(cur)
    late = [s for s in sessions
            if s['n'] >= 10 and (s['_end'].hour >= 22 or s['_end'].hour < 6)]
    late.sort(key=lambda s: (-s['n'], s['_end'].hour))
    for s in late:
        s.pop('_end', None)
    late_sessions = late[:50]

    # 5) 桥梁人物: 同群对象覆盖 ≥2 个圈层
    co_circles = {}
    for e in shared_edges:
        for a, b in ((e['a'], e['b']), (e['b'], e['a'])):
            ca = circle_of.get(a)
            cb = circle_of.get(b)
            if ca and cb:
                co_circles.setdefault(a, Counter())[cb] += 1
    bridges = []
    for name, cnt in co_circles.items():
        strong = [c for c, n in cnt.items() if n >= 2]
        if len(strong) >= 2:
            bridges.append({'name': name, 'circles': strong,
                            'co_n': sum(cnt.values())})
    bridges.sort(key=lambda x: (-len(x['circles']), -x['co_n']))

    # 6) 圈层统计
    now = datetime.datetime.now()
    circles = {}
    for c in contacts():
        b = _bucket(c.get('圈层猜测', ''))
        cc = circles.setdefault(b, {'人数': 0, '消息': 0, '近120天活跃': 0})
        cc['人数'] += 1
        cc['消息'] += c.get('总消息', 0)
        last = _parse(c.get('末次', ''))
        if last and (now - last).days <= 120:
            cc['近120天活跃'] += 1

    # 7) 每个联系人参与的群
    member_groups = {}
    for g, members in group_members.items():
        for wx in members:
            n = alias.get(wx)
            if n:
                member_groups.setdefault(n, []).append(g)

    data = {'circles': circles, 'per_year': per_year, 'shared_edges': shared_edges[:3000],
            'late_sessions': late_sessions, 'bridges': bridges[:12],
            'member_groups': member_groups,
            'group_members_n': {g: len(m) for g, m in group_members.items()},
            'generated_at': datetime.datetime.now().isoformat(timespec='seconds')}
    try:
        config.atomic_write_json(os.path.join(config.CACHE, 'relationships.json'), data)
    except Exception:
        pass
    return data


def load():
    global _data
    if _data is not None:
        return _data
    with _lock:
        if _data is not None:
            return _data
        _data = _build()
        print('[关系网络] 已构建: %d 联系人, %d 共同群边, %d 深夜会话'
              % (sum(v['人数'] for v in _data['circles'].values()),
                 len(_data['shared_edges']), len(_data['late_sessions'])), flush=True)
        return _data


# ────────────────────────── 对外视图 ──────────────────────────
def graph(year=None, limit=140):
    """全局关系图: 万凯中心 + 联系人节点(圈层/强度) + 共同群边(仅同群证据)
    year 指定时按该年消息量取活跃节点"""
    d = load()
    if year:
        nodes = sorted(((n, v[year]['n']) for n, v in d['per_year'].items()
                        if v.get(year, {}).get('n')), key=lambda x: -x[1])[:limit]
        values = {n: n_ for n, n_ in nodes}
    else:
        allc = {c['姓名']: c.get('总消息', 0) for c in contacts()}
        values = dict(sorted(allc.items(), key=lambda x: -x[1])[:limit])
    circle_of = {c['姓名']: _bucket(c.get('圈层猜测', '')) for c in contacts()}
    info_of = {c['姓名']: c for c in contacts()}
    out_nodes = [{'name': n, 'circle': circle_of.get(n, '其他'), 'value': values[n],
                  'pct': round((info_of.get(n) or {}).get('我的占比%', 0), 1),
                  'last': (info_of.get(n) or {}).get('末次', '')[:10]}
                 for n in values if n in circle_of]
    names = set(values)
    edges = [{'a': e['a'], 'b': e['b'], 'n': e['n']} for e in d['shared_edges']
             if e['a'] in names and e['b'] in names and e['n'] >= 2][:220]
    return {'nodes': out_nodes, 'edges': edges, 'center': '万凯', 'year': year or 'all'}


def ego(name):
    """个人关系网: 万凯-X 的直接关系 + X 的同群联系人 + 按年演变 + 深夜长聊"""
    d = load()
    info = None
    for c in contacts():
        if c.get('姓名') == name:
            info = c
            break
    if not info:
        return None
    circle_of = {c['姓名']: _bucket(c.get('圈层猜测', '')) for c in contacts()}

    # 同群的人(来自共同群边 —— 注意: 这只是"同群"证据, 不是已证实的关系)
    shared_with = []
    for e in d['shared_edges']:
        if e['a'] == name:
            shared_with.append({'name': e['b'], 'n': e['n'],
                                'circle': circle_of.get(e['b'], '其他')})
        elif e['b'] == name:
            shared_with.append({'name': e['a'], 'n': e['n'],
                                'circle': circle_of.get(e['a'], '其他')})
    shared_with.sort(key=lambda x: -x['n'])

    my_groups = [{'group': g, 'members': d['group_members_n'].get(g, 0)}
                 for g in d['member_groups'].get(name, [])]
    my_groups.sort(key=lambda x: -x['members'])

    py = d['per_year'].get(name, {})
    return {'info': {k: info.get(k) for k in
                     ('姓名', '类别', '圈层猜测', '总消息', '我的发言', '对方发言',
                      '我的占比%', '首次', '末次')},
            'circle': circle_of.get(name, '其他'),
            'per_year': {y: py.get(y, {'n': 0, 'mine': 0}) for y in sorted(py)},
            'groups': my_groups,
            'shared_with': shared_with[:20],
            'late_sessions': [s for s in d['late_sessions'] if s['ct'] == name][:5]}


def circles():
    return load()['circles']


def life_stats():
    """首页: 时段分布(已有总览统计) + 深夜长聊 + 每人回复占比"""
    d = load()
    reply = []
    for c in contacts():
        if c.get('类别') != '私聊' or c.get('总消息', 0) < 10:
            continue
        reply.append({'name': c['姓名'], 'circle': _bucket(c.get('圈层猜测', '')),
                      'total': c.get('总消息', 0), 'mine': c.get('我的发言', 0),
                      'other': c.get('对方发言', 0), 'pct': c.get('我的占比%', 0)})
    reply.sort(key=lambda x: -x['total'])
    fading = _fading(d)
    return {'late_sessions': d['late_sessions'][:20], 'reply_share': reply[:40],
            'fading': fading, 'bridges': d['bridges']}


def _fading(d):
    """疏远检测: 同比比较 —— 今年至今 vs 去年/前年同期(到月粒度), 避免年末误报"""
    out = []
    now = datetime.datetime.now()
    y_now, mon = str(now.year), now.month
    months = [f'{i:02d}' for i in range(1, mon + 1)]
    for name, py in d['per_year'].items():
        try:
            n_now = py.get(y_now, {}).get('n', 0)
            n_now_p = sum(py.get(y_now, {}).get('m', {}).get(mm, 0) for mm in months)
            n_prev = py.get(str(now.year - 1), {}).get('n', 0)
            n_before = py.get(str(now.year - 2), {}).get('n', 0)
            prev_py = py.get(str(now.year - 1), {})
            n_prev_p = sum(prev_py.get('m', {}).get(mm, 0) for mm in months)
            bef_py = py.get(str(now.year - 2), {})
            n_before_p = sum(bef_py.get('m', {}).get(mm, 0) for mm in months)
        except Exception:
            continue
        base = max(n_prev_p, n_before_p)
        if not base:  # 旧缓存无月粒度 → 回退全年对比
            base = max(n_prev, n_before)
            n_now_p = n_now
        if base >= 80 and n_now_p < base * 0.35:
            out.append({'name': name, 'base': base, 'now': n_now_p,
                        'peak_year': str(now.year - 1) if n_prev_p >= n_before_p else str(now.year - 2)})
    out.sort(key=lambda x: -(x['base'] - x['now']))
    return out[:12]


def insight_context(names=None):
    """给关系洞察 Agent 的结构化背景(文本)"""
    d = load()
    ls = life_stats()
    lines = ['【圈层统计】']
    for k, v in d['circles'].items():
        lines.append(f"· {k}: {v['人数']}人, 累计{v['消息']}条, 近120天活跃{v['近120天活跃']}人")
    lines.append('【按消息量前15的联系人(我的回复占比%)】')
    for r in ls['reply_share'][:15]:
        lines.append(f"· {r['name']}({r['circle']}): {r['total']}条, 我占{round(r['pct'])}%")
    lines.append('【桥梁人物(同群对象跨圈层)】')
    for b in d['bridges'][:6]:
        lines.append(f"· {b['name']}: 连接 {'/'.join(b['circles'])}")
    lines.append('【可能疏远的人(近一年大滑坡)】')
    for f in ls['fading'][:8]:
        lines.append(f"· {f['name']}: 峰值年约{f['base']}条 → 今年{f['now']}条")
    if names:
        for n in names[:3]:
            py = d['per_year'].get(n)
            if py:
                lines.append(f"【与{n}的逐年消息量】" + ', '.join(
                    f"{y}:{v['n']}条(我{v['mine']})" for y, v in sorted(py.items())))
    return '\n'.join(lines)
