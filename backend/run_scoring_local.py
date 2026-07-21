#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本地批量股票打分脚本 —— 产出 scores.json，手动上传到服务器。

为什么需要它：服务器调用智谱 AI (open.bigmodel.cn) 偶发 "Read timed out"，
导致批量打分中断/漏评。本脚本在本地跑（网络更稳、可随时重试、可断点续跑），
使用与服务器**完全相同**的评分逻辑和提示词（复用 stock_scorer 模块），
产出 data/stock_scores/scores.json —— 跑完把这个文件上传替换服务器同名文件即可。

用法（在 backend 目录 或 仓库根目录 都行）：
    python run_scoring_local.py                       # 全量打分（首次）
    python run_scoring_local.py --scope missing       # 只补未评分的（超时漏掉的）
    python run_scoring_local.py --scope insufficient  # 只重评"信息不足"的
    python run_scoring_local.py --rounds 3            # 全量 + 自动补漏2轮（推荐，对抗超时）
    python run_scoring_local.py --limit 30            # 只打分前30只（先小批验证提示词效果）

前提：
    1) config/ai_config.json 已配置好 AI（同服务器配置）
    2) data/realtime/market_map_industry.json 存在；没有会自动从东方财富抓取一次
"""
import os
import sys
import time
import argparse

# 让 backend 包内的模块可被导入（支持从仓库根或 backend 目录运行）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import stock_scorer
from data.data_processor import refresh_market_map_cache, get_all_market_map_stocks


def poll_until_done(label=''):
    """轮询打分进度直到结束，实时打印（含失败原因）。返回最终 status dict。"""
    last_line = ''
    last_err = None
    while True:
        st = stock_scorer.get_status()
        status = st.get('status')
        line = f"[{label}] {st.get('progress', 0):>3}% | {st.get('step', '')} | 成功 {st.get('done', 0)} 失败 {st.get('failed', 0)}"
        if line != last_line:
            print(line, flush=True)
            last_line = line
        # 失败原因：每次出现新原因就打印一次（不刷屏）
        err = st.get('last_error') or ''
        if err and err != last_err and st.get('failed'):
            print(f"   ⚠ 上一批失败原因：{err}", flush=True)
            last_err = err
        if status in ('completed', 'failed', 'interrupted'):
            print('   →', st.get('message', ''), flush=True)
            if st.get('last_error'):
                print('   → 最近失败原因：', st.get('last_error'), flush=True)
            return st
        time.sleep(3)


def ensure_stock_list():
    """本地无行业缓存时自动抓取一次；抓不到给出从服务器拷贝的提示。"""
    if get_all_market_map_stocks():
        return True
    print('本地无 data/realtime/market_map_industry.json，正在从东方财富抓取一次...', flush=True)
    cache = refresh_market_map_cache()
    if cache and cache.get('count'):
        print(f"   抓取完成：{cache['count']} 只股票", flush=True)
        return True
    print('   抓取失败。请从服务器把 data/realtime/market_map_industry.json 拷贝到本地同名路径后再运行。')
    return False


def main():
    ap = argparse.ArgumentParser(description='本地批量股票打分（产出 scores.json 供上传服务器）')
    ap.add_argument('--scope', choices=['all', 'missing', 'insufficient'], default='all',
                    help='all=全量(默认)；missing=只补未评分(超时漏的)；insufficient=只重评"信息不足"')
    ap.add_argument('--rounds', type=int, default=1,
                    help='总轮数：首轮用 --scope，后续轮自动用 missing 补漏（默认1；对抗超时推荐3）')
    ap.add_argument('--limit', type=int, default=0, help='只打分前N只（小批验证用；0=全部）')
    ap.add_argument('--yes', action='store_true', help='跳过开始前的回车确认')
    args = ap.parse_args()

    if not ensure_stock_list():
        return 1

    total_stocks = len(get_all_market_map_stocks())
    existing = stock_scorer.load_scores()
    print(f"本地股票清单：{total_stocks} 只 | 已有评分：{len(existing)} 只", flush=True)
    print(f"输出文件：{stock_scorer.STOCK_SCORES_FILE}", flush=True)
    plan = f"首轮 scope={args.scope}"
    if args.rounds > 1:
        plan += f"，随后 {args.rounds - 1} 轮 scope=missing 补漏"
    print(f"计划：{plan}", flush=True)

    if not args.yes:
        try:
            input('\n回车开始（Ctrl+C 取消）... ')
        except KeyboardInterrupt:
            print('已取消'); return 0

    # --limit：小批验证。临时限定 _load_stock_list 返回数量（start_scoring 与后台线程都会用到）
    if args.limit > 0:
        _orig_load = stock_scorer._load_stock_list
        def _limited(scope='all'):
            return _orig_load(scope=scope)[:args.limit]
        stock_scorer._load_stock_list = _limited

    try:
        for i in range(max(1, args.rounds)):
            scope = args.scope if i == 0 else 'missing'
            pending = len(stock_scorer._load_stock_list(scope=scope))
            if pending == 0:
                print(f"\n第{i + 1}轮 scope={scope}：无待评股票，跳过", flush=True)
                break
            print(f"\n===== 第{i + 1}轮 / scope={scope} / 待评 {pending} 只 =====", flush=True)
            res = stock_scorer.start_scoring(scope=scope)
            if not res.get('success') and res.get('status') != 'running':
                print('启动失败：', res.get('message'))
                return 1
            poll_until_done(label=f'R{i + 1}/{scope}')
            # 若已无未评分项，提前结束（不必跑满 --rounds）
            if len(stock_scorer._load_stock_list(scope='missing')) == 0:
                print('已无未评分项，提前完成。', flush=True)
                break
    except KeyboardInterrupt:
        print('\n收到 Ctrl+C，已请求停止（已评分结果已落盘，可重跑 --scope missing 继续）...')
        stock_scorer.stop_scoring()
        time.sleep(2)

    # 汇总
    scores = stock_scorer.load_scores()
    ins = sum(1 for v in scores.values() if '信息不足' in (v.get('reason') or ''))
    print('\n================== 完成 ==================')
    print(f'已评分：{len(scores)} / {total_stocks} 只')
    if ins:
        print(f'其中"信息不足"：{ins} 只（可运行 `python run_scoring_local.py --scope insufficient` 重评）')
    print(f'结果文件：{stock_scorer.STOCK_SCORES_FILE}')
    print('下一步：把该文件上传到服务器 data/stock_scores/scores.json 替换即可。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
