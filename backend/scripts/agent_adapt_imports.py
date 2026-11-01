# -*- coding: utf-8 -*-
"""个人Agent 代码 → StockRank agent_core 包 导入改写器

本地(个人Agent/)的模块使用顶层绝对导入(import config / from analysis import ...)。
拷入 StockRank backend/agent_core/ 后, StockRank 自己也有顶层 analysis 包, 直接
运行会冲突。本脚本把 agent_core 下所有 .py 的顶层模块导入统一加上 agent_core.
前缀, 使其成为规范的包内相对引用(效果等同相对导入, 但对同步脚本最友好:
本地源文件无需任何改动, 每次同步后重跑本脚本即可)。

用法: python backend/scripts/agent_adapt_imports.py
幂等: 已改写过的文件重复执行无副作用。
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '..', 'agent_core'))

# 个人Agent 的顶层模块名(仅这些会被加前缀, 避免误伤 import re/os/json 等)
TOP = r'(config|knowledge|llm_client|cache_store|pipeline|memory|agents|analysis|simulation)'

RULES = [
    # import knowledge as _kn  →  from agent_core import knowledge as _kn
    (re.compile(r'(?m)^(\s*)import ' + TOP + r'\s+as\s+(\w+)\s*$'),
     r'\1from agent_core import \2 as \3'),
    # import config  →  from agent_core import config
    (re.compile(r'(?m)^(\s*)import ' + TOP + r'\s*$'),
     r'\1from agent_core import \2'),
    # from analysis import profile  →  from agent_core.analysis import profile
    (re.compile(r'(?m)^(\s*)from ' + TOP + r'\b'),
     r'\1from agent_core.\2'),
]


def adapt_file(path):
    with open(path, encoding='utf-8') as f:
        src = f.read()
    out = src
    for pat, rep in RULES:
        out = pat.sub(rep, out)
    if out != src:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        return True
    return False


def main():
    changed = []
    for root, _dirs, files in os.walk(CORE):
        for fn in files:
            if fn.endswith('.py'):
                p = os.path.join(root, fn)
                if adapt_file(p):
                    changed.append(os.path.relpath(p, CORE))
    print('已改写 %d 个文件:' % len(changed))
    for c in sorted(changed):
        print('  ' + c)


if __name__ == '__main__':
    main()
