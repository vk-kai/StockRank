# -*- coding: utf-8 -*-
"""群友提炼: 扫描群聊文件, 找出发言很多但未加为私聊好友的群成员,
提炼为「群友」类联系人 —— 与普通联系人同等对待(画像/检索/原始聊天)。
提炼名单存 KB/群友名单.json, 重建知识库不会丢失。"""
import os, re, json
from agent_core import config
from agent_core.knowledge import contacts, group_friends, save_group_friends

SKIP_SPEAKER = {'我', '', '对方'}
# 机器人/系统账号: openim 服务号、裸 wxid/gh_ 开头(昵称未设置的公众号或商家机器人)
_BOT = re.compile(r'@openim$|^wxid_[0-9a-z_]{6,}$|^gh_|^weixin$|^.getFloat|^Float')


def _is_bot(sp):
    return bool(_BOT.search(sp))


DEFAULT_MIN = 60   # 群内总消息门槛


def scan(min_msgs=DEFAULT_MIN):
    """返回候选群友列表(按总消息排序); 已是私聊好友或已提炼的不在内"""
    known = {c.get('姓名') for c in contacts()}
    stats = {}
    gdir = os.path.join(config.DATA, '群聊')
    if not os.path.isdir(gdir):
        return []
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
                    sp = m.get('speaker') or ''
                    if sp in SKIP_SPEAKER or _is_bot(sp) or sp in known:
                        continue
                    st = stats.get(sp)
                    if st is None:
                        st = stats[sp] = {'姓名': sp, '总消息': 0, '文本': 0,
                                          '首次': '', '末次': '', '群': {}}
                    st['总消息'] += 1
                    if (m.get('type') or 'text') == 'text':
                        st['文本'] += 1
                    t = m.get('time') or ''
                    if t:
                        if not st['首次'] or t < st['首次']:
                            st['首次'] = t
                        if not st['末次'] or t > st['末次']:
                            st['末次'] = t
                    st['群'][gname] = st['群'].get(gname, 0) + 1
        except Exception:
            continue
    out = []
    for st in stats.values():
        if st['总消息'] < min_msgs:
            continue
        main = max(st['群'], key=st['群'].get)
        out.append({'姓名': st['姓名'], '总消息': st['总消息'], '文本消息': st['文本'],
                    '首次': st['首次'][:19], '末次': st['末次'][:19],
                    '主群': main, '主群消息': st['群'][main],
                    '参与群数': len(st['群']),
                    '来源群': dict(sorted(st['群'].items(), key=lambda kv: -kv[1])[:8])})
    out.sort(key=lambda x: -x['总消息'])
    return out


def promote(name):
    """把一个群成员提炼为联系人; 返回档案条目"""
    name = (name or '').strip()[:60]
    if not name:
        raise ValueError('名字为空')
    if name in {g.get('姓名') for g in group_friends()}:
        raise ValueError(f'「{name}」已是提炼过的群友')
    cands = scan(min_msgs=1)
    c = next((x for x in cands if x['姓名'] == name), None)
    if not c:
        raise ValueError(f'「{name}」不在群聊记录中, 或已是私聊好友')
    entry = {'类别': '群友', '姓名': name, '总消息': c['总消息'],
             '我的发言': 0, '对方发言': c['总消息'], '我的占比%': 0,
             '首次': c['首次'], '末次': c['末次'],
             '圈层猜测': '朋友/其他', '主群': c['主群'],
             '来源群': c['来源群'], '文件': '群友/' + name}
    lst = group_friends()
    lst.append(entry)
    lst.sort(key=lambda x: -x.get('总消息', 0))
    save_group_friends(lst)
    return entry


def demote(name):
    """撤销提炼"""
    save_group_friends([g for g in group_friends() if g.get('姓名') != (name or '').strip()[:60]])
    return True
