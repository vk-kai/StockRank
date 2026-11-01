# -*- coding: utf-8 -*-
"""数字人生模拟引擎 — 真实/虚拟严格隔离

隔离规则(硬编码在代码里, 不依赖 prompt 自觉):
1. 本模块对真实知识库(cache/)与聊天记录只读, 绝不回写;
2. 一切虚拟产物只写 个人Agent/simulation/ 目录;
3. 虚拟内容进入分身/分析上下文的唯一通路是 sim_note_for():
   仅当 (a)条目被用户逐条批准 且 (b)config.sim_merge=True 时才生效,
   且输出必带【虚拟推演】标注; 其余任何情况返回空字符串。
"""
import os
import re
import json
import random
import threading
import datetime as dt

from agent_core import config
from agent_core import knowledge
from agent_core.llm_client import llm_chat, extract_json, LLMError

SIM_DIR = os.path.join(config.APP, 'simulation')
EXPORT_DIR = os.path.join(SIM_DIR, 'exports')
STATE_P = os.path.join(SIM_DIR, 'sim_state.json')
TL_P = os.path.join(SIM_DIR, 'sim_timeline.json')
AUDIT_P = os.path.join(SIM_DIR, 'sim_audit.json')

_lock = threading.Lock()
_EMOJI = re.compile(r'\[[^\[\]]{1,6}\]|[^\w\s\u4e00-\u9fff,。?!、~…]')
_LAUGH = re.compile(r'哈|嘿|哈哈|笑死|[呲牙][偷笑]')

DEFAULT_STATE = {'sim_date': None, 'merge': False, 'steps': 0, 'last_real_date': None}


# ───────── 时事感知: 抓取真实新闻 RSS(只读外部, 注入推演作参考) ─────────
_NEWS_P = os.path.join(SIM_DIR, 'news_cache.json')
_NEWS_SOURCES = [
    ('IT之家', 'https://www.ithome.com/rss/'),
    ('36氪', 'https://36kr.com/feed'),
    ('人民网', 'http://www.people.com.cn/rss/politics.xml'),
]


def fetch_news(max_age_hours=6):
    """抓取最近新闻标题(多源 RSS, 失败静默跳过); 缓存 6 小时。
    离线/全部失败时返回空列表, 推演照常进行(只是没有时事参考)。"""
    cache = config.jload(_NEWS_P, None) or {}
    try:
        t = dt.datetime.fromisoformat(cache.get('fetched_at', ''))
        if (dt.datetime.now() - t).total_seconds() < max_age_hours * 3600:
            return cache.get('items', [])
    except Exception:
        pass
    import urllib.request
    import xml.etree.ElementTree as ET
    items = []
    for src, url in _NEWS_SOURCES:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            raw = urllib.request.urlopen(req, timeout=8).read()
            root = ET.fromstring(raw)
            n = 0
            for it in root.iter('item'):
                title = re.sub(r'<[^>]+>|<!\[CDATA\[|\]\]>', '', (it.findtext('title') or '')).strip()
                pub = (it.findtext('pubDate') or '')[:16]
                if title and n < 8:
                    items.append({'src': src, 'title': title[:60], 'date': pub})
                    n += 1
        except Exception:
            continue
    if items:
        cache = {'fetched_at': dt.datetime.now().isoformat(timespec='seconds'), 'items': items[:30]}
        try:
            config.atomic_write_json(_NEWS_P, cache)
        except Exception:
            pass
    return cache.get('items', [])


def _load(p, d):
    return config.jload(p, d)


def _save(p, obj):
    config.atomic_write_json(p, obj)


# ───────── 真实底座(只读) ─────────

def _profiles():
    """全部联系人档案(私聊+群聊)"""
    try:
        return [c for c in knowledge.contacts() if c.get('姓名')]
    except Exception:
        return []


def _last_real_date():
    profs = _profiles()
    ds = [c.get('末次', '') for c in profs if c.get('末次')]
    return max(ds)[:10] if ds else dt.date.today().isoformat()


def _active_pool():
    """可推演联系人池: 私聊且近90天有互动, 按消息量加权"""
    end = dt.date.fromisoformat(_last_real_date())
    pool = []
    for c in _profiles():
        if c.get('类别') != '私聊':
            continue
        last = c.get('末次', '')[:10]
        if not last:
            continue
        try:
            gap = (end - dt.date.fromisoformat(last)).days
        except ValueError:
            continue
        if gap <= 90 and c.get('总消息', 0) >= 150:
            pool.append({'name': c['姓名'], 'w': min(c.get('总消息', 0), 6000), 'gap': gap})
    return pool


def _pick_contacts(n):
    pool = _active_pool()
    if not pool:
        return []
    random.shuffle(pool)
    picks = []
    total = sum(p['w'] for p in pool)
    while len(picks) < min(n, len(pool)):
        r = random.uniform(0, total)
        acc = 0
        for p in pool:
            acc += p['w']
            if acc >= r:
                if p['name'] not in picks:
                    picks.append(p['name'])
                break
    return picks


def _recent_real_msgs(contact, n=14):
    """该联系人最近的真实对话(只读私聊 jsonl 末尾)"""
    try:
        from agent_core.analysis.profile import _find_source
        src = _find_source(contact)
        if not src:
            return []
        import io
        with io.open(src, encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[-n * 2:]
        out = []
        for ln in lines:
            try:
                m = json.loads(ln)
            except Exception:
                continue
            sp = '我' if m.get('speaker') == '我' else contact
            txt = (m.get('content') or '').strip()
            if txt:
                out.append(f"{m.get('time', '')[5:16]} {sp}: {txt[:60]}")
        return out[-n:]
    except Exception:
        return []


def _per_year(contact):
    try:
        from agent_core.analysis import relationships
        d = relationships.load()
        py = (d.get('per_person') or {}).get(contact, {}).get('per_year') or {}
        return {y: v.get('n', 0) for y, v in sorted(py.items())}
    except Exception:
        return {}


def _brief(contact):
    prof = knowledge.contact_info(contact) or {}
    frags, level, frm = knowledge.load_examples(contact, limit=5)
    return {
        'name': contact,
        'circle': prof.get('圈层猜测', ''),
        'total': prof.get('总消息', 0),
        'my_pct': prof.get('我的占比%', 0),
        'first': prof.get('首次', ''),
        'last': prof.get('末次', ''),
        'per_year': _per_year(contact),
        'recent_real': _recent_real_msgs(contact),
        'style_samples': [knowledge.frag_text(f) for f in (frags or [])],
    }


# ───────── 虚拟世界(读写 simulation/) ─────────

def _state():
    s = _load(STATE_P, dict(DEFAULT_STATE))
    if not s.get('last_real_date'):
        s['last_real_date'] = _last_real_date()
    return s


def _timeline():
    return _load(TL_P, [])


def _save_timeline(tl):
    _save(TL_P, tl)


def _next_id(tl):
    return 'SIM-%06d' % (len(tl) + 1)


def status():
    s = _state()
    tl = _timeline()
    aud = _load(AUDIT_P, {})
    approved = sum(1 for e in tl if e.get('approved'))
    return {
        'sim_date': s.get('sim_date'),
        'last_real_date': s.get('last_real_date'),
        'merge': s.get('merge', False),
        'steps': s.get('steps', 0),
        'count': len(tl),
        'approved': approved,
        'audit': {'at': aud.get('at'), 'personality_ok': aud.get('personality_ok'),
                  'conflicts': len(aud.get('conflicts', [])), 'note': aud.get('note', '')},
    }


# ───────── 推演 ─────────

_SYS = """你是「数字人生模拟引擎」。基于真实资料推演一个虚拟区间内, 万凯与若干联系人之间可能发生的日常交流。

铁律:
1. 这是"可能的人生"推演, 不是小说创作: 绝大多数内容必须是平静日常(问候、工作近况、家庭、吃饭、游戏、延续之前的兴趣话题); 禁止编造重大变故(疾病、事故、结婚、生子、离职、搬家、发财), 除非真实资料中有明确伏笔, 且要标注进 basis
2. 每个联系人的说话方式必须模仿其真实样本的语气和长度; 万凯的回复保持短句口语(多数不超过15个字), 与真实样本一致
3. 允许并鼓励生成 kind="quiet" 的平静日(该联系人这段时间没怎么聊), 不要为填满时间硬造对话
4. 尊重真实节奏: 周末/晚上聊天多, 工作日白天少; 关系亲密度参考"近年消息趋势"
5. 每条 entries 都要给 basis: 说明这段推演延续了真实资料中的哪些具体内容(未完结话题/关系状态/近期对话), basis 必须引用真实资料中的具体信息, 不能为空
6. 虚拟对话里出现的人名、地点、事项尽量来自真实资料; 实在需要新事物时只允许生活琐事级细节
7. 只输出 JSON"""


def run_step(days):
    """推进虚拟日历 days 天, 生成该区间内的虚拟经历"""
    with _lock:
        s = _state()
        tl = _timeline()
        if not s.get('sim_date'):
            base = dt.date.fromisoformat(s['last_real_date'])
            s['sim_date'] = (base + dt.timedelta(days=1)).isoformat()
        start = dt.date.fromisoformat(s['sim_date'])
        end = start + dt.timedelta(days=days - 1)

        names = _pick_contacts(min(4, max(2, days // 2)))
        if not names:
            raise LLMError('联系人池为空, 无法推演')

        briefs = []
        for n in names:
            b = _brief(n)
            sim_hist = [e for e in tl if e.get('contact') == n][-3:]
            briefs.append({
                'brief': b,
                'sim_hist': [{'date': e['date'], 'summary': e['summary']} for e in sim_hist],
            })

        wd = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        cal = '\n'.join(
            f"{(start + dt.timedelta(days=i)).isoformat()} {wd[(start + dt.timedelta(days=i)).weekday()]}"
            for i in range(days))

        parts = [f"[虚拟区间] {start.isoformat()} 至 {end.isoformat()} ({days}天)", f"[日历]\n{cal}"]
        facts = knowledge.facts()
        if facts:
            parts.append('[万凯人生事实(真实)]\n' + str(facts)[:900])
        # 时事参考: 真实新闻标题注入, 让推演贴合当下(离线时静默跳过)
        try:
            news = fetch_news()
            if news:
                parts.append('[近期真实新闻(时事参考, 只可引用这些, 禁止编造其他时事)]\n'
                             + '\n'.join(f"- [{x['src']}] {x['title']}" for x in news[:24]))
        except Exception:
            pass
        for it in briefs:
            b = it['brief']
            p = (f"\n[联系人 {b['name']}] 圈层:{b['circle']} 总消息:{b['total']} 我占比:{b['my_pct']}% "
                 f"首次:{b['first'][:10]} 末次:{b['last'][:10]} 按年消息:{json.dumps(b['per_year'], ensure_ascii=False)}")
            if b['recent_real']:
                p += '\n最近真实对话:\n' + '\n'.join(b['recent_real'])
            if b['style_samples']:
                p += '\n真实风格样本:\n' + '\n'.join(b['style_samples'][:3])[:700]
            if it['sim_hist']:
                p += '\n此前虚拟经历(请延续, 不要重复):\n' + '\n'.join(
                    f"{h['date']} {h['summary']}" for h in it['sim_hist'])
            parts.append(p)

        user = '\n'.join(parts) + (
            f"\n\n请推演这 {days} 天: 挑选 2-4 位联系人产生内容, 每位 1-3 条; "
            "其余日子作为 quiet 日(合并成几条 kind=quiet 的占位, 不写 messages)。"
            "\n时事结合: 结合上面的人生事实判断万凯会关心什么(如网络安全/漏洞/股市基金/科技数码/家乡榆林等), "
            "若某条真实新闻与他的兴趣相关, 可让虚拟对话以日常口吻自然提及(一两句带过, 像真人转述, 不要长篇大论); "
            "引用了哪条新闻要写进 basis; 没有合适新闻就照常推日常, 不要硬凑。"
            '\n输出 JSON: {"entries":[{"date":"YYYY-MM-DD","contact":"名字或空","kind":"chat|event|quiet",'
            '"summary":"一句话","messages":[{"speaker":"联系人名或我","content":"..."}],"basis":["..."]}]}'
            '\nkind=event 仅用于有真实伏笔的稍重大事项; chat 为日常虚拟对话; quiet 的 contact 留空、messages 为空数组。')

        raw = llm_chat([{'role': 'system', 'content': _SYS}, {'role': 'user', 'content': user}])
        data = extract_json(raw)
        entries = []

        for e in (data.get('entries') or []):
            date = str(e.get('date', ''))[:10]
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
                continue
            if not (start.isoformat() <= date <= end.isoformat()):
                continue
            kind = e.get('kind') if e.get('kind') in ('chat', 'event', 'quiet') else 'chat'
            msgs = []
            for m in (e.get('messages') or [])[:30]:
                sp = str(m.get('speaker', '')).strip()[:20]
                ct = str(m.get('content', '')).strip()[:200]
                if sp and ct:
                    msgs.append({'speaker': sp, 'content': ct})
            if kind == 'quiet':
                msgs = []
            contact = str(e.get('contact', '')).strip()[:20] or None
            ent = {
                'id': _next_id(tl) if not entries else 'SIM-%06d' % (len(tl) + len(entries) + 1),
                'date': date,
                'contact': contact,
                'kind': kind,
                'summary': str(e.get('summary', '')).strip()[:120],
                'messages': msgs,
                'basis': [str(x)[:160] for x in (e.get('basis') or [])[:4]],
                'drift': 0.0,
                'flags': [],
                'approved': False,
                'created_at': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            _audit_entry(ent, tl)
            entries.append(ent)

        tl.extend(entries)
        s['sim_date'] = (end + dt.timedelta(days=1)).isoformat()
        s['steps'] = s.get('steps', 0) + 1
        _save(STATE_P, s)
        _save_timeline(tl)
        return {'added': len(entries), 'sim_date': s['sim_date'],
                'entries': entries[-12:]}


# ───────── 程序审计(不依赖 LLM, 可靠) ─────────

def _bigrams(t):
    t = re.sub(r'\s', '', t or '')
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()


def _audit_entry(ent, tl):
    flags = []
    mine = [m['content'] for m in ent['messages'] if m['speaker'] == '我']
    if mine:
        avg = sum(len(x) for x in mine) / len(mine)
        if avg > 24:
            flags.append('我的消息平均%d字, 远超真实的8字风格' % avg)
        emo = sum(1 for x in mine if _EMOJI.search(x)) / len(mine)
        laugh = sum(1 for x in mine if _LAUGH.search(x)) / len(mine)
        if emo > 0.25:
            flags.append('表情使用率%.0f%%, 真实仅3.8%%' % (emo * 100))
        if laugh > 0.15:
            flags.append('带笑频率%.0f%%, 真实仅2.4%%' % (laugh * 100))
    if ent['kind'] in ('chat', 'event') and not ent['basis']:
        flags.append('无推演依据')
    if ent['contact'] and ent['kind'] == 'chat' and ent['messages']:
        olds = [e for e in tl if e.get('contact') == ent['contact']][-8:]
        txt = ''.join(m['content'] for m in ent['messages'])
        bg = _bigrams(txt)
        for o in olds:
            ot = ''.join(m['content'] for m in o.get('messages', []))
            ob = _bigrams(ot)
            if bg and ob:
                jac = len(bg & ob) / len(bg | ob)
                if jac > 0.5:
                    flags.append('与%s的虚拟对话高度重复(%.0f%%)' % (o['date'], jac * 100))
                    break
    if ent['kind'] == 'event' and len(ent['basis']) < 2:
        flags.append('重大事件但依据不足')
    ent['flags'] = flags
    ent['drift'] = round(min(1.0, 0.25 * len(flags)), 2)


def deep_audit():
    """AI 深度审计: 用真实 facts 反推虚拟经历是否产生幻觉"""
    tl = _timeline()
    recent = tl[-14:]
    if not recent:
        return {'at': dt.datetime.now().strftime('%Y-%m-%d %H:%M'), 'conflicts': [],
                'personality_ok': True, 'note': '暂无虚拟经历可审计'}
    facts = knowledge.facts()
    lst = '\n'.join(
        f"{e['id']} {e['date']} 与{e.get('contact') or '—'} [{e['kind']}] {e['summary']} 依据:{';'.join(e['basis'])[:100]}"
        for e in recent)
    user = (f'[万凯真实人生事实]\n{str(facts)[:800]}\n\n[最近虚拟推演经历]\n{lst}\n\n'
            '请审查: 1)conflicts: 虚拟经历中与真实事实/关系状态明显冲突的条目(给id和原因, 没有则空数组); '
            '2)personality_ok: 整体是否仍像万凯的人生轨迹(true/false); 3)note: 一两句中文总评。'
            '输出JSON: {"conflicts":[{"id":"...","issue":"..."}],"personality_ok":true,"note":"..."}')
    raw = llm_chat([{'role': 'system', 'content': '你是人格审计员, 只依据真实事实判断, 输出JSON'},
                    {'role': 'user', 'content': user}])
    data = extract_json(raw)
    rep = {'at': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
           'conflicts': (data.get('conflicts') or [])[:10],
           'personality_ok': bool(data.get('personality_ok', True)),
           'note': str(data.get('note', ''))[:200]}
    _save(AUDIT_P, rep)
    return rep


# ───────── 受控融合(唯一通路) ─────────

def sim_note_for(contact, limit=3):
    """分身/分析 agent 的虚拟经历注入。默认关闭; 仅'已批准'条目, 必带虚拟标注。"""
    s = _state()
    if not s.get('merge'):
        return ''
    tl = _timeline()
    rel = [e for e in tl if e.get('approved') and
           (e.get('contact') == contact or e.get('kind') == 'event')][-limit:]
    if not rel:
        return ''
    lines = []
    for e in rel:
        seg = f"{e['date']}(虚拟) 与{e.get('contact') or '—'}: {e['summary']}"
        if e['messages']:
            seg += ' | ' + ' / '.join(f"{m['speaker']}:{m['content'][:30]}" for m in e['messages'][:4])
        lines.append(seg)
    return ('【虚拟推演经历 · 非真实发生, 仅是模拟推演, 使用时不得声称真实发生过】\n' +
            '\n'.join(lines))


def approve(entry_id, ok):
    with _lock:
        tl = _timeline()
        for e in tl:
            if e['id'] == entry_id:
                e['approved'] = bool(ok)
                _save_timeline(tl)
                return True
    return False


def delete(entry_id):
    with _lock:
        tl = _timeline()
        n = len(tl)
        tl = [e for e in tl if e['id'] != entry_id]
        if len(tl) < n:
            _save_timeline(tl)
            return True
    return False


def set_merge(v):
    with _lock:
        s = _state()
        s['merge'] = bool(v)
        _save(STATE_P, s)


# ───────── 导出 ─────────

def export():
    tl = _timeline()
    if not tl:
        return None
    os.makedirs(EXPORT_DIR, exist_ok=True)
    fname = '推演时间线_%s.md' % dt.datetime.now().strftime('%Y%m%d_%H%M')
    path = os.path.join(EXPORT_DIR, fname)
    L = ['# 万凯 · 数字人生推演时间线', '',
         '> ⚠ 本文档全部内容为 AI 基于真实聊天记录推演的**虚拟内容**, 并非真实发生的事情。',
         '> 虚拟联系人的言行不代表其本人。生成时间: %s' % dt.datetime.now().strftime('%Y-%m-%d %H:%M'), '']
    last = None
    for e in tl:
        if e['date'][:4] != last:
            last = e['date'][:4]
            L.append('## %s (虚拟)' % last)
        mark = '✅已批准' if e.get('approved') else '·'
        warn = (' ⚠' + ';'.join(e['flags']) if e.get('flags') else '')
        L.append(f"- **{e['date']}** [{e['kind']}] {mark} 与{e.get('contact') or '—'}: {e['summary']}{warn}")
        if e.get('basis'):
            L.append(f"  - 依据: {'; '.join(e['basis'])}")
        for m in e.get('messages', []):
            L.append(f"  - {m['speaker']}: {m['content']}")
    L.append('')
    L.append('---')
    L.append('共 %d 条虚拟经历, 其中 %d 条已批准融合。' % (len(tl), sum(1 for e in tl if e.get('approved'))))
    config.atomic_write(path, '\n'.join(L).encode('utf-8'))
    return path
