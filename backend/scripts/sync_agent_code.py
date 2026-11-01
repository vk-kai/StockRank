# -*- coding: utf-8 -*-
"""个人Agent 代码 → StockRank 一键同步器(代码部分)

主战场在本地桌面 个人Agent/, 平时只迭代本地; 本脚本把改动的代码拷进 StockRank
仓库并提交推送, 云端即可运行最新版。数据文件不归它管(走 agent_local_sync.py)。

用法:
  python backend/scripts/sync_agent_code.py [--dry-run] [--no-commit] [--no-push]
双击入口: 个人Agent/同步到云端.bat

拷贝白名单(只增改, 永不删除; 本地文件一律不动):
  根目录: cache_store.py / knowledge.py / llm_client.py / pipeline.py
  agents/*.py  analysis/*.py  memory/*.py  simulation/{engine,__init__}.py
明确不拷(云端各有专属版本或属运行数据):
  config.py(云端路径版) server.py(agent_routes.py 替代) config.json(含密钥)
  web/ cache/ evaluation/ simulation/*.json exports/ __pycache__

拷完自动执行: agent_adapt_imports.py(导入改写) → agent_build_vue.py(前端转换)
然后 git add 指定路径 + commit(+push)。config.json 若未被 .gitignore 覆盖会直接中止。
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))
CORE = os.path.join(REPO, 'backend', 'agent_core')
ADAPT = os.path.join(HERE, 'agent_adapt_imports.py')
BUILD_VUE = os.path.join(HERE, 'agent_build_vue.py')
DEFAULT_LOCAL = r'C:\Users\Administrator\Desktop\WeChatExport\个人Agent'

# git 提交范围(精确路径, 绝不 git add -A, 防止把密钥/数据带进仓库)
GIT_PATHS = [
    'backend/agent_core',
    'backend/routes/agent_routes.py',
    'backend/scripts',
    'backend/app.py',
    'frontend/src/AgentAvatar.vue',
    'frontend/src/router.js',
    'frontend/src/App.vue',
    'frontend/src/components/App/App.script.js',
    '.gitignore',
]

ROOT_FILES = ['cache_store.py', 'knowledge.py', 'llm_client.py', 'pipeline.py']
DIR_GLOBS = ['agents', 'analysis', 'memory']
SIM_FILES = ['simulation/engine.py', 'simulation/__init__.py']


def plan(local):
    """返回 [(src, dst), …] 拷贝清单"""
    pairs = []
    for f in ROOT_FILES:
        pairs.append((os.path.join(local, f), os.path.join(CORE, f)))
    for d in DIR_GLOBS:
        src_dir = os.path.join(local, d)
        dst_dir = os.path.join(CORE, d)
        if os.path.isdir(src_dir):
            for fn in sorted(os.listdir(src_dir)):
                if fn.endswith('.py'):
                    pairs.append((os.path.join(src_dir, fn), os.path.join(dst_dir, fn)))
    for f in SIM_FILES:
        pairs.append((os.path.join(local, f), os.path.join(CORE, f)))
    return [(s, d) for s, d in pairs if os.path.exists(s)]


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
    return r


def git(*args):
    return run(['git', *args], cwd=REPO)


def main():
    ap = argparse.ArgumentParser(description='个人Agent 代码同步到 StockRank')
    ap.add_argument('--local', default=DEFAULT_LOCAL, help='本地个人Agent目录')
    ap.add_argument('--dry-run', action='store_true', help='只打印拷贝计划, 不写任何文件')
    ap.add_argument('--no-commit', action='store_true', help='只拷贝+改写+生成前端, 不动 git')
    ap.add_argument('--no-push', action='store_true', help='提交但不推送')
    a = ap.parse_args()

    local = os.path.abspath(a.local)
    if not os.path.isdir(local):
        sys.exit(f'本地目录不存在: {local}')
    if not os.path.isdir(CORE):
        sys.exit(f'目标 agent_core 不存在(仓库不对?): {CORE}')

    # 安全闸: 含 api_key 的云端 config.json 必须被 .gitignore 覆盖, 否则中止
    chk = git('check-ignore', 'backend/agent_core/config.json')
    if chk.returncode != 0:
        sys.exit('⚠ backend/agent_core/config.json 未被 .gitignore 覆盖, 中止以防密钥入库')

    pairs = plan(local)
    print(f'同步计划: {len(pairs)} 个文件  {local}  →  {CORE}')
    for s, d in pairs:
        mark = '' if os.path.exists(d) else ' (新增)'
        print(f'  {os.path.relpath(d, CORE)}{mark}')
    if a.dry_run:
        print('dry-run: 未写入任何文件')
        return

    n = 0
    for s, d in pairs:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        n += 1
    print(f'已拷贝 {n} 个文件(本地原件一律保留)')

    print('改写 agent_core 导入前缀…')
    run([sys.executable, ADAPT])
    print('生成前端 AgentAvatar.vue…')
    run([sys.executable, BUILD_VUE, local])

    if a.no_commit:
        print('no-commit: 到此为止, 未提交')
        return

    if git('rev-parse', '--is-inside-work-tree').returncode != 0:
        sys.exit(f'{REPO} 不是 git 仓库')
    branch = (git('rev-parse', '--abbrev-ref', 'HEAD').stdout or '').strip()
    if branch != 'main':
        print(f'⚠ 当前分支是 {branch}(非 main), 仍按当前分支提交推送')

    git('add', *GIT_PATHS)
    staged = (git('diff', '--cached', '--name-only').stdout or '').split()
    if not staged:
        print('代码无变化, 跳过提交')
        return
    msg = f"个人Agent 代码同步 {datetime.now().strftime('%Y-%m-%d %H:%M')} ({len(staged)} 文件)"
    c = git('commit', '-m', msg)
    if c.returncode != 0:
        sys.exit('提交失败: ' + (c.stderr or c.stdout))
    print(f'已提交 {len(staged)} 个文件: {msg}')

    if a.no_push:
        print('no-push: 已提交未推送')
        return
    p = git('push')
    if p.returncode != 0:
        sys.exit('推送失败(检查网络/凭据), 本地提交已完成, 可手动 git push:\n' + (p.stderr or p.stdout))
    print('已推送到远端')


if __name__ == '__main__':
    main()
