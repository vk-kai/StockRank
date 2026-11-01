# -*- coding: utf-8 -*-
"""个人Agent 数据同步器: 本地(主战场) → StockRank 云端

流程:
  1) (默认)重建知识库 pipeline.run_pipeline —— 新导入聊天记录后必须更新知识库
     (--skip-export 跳过, 直接同步现有知识库/数据文件)
  2) 收集本地 聊天记录数据/ Agent知识库/ 下 .jsonl/.json 的 [size, mtime] 清单
  3) GET /api/auth/otp-required 检查 OTP(开启则明确报错退出, 同步器不碰动态口令)
  4) POST /api/auth/login 拿 session cookie(默认 vk / vk666+月日, 北京时间自动算)
  5) GET /api/agent/sync/poll 取云端清单 → 比对出 新增/变更/云端多余
  6) POST /api/agent/sync/upload 分批上传(云端多余文件走 delete 清理改名旧文件)
  7) POST /api/agent/sync/rebuild 让云端清缓存 + 重建 FTS 索引

用法:
  python backend/scripts/agent_local_sync.py [--server URL] [--skip-export]
         [--dry-run] [--user vk] [--password XXXX] [--local 个人Agent目录]
只按文件大小比对增量(mtime 在重建后必然变化, 不可靠); 本地同名同名长文件视为已同步。
安全闸: 本地一个文件都没有时拒绝执行(防止从空机器反向清空云端)。
"""
import argparse
import base64
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DEFAULT_LOCAL = r'C:\Users\Administrator\Desktop\WeChatExport\个人Agent'
SUBDIRS = ('聊天记录数据', 'Agent知识库')
BATCH_FILES = 15          # 单批最多文件数
BATCH_CHARS = 5_000_000   # 单批内容字符上限(单文件超限则独占一批)

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def req(method, path, payload=None, timeout=120):
    url = SERVER.rstrip('/') + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={'Content-Type': 'application/json'})
    try:
        with _opener.open(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body[:300]
    except Exception as e:
        raise SystemExit(f'请求 {path} 失败: {e}')


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


def login(user, password):
    st, body = req('GET', '/api/auth/otp-required')
    if st == 200 and isinstance(body, dict) and body.get('otp_required'):
        raise SystemExit('服务器已开启 OTP 动态口令, 同步器无法自动登录。\n'
                         '请在服务器上临时关闭 OTP, 或自行在浏览器登录后改用其他方式同步。')
    pwd = password or f"vk666+{beijing_now().month:02d}{beijing_now().day:02d}"
    st, body = req('POST', '/api/auth/login', {'username': user, 'password': pwd})
    if st != 200 or not (isinstance(body, dict) and body.get('success', True)
                         and body.get('authenticated', True)):
        msg = body.get('message', body) if isinstance(body, dict) else body
        raise SystemExit(f'登录失败({st}): {msg}\n'
                         f'(密码默认 vk666+当天月日, 可用 --password 指定; '
                         f'注意北京时间跨天后口令变化)')
    print(f'已登录: {user} @ {SERVER}')


def local_paths(local_dir):
    """借本地 config.py 定位 数据/知识库 目录(项目搬家也不怕)"""
    try:
        sys.path.insert(0, local_dir)
        import config as lc  # noqa: E402
        return lc.DATA, lc.KB
    except Exception:
        parent = os.path.dirname(os.path.abspath(local_dir))
        return (os.path.join(parent, '聊天记录数据'),
                os.path.join(parent, 'Agent知识库'))


def collect_local(data_dir, kb_dir):
    out = {}
    for sub, root in (('聊天记录数据', data_dir), ('Agent知识库', kb_dir)):
        if not os.path.isdir(root):
            print(f'⚠ 本地缺目录: {root}')
            continue
        for cur, _d, fns in os.walk(root):
            for fn in fns:
                if fn.lower().endswith(('.jsonl', '.json')):
                    p = os.path.join(cur, fn)
                    rel = sub + '/' + os.path.relpath(p, root).replace('\\', '/')
                    out[rel] = [os.path.getsize(p), int(os.path.getmtime(p))]
    return out


def rel_to_local(rel, data_dir, kb_dir):
    sub, rest = rel.split('/', 1)
    base = kb_dir if sub == 'Agent知识库' else data_dir
    return os.path.join(base, *rest.split('/'))


def read_item(rel, data_dir, kb_dir):
    p = rel_to_local(rel, data_dir, kb_dir)
    raw = open(p, 'rb').read()
    try:
        return {'rel': rel, 'content': raw.decode('utf-8')}
    except UnicodeDecodeError:
        return {'rel': rel, 'content': base64.b64encode(raw).decode('ascii'), 'base64': True}


def batches(items):
    cur, chars = [], 0
    for it in items:
        n = len(it.get('content') or '') * 1.25 + 200
        if cur and (len(cur) >= BATCH_FILES or chars + n > BATCH_CHARS):
            yield cur
            cur, chars = [], 0
        cur.append(it)
        chars += n
    if cur:
        yield cur


def main():
    global SERVER
    ap = argparse.ArgumentParser(description='个人Agent 数据同步到云端')
    ap.add_argument('--server', default='http://127.0.0.1:5000', help='云端地址')
    ap.add_argument('--user', default='vk')
    ap.add_argument('--password', default='', help='不填则自动 vk666+月日')
    ap.add_argument('--local', default=DEFAULT_LOCAL, help='本地个人Agent目录')
    ap.add_argument('--skip-export', action='store_true', help='跳过知识库重建, 直接同步文件')
    ap.add_argument('--dry-run', action='store_true', help='只对比并打印计划, 不上传不删除')
    a = ap.parse_args()
    SERVER = a.server.rstrip('/')
    local_dir = os.path.abspath(a.local)

    # 1) 知识库重建(新导入聊天记录后必须)
    if not a.skip_export:
        try:
            sys.path.insert(0, local_dir)
            import pipeline
            print('重建知识库(pipeline)… 新导入聊天记录后这一步是必须的, 可能需要几分钟')
            pipeline.run_pipeline(progress=lambda s: print('  · ' + str(s)))
        except SystemExit as e:
            raise SystemExit(f'知识库重建中止: {e}')
        except Exception as e:
            print(f'⚠ 知识库重建失败({e}), 改用现有知识库文件继续同步')
    else:
        print('--skip-export: 跳过知识库重建')

    data_dir, kb_dir = local_paths(local_dir)
    local = collect_local(data_dir, kb_dir)
    if not local:
        raise SystemExit('本地没有任何数据文件, 拒绝同步(防止反向清空云端)')
    print(f'本地清单: {len(local)} 个文件, 共 '
          f'{sum(s for s, _ in local.values()) / 1e6:.1f} MB')

    login(a.user, a.password)
    st, poll = req('GET', '/api/agent/sync/poll', timeout=60)
    if st != 200 or not isinstance(poll, dict):
        raise SystemExit(f'拉取云端清单失败({st}): {poll}')
    remote = poll.get('files', {})
    print(f'云端清单: {len(remote)} 个文件')

    to_up = sorted(rel for rel, (sz, _mt) in local.items()
                   if rel not in remote or remote[rel][0] != sz)
    to_del = sorted(rel for rel in remote if rel not in local)
    skip = len(local) - len(to_up)
    print(f'比对结果: 待上传 {len(to_up)}, 云端多余待删 {len(to_del)}, 已一致 {skip}')
    for rel in to_up[:20]:
        print(f'  ↑ {rel} ({local[rel][0] / 1e6:.2f} MB)')
    for rel in to_del[:20]:
        print(f'  × {rel}')
    if a.dry_run:
        print('dry-run: 未上传未删除')
        return

    written, deleted, errs = 0, 0, []
    for i, b in enumerate(batches([read_item(rel, data_dir, kb_dir) for rel in to_up]), 1):
        print(f'上传批次 {i}({len(b)} 个文件, 约 {sum(len(x["content"]) for x in b) / 1e6:.1f} MB)…')
        st, body = req('POST', '/api/agent/sync/upload',
                       {'files': b, 'delete': []}, timeout=600)
        if st != 200 or not (isinstance(body, dict) and body.get('ok')):
            raise SystemExit(f'上传失败({st}): {body}')
        written += body.get('written', 0)
        errs += body.get('errors', [])
    if to_del:
        st, body = req('POST', '/api/agent/sync/upload',
                       {'files': [], 'delete': to_del}, timeout=300)
        if st == 200 and isinstance(body, dict):
            deleted = body.get('deleted', 0)
            errs += body.get('errors', [])
    for e in errs:
        print(f"  ⚠ {e.get('rel')}: {e.get('error')}")

    if to_up or to_del:
        st, body = req('POST', '/api/agent/sync/rebuild', {}, timeout=300)
        print(f'云端重载: {body.get("reloaded", body) if isinstance(body, dict) else body}')

    print(f'完成: 上传 {written}, 删除 {deleted}, 跳过(已一致) {skip}, 错误 {len(errs)}')
    if to_del:
        print('(云端多余文件已删除 —— 若非你改名/清理所致, 请检查本地目录是否完整)')


if __name__ == '__main__':
    main()
