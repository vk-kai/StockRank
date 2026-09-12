import argparse
import time
from typing import Iterable

from backend import db
from backend.market.akshare_data import get_stock_industry
from backend.security_service import ensure_runtime_db_ready


def chunked(items: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]


def build_upsert_row(item: dict, industry: str) -> dict:
    return {
        "code": item.get("code"),
        "name": item.get("name"),
        "market": item.get("market"),
        "security_type": item.get("security_type"),
        "total_mv": item.get("total_mv"),
        "circ_mv": item.get("circ_mv"),
        "price": item.get("price"),
        "change_pct": item.get("change_pct"),
        "prev_close": item.get("prev_close"),
        "is_st": item.get("is_st"),
        "is_delisted": item.get("is_delisted"),
        "is_low_mv": item.get("is_low_mv"),
        "ma144_passed": item.get("ma144_passed"),
        "scan_eligible": item.get("scan_eligible"),
        "kline_downloaded": item.get("kline_downloaded"),
        "download_source": item.get("download_source"),
        "industry": industry,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刷新 stock_pool 中已入库股票的行业字段")
    parser.add_argument(
        "--codes",
        default="",
        help="只刷新指定代码，多个代码用逗号分隔，例如 300756,600519",
    )
    parser.add_argument(
        "--security-type",
        default="stock",
        help="默认只刷新 stock；如需全部证券类型可传 all",
    )
    parser.add_argument(
        "--only-empty",
        action="store_true",
        help="仅刷新当前 industry 为空的记录",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="每次请求后额外等待秒数，默认 0",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="批量写回数据库的条数，默认 50",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_runtime_db_ready()

    security_type = None if str(args.security_type).strip().lower() == "all" else str(args.security_type).strip()
    rows = db.list_stock_pool(security_type=security_type)

    code_filter = {
        str(code).strip().zfill(6)
        for code in str(args.codes or "").split(",")
        if str(code).strip()
    }
    if code_filter:
        rows = [item for item in rows if str(item.get("code", "")).zfill(6) in code_filter]
    if args.only_empty:
        rows = [item for item in rows if not str(item.get("industry", "") or "").strip()]

    total = len(rows)
    print(f"待刷新记录数: {total}")
    if total <= 0:
        return

    pending_updates: list[dict] = []
    changed = 0
    unchanged = 0
    unresolved = 0
    failed = 0

    for index, item in enumerate(rows, start=1):
        code = str(item.get("code", "")).zfill(6)
        name = str(item.get("name", "") or code)
        current_industry = str(item.get("industry", "") or "").strip()
        try:
            industry = (get_stock_industry(code) or "").strip()
            if not industry:
                unresolved += 1
                print(f"[{index}/{total}] {code} {name}: 未获取到行业")
            elif industry == current_industry:
                unchanged += 1
                print(f"[{index}/{total}] {code} {name}: 无变化 -> {industry}")
            else:
                changed += 1
                pending_updates.append(build_upsert_row(item, industry))
                print(f"[{index}/{total}] {code} {name}: {current_industry or '--'} -> {industry}")
                if len(pending_updates) >= max(1, int(args.batch_size)):
                    db.upsert_stock_pool(pending_updates)
                    pending_updates = []
        except Exception as exc:
            failed += 1
            print(f"[{index}/{total}] {code} {name}: 刷新失败 -> {type(exc).__name__}: {exc}")

        if args.sleep > 0:
            time.sleep(args.sleep)

    if pending_updates:
        db.upsert_stock_pool(pending_updates)

    print("")
    print("刷新完成")
    print(f"总数: {total}")
    print(f"已更新: {changed}")
    print(f"无变化: {unchanged}")
    print(f"未解析: {unresolved}")
    print(f"失败: {failed}")


if __name__ == "__main__":
    main()
