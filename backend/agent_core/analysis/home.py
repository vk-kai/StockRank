# -*- coding: utf-8 -*-
"""首页「数字人生观察室」数据层 —— 程序计算为主, 不做全局总计类统计
- 昨晚最后聊天 / 近几日生活切片 / 最近常联系 / 重新活跃 / 逐渐疏远 / 一直保持联系 / 近期话题
全部一次遍历私聊消息得出, AI 只负责在前端做解释(单独接口)"""
import datetime, re
from collections import Counter, defaultdict
from agent_core.memory import indexer
from agent_core.knowledge import contacts
from agent_core.analysis import relationships as R

_MARK = re.compile(r'\[[^\]]{1,12}\]')          # [图片]/[表情] 等标记
_STOP = set('''我们 你们 他们 自己 什么 这个 那个 还是 没有 不是 就是 时候 知道 现在 可以
一个 一下 感觉 然后 因为 但是 如果 怎么 这样 那样 而且 所以 或者 只是 已经 应该 可能 是不是
不了 的话 起来 东西 事情 问题 直接 这样 出来 时间 今天 明天 昨天 早上 晚上 中午 多少 第一
哈哈 嘿嘿 好的 行了 好吧 嗯嗯 嗯 我也 你也 都可以'''.split())


def _clean(c):
    c = _MARK.sub('', c or '').strip()
    return c


def _weekday(d):
    return '一二三四五六日'[datetime.date.fromisoformat(d).weekday()]


def home_insights():
    idx = indexer.mem_index()
    now = datetime.datetime.now()
    today = datetime.date.today()
    d7 = (today - datetime.timedelta(days=7)).isoformat()
    d14 = (today - datetime.timedelta(days=14)).isoformat()
    d30 = (today - datetime.timedelta(days=30)).isoformat()
    d75 = (today - datetime.timedelta(days=75)).isoformat()

    circle_of = {c['姓名']: R._bucket(c.get('圈层猜测', '')) for c in contacts()}

    per_day = defaultdict(list)          # 'YYYY-MM-DD' -> [(time,name,speaker,content)]
    n7, n30 = Counter(), Counter()
    last_overall = {}                    # name -> (time, content)
    days_of = defaultdict(list)          # name -> sorted 活跃日列表

    f2n, _ = R.name_maps()
    for it in idx:
        if not it['rel'].startswith('私聊/'):
            continue
        day = it['t'][:10]
        if not day:
            continue
        name = f2n.get(it['rel'], it['ct'])
        per_day[day].append((it['t'], name, it['s'], it['c']))
        if day >= d7:
            n7[name] += 1
        if day >= d30:
            n30[name] += 1
        last_overall[name] = (it['t'], it['c'])
        days_of[name].append(day)

    # 1) 昨晚/晚间最后聊天 (按最后一条消息的真实时段标注口径)
    last_night = None
    for back in (1, 2, 3):
        day = (today - datetime.timedelta(days=back)).isoformat()
        rows = per_day.get(day)
        if rows:
            rows.sort()
            t, name, sp, c = rows[-1]
            hr = int(t[11:13])
            label = ('昨晚最后聊天' if (hr >= 22 or hr < 6)
                     else '昨天晚间最后聊天' if hr >= 18 else '昨天最后聊天')
            preview = _clean(c)
            if not preview:
                for t2, n2, s2, c2 in reversed(rows):
                    if _clean(c2):
                        preview = _clean(c2)
                        break
            last_night = {'date': day, 'weekday': _weekday(day), 'name': name,
                          'time': t[11:16], 'preview': preview[:80], 'label': label,
                          'n': len(rows), 'mine_last': sp == '我'}
            break

    # 2) 近几日生活切片(最近3个有记录的日子, 每天聊得最多的人 + 最后一条)
    life_cards = []
    for day in sorted(per_day, reverse=True):
        if day >= today.isoformat():
            continue
        rows = sorted(per_day[day])
        cnt = Counter(n for _, n, _, _ in rows)
        top_name, top_n = cnt.most_common(1)[0]
        preview = ''
        for t, n, s, c in reversed(rows):
            if n == top_name and _clean(c):
                preview = _clean(c)
                break
        life_cards.append({'date': day, 'weekday': _weekday(day), 'name': top_name,
                           'circle': circle_of.get(top_name, '其他'), 'n': top_n,
                           'total': len(rows), 'people': len(cnt),
                           'preview': preview[:70], 'time': rows[-1][0][11:16]})
        if len(life_cards) >= 3:
            break

    # 3) 最近常联系(近7天, 按消息量)
    recent = [{'name': n, 'circle': circle_of.get(n, '其他'), 'n7': c,
               'n30': n30.get(n, 0), 'last': last_overall.get(n, ('', ''))[0][:10]}
              for n, c in n7.most_common(8)]

    # 4) 重新活跃: 近14天有互动, 且此前沉寂≥60天; 按恢复稳定度分级
    reactivated = []
    for name, dlist in days_of.items():
        dlist = sorted(set(dlist))
        rec = [d for d in dlist if d >= d14]
        bef = [d for d in dlist if d < d14]
        if rec and bef:
            gap = (datetime.date.fromisoformat(min(rec))
                   - datetime.date.fromisoformat(max(bef))).days
            if gap >= 60:
                rd = len(rec)
                level = '稳定恢复' if rd >= 3 else ('短暂恢复' if rd == 2 else '偶然联系')
                reactivated.append({'name': name, 'circle': circle_of.get(name, '其他'),
                                    'gap_days': gap, 'n14': rd, 'level': level,
                                    'last': max(dlist)})
    reactivated.sort(key=lambda x: (-x['n14'], -x['gap_days']))

    # 5) 一直保持联系: 近5年每年都有私聊
    lifers = []
    need = {str(y) for y in range(today.year - 4, today.year + 1)}
    py_all = R.load()['per_year']
    for name, py in py_all.items():
        ys = {y for y, v in py.items() if v.get('n')}
        if need <= ys:
            lifers.append({'name': name, 'circle': circle_of.get(name, '其他'),
                           'years': len(ys), 'n30': n30.get(name, 0)})
    lifers.sort(key=lambda x: -x['n30'])

    # 6) 近期话题: 近30天私聊内容 2-gram 高频词, 相邻碎片合并("公积"+"积金"→"公积金")
    grams, tri = Counter(), Counter()
    for it in idx:
        if not it['rel'].startswith('私聊/') or it['t'][:10] < d30:
            continue
        c = _clean(it['c'])
        if len(c) < 2:
            continue
        for i in range(len(c) - 1):
            g = c[i:i + 2]
            if re.match(r'^[\u4e00-\u9fff]{2}$', g) and g not in _STOP:
                grams[g] += 1
                if i + 2 < len(c):
                    t3 = c[i:i + 3]
                    if re.match(r'^[\u4e00-\u9fff]{3}$', t3):
                        tri[t3] += 1
    merged = set()
    for t3, n3 in tri.items():
        a, b = t3[:2], t3[1:]
        if a in grams and b in grams and n3 >= min(grams[a], grams[b]) * 0.55 and n3 >= 8:
            if n3 >= grams.get(a, 0) and n3 >= grams.get(b, 0):
                merged.add(t3)
    for w in list(grams):
        if any(w in t for t in merged):
            del grams[w]
    for t3 in merged:
        grams[t3] = tri[t3]
    topics = [{'word': w, 'n': n} for w, n in grams.most_common(40) if n >= 8][:12]

    # 7) 疏远 / 圈层 (复用关系层)
    ls = R.life_stats()

    return {'date': today.isoformat(), 'weekday': _weekday(today.isoformat()),
            'last_night': last_night, 'life_cards': life_cards, 'recent': recent,
            'reactivated': reactivated[:6], 'lifers': lifers[:8], 'topics': topics,
            'fading': ls['fading'][:6], 'bridges': ls['bridges'][:6],
            'circles': R.circles()}
