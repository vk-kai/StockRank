#!/usr/bin/env python
"""重建后复权(hfq)K 线数据。

本地 parquet 缓存此前是 pytdx(不复权)+ akshare(qfq)的混合,且无复权因子列,
无法就地换算成 hfq。本脚本用 akshare 后复权(hfq)重新拉取全市场日/周/月线,
以 replace_existing=True 整文件覆盖写回 data/kline/{code}/{period}.parquet。

用法:
    python scripts/rebuild_hfq_kline.py                       # 重建全股票池 daily
    python scripts/rebuild_hfq_kline.py --limit 20            # 只跑前 20 只(先测试)
    python scripts/rebuild_hfq_kline.py --codes 000001,600519 # 指定股票
    python scripts/rebuild_hfq_kline.py --period weekly       # 指定周期

注意:
- 全市场重建耗时较长(取决于网络与股票数量,可能数十分钟~数小时),请择机运行。
- 重建后回测数字会变化(变真实),旧的历史回测记录不可直接对比。
- 指数走 pytdx(不复权),脚本自动跳过;分钟线保持不复权,不在重建范围。
- 受 KLINE_MAX_HISTORY_YEARS(当前 3 年)限制,落盘会裁剪到该年限。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.kline_service import _fetch_remote_kline_for_cache, _kline_df_to_records
from backend.kline_parquet import upsert_kline_parquet
from backend.scan_universe_service import load_download_universe_snapshot
from backend import db


def detect_security_kind(code: str) -> str:
    code = str(code).zfill(6)
    if code in ("000300", "000016", "399001", "399006", "399005") or code.startswith("899"):
        return "index"
    if code.startswith(("51", "56", "58", "15", "16")):
        return "etf"
    return "stock"


def load_targets(codes_arg, limit):
    if codes_arg:
        return [{"code": c.strip().zfill(6), "name": c.strip().zfill(6)} for c in codes_arg.split(",") if c.strip()]
    targets = []
    seen = set()
    for item in load_download_universe_snapshot():
        code = str(item.get("code", "")).zfill(6)
        if not code or code in seen:
            continue
        seen.add(code)
        targets.append({"code": code, "name": str(item.get("name", "") or code)})
    if not targets:
        for item in db.list_stock_pool(scan_eligible_only=True):
            code = str(item.get("code", "")).zfill(6)
            if not code or code in seen:
                continue
            seen.add(code)
            targets.append({"code": code, "name": str(item.get("name", "") or code)})
    return targets[:limit] if limit else targets


def rebuild_one(code, period, fetch_count):
    kind = detect_security_kind(code)
    if kind == "index":
        return "skip", "指数(不复权,跳过)"
    df = _fetch_remote_kline_for_cache(code, period, fetch_count, kind)
    if df is None or df.empty:
        return "fail", "无数据"
    records = _kline_df_to_records(df, period)
    if not records:
        return "fail", "records 为空"
    upsert_kline_parquet(code, period, records, replace_existing=True)
    return "ok", f"{len(records)} 根({kind})"


def main():
    parser = argparse.ArgumentParser(description="重建后复权(hfq)K 线数据")
    parser.add_argument("--period", default="daily", help="周期: daily/weekly/monthly(默认 daily)")
    parser.add_argument("--codes", default="", help="指定代码,逗号分隔;不填则全股票池")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只(测试)")
    parser.add_argument("--fetch-count", type=int, default=1200, help="拉取根数(默认 1200)")
    args = parser.parse_args()

    if args.period not in ("daily", "weekly", "monthly"):
        print(f"[rebuild-hfq] period={args.period} 不是日/周/月,复权重建仅对日周月有意义。退出。")
        return

    targets = load_targets(args.codes, args.limit)
    print(f"[rebuild-hfq] 目标 {len(targets)} 只,period={args.period},fetch_count={args.fetch_count}")
    print("[rebuild-hfq] 日线用 akshare 后复权(hfq)整文件覆盖;指数/分钟线不重建。")

    counts = {"ok": 0, "fail": 0, "skip": 0}
    t0 = time.time()
    for i, item in enumerate(targets, 1):
        code = item["code"]
        name = item.get("name", code)
        try:
            status, msg = rebuild_one(code, args.period, args.fetch_count)
        except Exception as e:
            status, msg = "fail", f"异常:{e}"
        counts[status] = counts.get(status, 0) + 1
        if i % 20 == 0 or i == len(targets) or status == "fail":
            elapsed = time.time() - t0
            print(f"  [{i}/{len(targets)}] ok={counts['ok']} fail={counts['fail']} skip={counts['skip']} | {code} {name} -> {status} {msg} | 累计 {elapsed:.0f}s")

    print(f"\n[rebuild-hfq] 完成: ok={counts['ok']} fail={counts['fail']} skip={counts['skip']} 总用时 {time.time()-t0:.0f}s")
    print("[rebuild-hfq] 提示:回测数字现在基于 hfq 数据,会更真实;旧的历史回测记录不可直接对比。")


if __name__ == "__main__":
    main()
