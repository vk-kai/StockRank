import argparse
import json
import os
import traceback
from typing import Any

import pandas as pd

from backend.market import akshare_data


def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def summarize_df(df: pd.DataFrame | None, limit: int = 3) -> dict[str, Any]:
    if df is None:
        return {"is_none": True, "is_empty": True, "rows": 0, "columns": [], "preview": []}
    if df.empty:
        return {"is_none": False, "is_empty": True, "rows": 0, "columns": [str(col) for col in df.columns], "preview": []}
    return {
        "is_none": False,
        "is_empty": False,
        "rows": int(len(df)),
        "columns": [str(col) for col in df.columns],
        "preview": df.head(limit).to_dict(orient="records"),
    }


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def print_proxy_env() -> None:
    print_section("proxy env")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        print(f"{key}={os.environ.get(key, '')}")


def test_cninfo(code: str, timeout: int) -> None:
    print_section(f"cninfo test: {code}")
    try:
        df = akshare_data._fetch_stock_industry_cninfo_df(code, timeout=timeout)
        print_json(summarize_df(df))
        industry = akshare_data._get_stock_industry_from_cninfo(code, timeout=timeout)
        print(f"resolved_industry={industry}")
    except Exception as exc:
        print(f"cninfo_exception={type(exc).__name__}: {exc}")
        print(traceback.format_exc())


def test_sina_sector_preview(timeout: int, sector_limit: int, detail_limit: int) -> None:
    print_section("sina sector preview")
    try:
        sector_df = akshare_data._fetch_stock_sector_spot_df(timeout=timeout)
        summary = summarize_df(sector_df, limit=sector_limit)
        print_json(summary)
        if sector_df is None or sector_df.empty:
            return
        label_col = akshare_data._find_column(sector_df, "label")
        industry_col = akshare_data._find_column(sector_df, "板块")
        print(f"label_col={label_col}")
        print(f"industry_col={industry_col}")
        if not label_col or not industry_col:
            return
        sample_rows = sector_df.head(sector_limit).to_dict(orient="records")
        for row in sample_rows:
            sector_label = str(row.get(label_col, "") or "").strip()
            industry_name = str(row.get(industry_col, "") or "").strip()
            print_section(f"sina sector detail: {industry_name or sector_label}")
            try:
                detail_df = akshare_data._fetch_stock_sector_detail_df(sector_label, timeout=timeout)
                detail_summary = summarize_df(detail_df, limit=detail_limit)
                detail_summary["sector_label"] = sector_label
                detail_summary["industry_name"] = industry_name
                print_json(detail_summary)
            except Exception as exc:
                print(f"sina_detail_exception={type(exc).__name__}: {exc}")
                print(traceback.format_exc())
    except Exception as exc:
        print(f"sina_sector_exception={type(exc).__name__}: {exc}")
        print(traceback.format_exc())


def test_sina_map(code: str, timeout: int) -> None:
    print_section(f"sina map test: {code}")
    try:
        industry_map = akshare_data._get_stock_industry_map_from_sina(timeout=timeout, allow_stale=False)
        print(f"map_size={len(industry_map)}")
        if industry_map:
            sample_items = list(industry_map.items())[:10]
            print_json({"sample_items": sample_items, "industry_for_code": industry_map.get(code)})
        else:
            print_json({"sample_items": [], "industry_for_code": None})
    except Exception as exc:
        print(f"sina_map_exception={type(exc).__name__}: {exc}")
        print(traceback.format_exc())


def test_final_resolution(code: str) -> None:
    print_section(f"final resolution: {code}")
    try:
        industry = akshare_data.get_stock_industry(code)
        print(f"final_industry={industry}")
    except Exception as exc:
        print(f"final_resolution_exception={type(exc).__name__}: {exc}")
        print(traceback.format_exc())


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone stock industry source tester")
    parser.add_argument("--code", default="600519", help="stock code to inspect")
    parser.add_argument("--timeout", type=int, default=10, help="source request timeout in seconds")
    parser.add_argument("--sector-limit", type=int, default=2, help="number of sina sectors to preview")
    parser.add_argument("--detail-limit", type=int, default=3, help="number of detail rows to preview")
    parser.add_argument("--skip-sina-map", action="store_true", help="skip building full sina industry map")
    args = parser.parse_args()

    code = str(args.code).strip().zfill(6)
    print_proxy_env()
    test_cninfo(code, args.timeout)
    test_sina_sector_preview(args.timeout, args.sector_limit, args.detail_limit)
    if not args.skip_sina_map:
        test_sina_map(code, args.timeout)
    test_final_resolution(code)


if __name__ == "__main__":
    main()
