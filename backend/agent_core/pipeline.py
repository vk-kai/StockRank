# -*- coding: utf-8 -*-
"""数据管道: 增量导出新聊天记录 → 重建 Agent 知识库 (网页一键触发, 全程无界面)

Step1 增量导出: 直连微信 WCDB(后台 node 服务, 复用 WeChat-Export-Tool-main),
  逐会话对比 db 消息数与 _增量状态.json 中上次导出时的数量:
  - 数量未变 → 跳过(不拉取, 秒过);
  - 数量变化 → 全量拉取该会话, 仅把 create_time > 上次末条时间 的消息追加到现有 jsonl;
  - 新会话 → 全量新建。绝不重写/覆盖已有历史消息。
Step2 知识库重建: 重跑 build_kb.py(纯程序, 无 LLM)重建 风格档案/联系人档案/范例库/事实,
  然后清空 FTS 索引让个人Agent自动重建(关系网/首页缓存带源指纹, 自动失效)。
"""
import os
import sys
import json
import time
import sqlite3
import threading
import subprocess

BASE = r'c:\Users\Administrator\Desktop\WeChatExport'
TOOL = os.path.join(BASE, 'WeChat-Export-Tool-main')
SRC = os.path.join(BASE, '聊天记录数据')
STATE_P = os.path.join(SRC, '_增量状态.json')
CACHE = os.path.join(BASE, '个人Agent', 'cache')
BUILD_KB = os.path.join(TOOL, 'build_kb.py')

SKIP_IDS = {'brandsessionholder', 'newsapp', 'weixin', 'filehelper', 'floatbottle',
            'fmessage', 'medianote', 'masssend', 'notification_messages', 'tmessage',
            'qmessage', 'qqmail', 'exdevice', 'appbrand'}
TYPE_ICON = {3: '[图片]', 34: '[语音]', 43: '[视频]', 47: '[动画表情]', 42: '[名片]',
             48: '[位置]', 50: '[通话]', 51: '[状态]'}
PAGE = 1000

_lock = threading.Lock()
_running = {'on': False, 'phase': '', 'at': None}


def env_ready():
    key_p = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop', 'wx_export', 'key.txt')
    wx_base = os.path.join(os.environ.get('USERPROFILE', ''), 'Documents', 'xwechat_files')
    return {'key': os.path.exists(key_p), 'key_path': key_p,
            'wechat_data': os.path.isdir(wx_base), 'wx_base': wx_base,
            'tool': os.path.exists(BUILD_KB)}


def status():
    env = env_ready()
    st = _jload(STATE_P, {})
    summary = _jload(os.path.join(SRC, '_汇总统计.json'), {})
    return {
        'ready': all([env['key'], env['wechat_data'], env['tool']]),
        'env': env,
        'tracked': len(st),
        'last_export': max((v.get('exported_at', '') for v in st.values()), default=''),
        'total_msgs': summary.get('消息总数', 0),
        'last_summary_time': summary.get('提取时间', ''),
        'running': _running['on'],
        'phase': _running['phase'],
        'last_run': _running['at'],
    }


def _jload(p, d):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return d


def _clean_wxid(wxid):
    parts = str(wxid).split('_')
    return '_'.join(parts[:2]) if len(parts) >= 3 else wxid


def _safe_name(s):
    import re
    return re.sub(r'[\\/:*?"<>|\s]+', '_', str(s)).strip('_')[:50] or 'unknown'


def _fmt_time(sec):
    if not sec:
        return ''
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(sec)))
    except Exception:
        return str(sec)


def _to_content(m):
    import re
    lt = int(m.get('local_type', 0) or 0)
    c = m.get('message_content', '') or ''
    if isinstance(c, dict):
        c = c.get('message_content', '') or ''
    c = str(c)
    if lt == 1:
        return 'text', c.strip()
    if lt == 10000 or lt == 10002:
        t = re.sub(r'<[^>]+>', ' ', c)
        t = re.sub(r'\s+', ' ', t).strip()
        return 'system', t[:300]
    if lt in TYPE_ICON:
        return {3: 'image', 34: 'voice', 43: 'video', 47: 'sticker', 42: 'contact',
                48: 'location', 50: 'call', 51: 'status'}[lt], TYPE_ICON[lt]
    if lt == 49 or c.lstrip().startswith('<msg') or c.lstrip().startswith('<?xml'):
        t = ''
        mm = re.search(r'<title>(.*?)</title>', c, re.S)
        if mm:
            t = re.sub(r'<[^>]+>', '', mm.group(1)).strip()
        return 'link', (t or '[链接/卡片]').strip()
    return f'type{lt}', c.strip()[:500]


def _file_last_ts(fpath):
    """读文件尾, 返回最后一条消息的 create_time(秒)"""
    if not os.path.exists(fpath):
        return 0
    size = os.path.getsize(fpath)
    with open(fpath, 'rb') as f:
        f.seek(max(0, size - 65536))
        tail = f.read().decode('utf-8', errors='ignore')
    for line in reversed([x for x in tail.split('\n') if x.strip()]):
        try:
            m = json.loads(line)
            t = m.get('time', '')
            if t:
                return int(time.mktime(time.strptime(t, '%Y-%m-%d %H:%M:%S')))
        except Exception:
            continue
    return 0


def _tail_fingerprints(fpath, since_ts):
    """读文件尾部, 返回 since_ts 之后已有消息的指纹集合 (time, speaker, content)"""
    exist = set()
    if not os.path.exists(fpath):
        return exist
    size = os.path.getsize(fpath)
    with open(fpath, 'rb') as f:
        f.seek(max(0, size - 524288))  # 尾部 512KB 足够覆盖回溯窗口
        tail = f.read().decode('utf-8', errors='ignore')
    for line in tail.split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
            t = m.get('time', '')
            if t and int(time.mktime(time.strptime(t, '%Y-%m-%d %H:%M:%S'))) >= since_ts:
                exist.add((t, m.get('speaker', ''), m.get('content', '')))
        except Exception:
            continue
    return exist


def _invalidate_caches(progress):
    """同步完成后统一清理进程内缓存, 让运行中的服务立即用上新数据"""
    n = []
    try:
        from agent_core.memory import indexer as _ix
        with _ix._mem_lock:
            _ix._mem_index = None
            _ix._mem_daily = None
        n.append('消息索引')
    except Exception:
        pass
    try:
        from agent_core.memory import retrieval as _rt
        with _rt._lock:
            _rt._state = None
        n.append('FTS状态')
    except Exception:
        pass
    try:
        from agent_core.analysis import relationships as _rl
        with _rl._lock:
            _rl._data = None
            _rl._nm_cache = None
        n.append('关系网')
    except Exception:
        pass
    try:
        from agent_core import knowledge as _kn
        _kn._ex_cache.clear()
        n.append('范例缓存')
    except Exception:
        pass
    try:
        from agent_core.analysis import group_persona as _gp
        for attr in ('_persona_cache',):
            if hasattr(_gp, attr):
                setattr(_gp, attr, None)
        n.append('群画像')
    except Exception:
        pass
    progress('进程内缓存已刷新: ' + ('/'.join(n) if n else '无'))


# ───────── Step1: 增量导出 ─────────

def step1_export(progress):
    sys.path.insert(0, os.path.join(TOOL, 'scripts'))
    from wcdb_server import WCDBClient

    key_p = os.path.join(os.environ['USERPROFILE'], 'Desktop', 'wx_export', 'key.txt')
    key = open(key_p, encoding='utf-8').read().strip()
    wx_base = os.path.join(os.environ['USERPROFILE'], 'Documents', 'xwechat_files')

    accs = []
    for d in os.listdir(wx_base):
        if d.startswith('wxid_'):
            sdb = os.path.join(wx_base, d, 'db_storage', 'session', 'session.db')
            if os.path.exists(sdb):
                accs.append((os.path.getmtime(sdb), os.path.join(wx_base, d)))
    accs.sort(reverse=True)
    if not accs:
        raise RuntimeError('未找到微信登录账号数据(xwechat_files)')
    acc_dir = accs[0][1]
    my_wxid = _clean_wxid(os.path.basename(acc_dir))
    progress(f'微信账号: {my_wxid}')

    progress('启动微信数据库后台服务…')
    c = WCDBClient()
    c.start(key, acc_dir,
            on_progress=lambda l: progress('  ' + l[7:90]) if l.startswith('[STAGE]') else None)
    try:
        sessions = c.get_sessions()
        try:
            names = c.get_display_names([s['username'] for s in sessions if s.get('username')])
        except Exception:
            names = {}
        targets = []
        for s in sessions:
            u = s.get('username', '') or ''
            if not u or u in SKIP_IDS or u.startswith('gh_'):
                continue
            targets.append((u, u.endswith('@chatroom')))

        state = _jload(STATE_P, {})
        for sub in ('私聊', '群聊'):
            os.makedirs(os.path.join(SRC, sub), exist_ok=True)

        total_new = 0
        updated, created = [], []
        for i, (u, is_group) in enumerate(targets, 1):
            try:
                cnt = int(c.get_count(u))
            except Exception:
                cnt = 0
            if cnt <= 0:
                continue
            old = state.get(u, {})
            if old.get('count') == cnt:
                continue  # 该会话无新消息, 跳过
            display = (names.get(u) or u).strip() or u
            kind = '群聊' if is_group else '私聊'
            fname = f'{_safe_name(display)}_{_safe_name(u)}.jsonl'
            fpath = os.path.join(SRC, kind, fname)
            old_path = old.get('fname') and os.path.join(SRC, old.get('kind', kind), old['fname'])
            if old_path and os.path.exists(old_path) and old_path != fpath:
                os.replace(old_path, fpath)  # 对方改名 → 文件跟随改名, 历史保留
            last_ts = _file_last_ts(fpath) if os.path.exists(fpath) else 0
            # 回溯窗口: 从 last_ts-1h 起取, 按指纹去重后追加 —— 防同秒/补录消息漏导
            cutoff = last_ts - 3600 if last_ts else 0
            exist = _tail_fingerprints(fpath, cutoff) if last_ts else set()

            rows = []
            offset = 0
            while offset < cnt:
                page = c.get_messages(u, PAGE, offset)
                if not page:
                    break
                rows.extend(page)
                offset += PAGE
                if len(page) < PAGE:
                    break
            rows.sort(key=lambda m: int(m.get('create_time', 0) or 0))
            new = [m for m in rows if int(m.get('create_time', 0) or 0) >= cutoff]

            n = 0
            max_ts = last_ts
            with open(fpath, 'a' if (os.path.exists(fpath) and last_ts) else 'w',
                      encoding='utf-8') as f:
                for m in new:
                    ts = int(m.get('create_time', 0) or 0)
                    typ, content = _to_content(m)
                    if not content:
                        continue
                    ts_str = _fmt_time(ts)
                    sr = m.get('sender_username', '') or ''
                    if sr and (sr == my_wxid or sr == os.path.basename(acc_dir)):
                        speaker, sender = '我', sr
                    else:
                        speaker = (names.get(sr) or sr or '对方').strip() or '对方'
                        sender = sr
                    fp = (ts_str, speaker, content)
                    if fp in exist:
                        continue  # 回溯窗口内已存在的消息, 跳过防重
                    exist.add(fp)
                    f.write(json.dumps({'time': ts_str, 'speaker': speaker,
                                        'sender_wxid': sender, 'type': typ, 'content': content},
                                       ensure_ascii=False) + '\n')
                    n += 1
                    max_ts = max(max_ts, ts)
            total_new += n
            state[u] = {'count': cnt, 'last_ts': max_ts, 'display': display,
                        'kind': kind, 'fname': fname,
                        'exported_at': time.strftime('%Y-%m-%d %H:%M:%S')}
            mark = '新会话' if not last_ts else '更新'
            (created if not last_ts else updated).append(display)
            progress(f'({i}) [{mark}] {kind} {display}: +{n} 条')
            if len(updated) + len(created) <= 3 or i % 50 == 0:
                pass

        # 重建汇总统计(全文件统计, 名字从状态恢复)
        disp_by_fname = {v.get('fname'): v for v in state.values()}
        manifest = []
        for kind in ('私聊', '群聊'):
            d = os.path.join(SRC, kind)
            for fn in os.listdir(d):
                if not fn.endswith('.jsonl'):
                    continue
                n, first, last = 0, '', ''
                with open(os.path.join(d, fn), encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        n += 1
                        try:
                            t = json.loads(line).get('time', '')
                        except Exception:
                            t = ''
                        if t:
                            if not first:
                                first = t
                            last = t
                meta = disp_by_fname.get(fn, {})
                manifest.append({'会话': meta.get('display') or fn[:-6].rsplit('_', 1)[0],
                                 'wxid': '', '类别': kind, '消息数': n,
                                 '首条时间': first, '末条时间': last,
                                 '文件': f'{kind}\\{fn}'})
        summary = {'说明': '微信聊天记录对话数据; 增量管道维护',
                   '提取时间': time.strftime('%Y-%m-%d %H:%M:%S'),
                   '会话总数(有消息)': len(manifest),
                   '消息总数': sum(x['消息数'] for x in manifest),
                   '会话明细': sorted(manifest, key=lambda x: -x['消息数'])}
        with open(os.path.join(SRC, '_汇总统计.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        with open(STATE_P, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        progress(f'导出完成: 新增 {total_new} 条 · 更新 {len(updated)} 个会话 · 新增 {len(created)} 个会话')
        return {'新增消息': total_new, '更新会话': updated[:20], '新增会话': created[:20],
                '消息总数': summary['消息总数']}
    finally:
        try:
            c.stop()
        except Exception:
            pass


# ───────── Step2: 重建知识库 ─────────

def step2_build(progress):
    progress('重建知识库(风格档案/联系人档案/范例库/事实记忆)…')
    r = subprocess.run([sys.executable, BUILD_KB], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', cwd=TOOL, timeout=600)
    if r.returncode != 0:
        raise RuntimeError('知识库重建失败: ' + ((r.stderr or '') + (r.stdout or ''))[-600:])
    progress('重置消息索引(下次检索自动全量重建)…')
    fts = os.path.join(CACHE, 'memory_fts.db')
    reset_ok = False
    for i in range(3):  # 服务可能正占用, 重试
        try:
            con = sqlite3.connect(fts)
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                con.execute(f'DROP TABLE IF EXISTS "{t}"')
            con.commit()
            con.close()
            reset_ok = True
            break
        except Exception:
            time.sleep(2)
    if not reset_ok:
        try:
            open(fts + '.rebuild', 'w').close()  # 强制重建标记, 下次启动检索时生效
            progress('  索引被占用, 已设强制重建标记(下次打开系统自动生效)')
        except Exception:
            progress('  索引重置失败, 请重启服务后重试')
    # 关系网/首页缓存带源指纹, 源数据变化后自动失效重建, 无需手动清理
    _invalidate_caches(progress)  # 运行中的服务立即看到新数据, 无需重启
    progress('知识库重建完成')
    return {'索引即时重置': reset_ok}


def run_pipeline(progress):
    """两步管道(带并发锁); progress(str) 用于实时推送到前端"""
    with _lock:
        if _running['on']:
            raise RuntimeError('已有同步任务在运行中')
        _running.update(on=True, phase='开始', at=time.strftime('%Y-%m-%d %H:%M:%S'))
    try:
        progress('── 第 1 步: 增量导出新聊天记录 ──')
        _running['phase'] = '增量导出'
        r1 = step1_export(progress)
        progress('── 第 2 步: 提取为 Agent 知识库 ──')
        _running['phase'] = '知识库重建'
        r2 = step2_build(progress)
        _running.update(on=False, phase='完成')
        return {'step1': r1, 'step2': r2}
    except Exception:
        _running.update(on=False, phase='失败')
        raise
