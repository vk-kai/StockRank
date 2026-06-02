import argparse
import sys
import time

import requests

from config import THS_SECTOR_NET_IN_URL, THS_SECTOR_NET_OUT_URL
from data_processor import generate_random_headers, normalize_ths_sector_headers, refresh_ths_cookie


TEST_URLS = [
    ("sector_in", THS_SECTOR_NET_IN_URL, "data.10jqka.com.cn", "https://data.10jqka.com.cn/funds/hyzjl/"),
    ("sector_out", THS_SECTOR_NET_OUT_URL, "data.10jqka.com.cn", "https://data.10jqka.com.cn/funds/hyzjl/"),
    ("indexflash", "https://q.10jqka.com.cn/api.php?t=indexflash&", "q.10jqka.com.cn", "https://q.10jqka.com.cn/"),
]


def preview_text(response):
    try:
        if response.encoding == "ISO-8859-1":
            response.encoding = "GBK"
        else:
            response.encoding = response.apparent_encoding or "GBK"
        return " ".join(response.text[:500].split())
    except Exception as exc:
        return f"<decode failed: {exc}>"


def marker_summary(text):
    lowered = text.lower()
    markers = []
    for marker in ["m-table", "forbidden", "unauthorized", "nginx", "captcha", "verify", "访问受限"]:
        if marker.lower() in lowered or marker in text:
            markers.append(marker)
    return ",".join(markers) or "-"


def build_headers(host, referer, cookie=""):
    headers = generate_random_headers(host=host, referer=referer)
    if host == "data.10jqka.com.cn":
        headers = normalize_ths_sector_headers(headers)
    else:
        headers["Host"] = host
        headers["Referer"] = referer
        headers["Accept"] = "*/*"
    if cookie:
        headers["Cookie"] = cookie
    return headers


def request_once(session, name, url, host, referer, cookie, proxies):
    headers = build_headers(host, referer, cookie)
    start = time.time()
    try:
        response = session.get(
            url,
            headers=headers,
            proxies=proxies,
            timeout=15,
            verify=False,
            allow_redirects=True,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        text = preview_text(response)
        print(f"[{name}] status={response.status_code} elapsed_ms={elapsed_ms} final_url={response.url}")
        print(f"[{name}] length={len(response.content)} markers={marker_summary(text)}")
        print(f"[{name}] preview={text}")
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        print(f"[{name}] error={type(exc).__name__}: {exc} elapsed_ms={elapsed_ms}")


def print_exit_ip(session, proxies):
    for url in ["https://api.ipify.org?format=text", "https://ifconfig.me/ip"]:
        try:
            response = session.get(url, proxies=proxies, timeout=10, verify=False)
            print(f"[exit_ip] {response.text.strip()}")
            return
        except Exception:
            continue
    print("[exit_ip] unavailable")


def main():
    parser = argparse.ArgumentParser(description="Diagnose THS access from this machine or proxy.")
    parser.add_argument("--proxy", help="Proxy URL, for example http://127.0.0.1:7890")
    parser.add_argument("--refresh-cookie", action="store_true", help="Try Chrome/Edge CDP cookie refresh first.")
    args = parser.parse_args()

    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    session = requests.Session()
    session.trust_env = False

    print_exit_ip(session, proxies)
    print(f"[config] sector_in={THS_SECTOR_NET_IN_URL}")
    print(f"[config] sector_out={THS_SECTOR_NET_OUT_URL}")

    cookie = ""
    if args.refresh_cookie:
        cookie = refresh_ths_cookie()
        print(f"[cookie] {'generated' if cookie else 'missing'}")

    for item in TEST_URLS:
        request_once(session, *item, cookie=cookie, proxies=proxies)

    return 0


if __name__ == "__main__":
    sys.exit(main())
