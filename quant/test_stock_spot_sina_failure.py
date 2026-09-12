import json
import sys
import traceback
from typing import Any

import akshare.stock.stock_zh_a_sina as sina_module
import pandas as pd

from backend.market.akshare_data import _fetch_stock_spot_sina_df


def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def safe_print(text: str) -> None:
    sys.stdout.write(str(text).encode("gbk", errors="replace").decode("gbk", errors="replace") + "\n")


def summarize_response(response: Any) -> dict:
    text = getattr(response, "text", "") or ""
    headers = dict(getattr(response, "headers", {}) or {})
    return {
        "status_code": getattr(response, "status_code", None),
        "content_type": headers.get("Content-Type") or headers.get("content-type"),
        "content_length": headers.get("Content-Length") or headers.get("content-length"),
        "url": getattr(response, "url", ""),
        "text_preview": text[:300],
    }


def print_dataframe_preview(df: pd.DataFrame, limit: int = 3) -> None:
    if df is None:
        print("返回: None")
        return
    if df.empty:
        print("返回空 DataFrame")
        return
    print(f"行数: {len(df)}, 列: {list(df.columns)}")
    print(json.dumps(df.head(limit).to_dict(orient="records"), ensure_ascii=False, indent=2, default=str))


def main() -> None:
    print_section("新浪 A 股现货接口常量")
    print(f"count_url: {sina_module.zh_sina_a_stock_count_url}")
    print(f"spot_url : {sina_module.zh_sina_a_stock_url}")
    print(f"payload  : {json.dumps(sina_module.zh_sina_a_stock_payload, ensure_ascii=False)}")

    original_get = sina_module.requests.get
    request_records: list[dict] = []

    def traced_get(*args, **kwargs):
        response = original_get(*args, **kwargs)
        record = summarize_response(response)
        request_records.append(record)
        return response

    sina_module.requests.get = traced_get
    try:
        print_section("直接调用 akshare.stock_zh_a_spot()")
        try:
            df = sina_module.stock_zh_a_spot()
            print_dataframe_preview(df)
        except Exception as exc:
            print(f"异常类型: {type(exc).__name__}")
            print(f"异常信息: {exc}")
            print("异常堆栈:")
            print(traceback.format_exc())

        print_section("HTTP 请求记录")
        if not request_records:
            print("没有捕获到请求记录")
        else:
            for index, record in enumerate(request_records, start=1):
                print(f"[{index}]")
                safe_print(json.dumps(record, ensure_ascii=False, indent=2, default=str))

        print_section("调用后端封装 _fetch_stock_spot_sina_df()")
        try:
            df = _fetch_stock_spot_sina_df(timeout=15)
            print_dataframe_preview(df)
        except Exception as exc:
            print(f"异常类型: {type(exc).__name__}")
            print(f"异常信息: {exc}")
            print("异常堆栈:")
            print(traceback.format_exc())
    finally:
        sina_module.requests.get = original_get


if __name__ == "__main__":
    main()
