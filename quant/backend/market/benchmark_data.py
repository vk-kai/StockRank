# -*- coding: utf-8 -*-
"""基准分时数据层（套利背离监控用）。

统一出口 ``get_benchmark_trends(kind, code)`` → 当日分钟级分时序列::

    {
        "kind": "em_board", "code": "BK0917", "source": "em_trends2",
        "trade_date": "2026-08-19", "pre_close": 1234.56, "pre_close_approx": False,
        "fetched_at": "2026-08-19 10:15:03", "stale": False,
        "points": [{"time": "09:31", "timestamp": 1755..., "price": 1240.1, "pct": 0.45}],
    }

kind 取值与主源:
- ``em_index``   A股指数(000001 等) → 东财 trends2 secid ``1.000001`` / ``0.399xxx``
- ``em_board``   东财概念/行业板块指数(BKxxxx) → secid ``90.BKxxxx``
- ``em_global``  全球指数(KOSPI=KS11) → secid ``100.KS11``
- ``tdx_board``  通达信 880 板块指数 → 直接走现有 pytdx ``get_index_kline("1min")``

兜底链: em_board → bench_registry 里的 880 孪生码; em_index → pytdx 指数分钟线。
em_global(KOSPI) 单独走"新浪实时优先"链(见 _fetch_kospi_trends): 新浪 b_KOSPI 快照
实时但无历史,东财 trends2 有全天曲线但全球指数免费行情实测滞后约 15~20 分钟,
故曲线 = 东财全量基线(低频回填) + 新浪实时快照按分钟覆盖,同分钟以新浪为准。
缓存/退避/陈旧兜底沿用 akshare_data._get_index_spot_df 的惯用法。
时间戳沿用 time_utils 的"北京墙钟当 epoch"约定,与个股分时 bar 对齐。
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from backend import db
from backend.config import (
    ARB_KOSPI_ACCUM_WINDOW,
    ARB_KOSPI_EM_BASE_TTL,
    ARB_TRENDS_CACHE_TTL,
    ARB_TRENDS_STALE_MAX_SECONDS,
)
from backend.market import pytdx_data
from backend.time_utils import now_beijing, to_chart_seconds

logger = logging.getLogger(__name__)

BENCH_KINDS = ("em_index", "em_board", "em_global", "tdx_board")

_EM_TRENDS_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
    "?secid={secid}"
    "&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
    "&iscr=0&ndays=1"
)
# 内置板块别名(关键词 → 东财 BK 码):在线解析失败时的兜底,也避免每次启动都搜一遍。
# pytdx 的 get_security_list 里没有 880xxx 板块指数(实测扫描为空),通达信兜底找不到孪生码,
# 所以核心板块直接内置 BK 码。国家大基金持股 = BK0717(quote.eastmoney.com/bk/BK0717.html)。
_BUILTIN_BOARD_ALIASES: dict[str, list[dict]] = {
    "国家大基金持股": [{"kind": "em_board", "code": "BK0717", "label": "国家大基金持股", "source": "builtin"}],
    "国家大基金": [{"kind": "em_board", "code": "BK0717", "label": "国家大基金持股", "source": "builtin"}],
    "大基金": [{"kind": "em_board", "code": "BK0717", "label": "国家大基金持股", "source": "builtin"}],
}
_EM_BOARD_LIST_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=1000&po=1&np=1&fltt=2&invt=2&fid=f12"
    "&fs=m:90+t:2&fields=f12,f14"
)
_SINA_KOSPI_URL = "https://hq.sinajs.cn/list=b_KOSPI"
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://quote.eastmoney.com/",
}
_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn/",
}

# trends 缓存: key -> (payload, fetched_at_aware)
_trends_cache: dict[str, tuple[dict, datetime]] = {}
# 拉取失败后的退避截止: key -> aware datetime
_trends_retry_blocked_until: dict[str, datetime] = {}
_trends_lock = threading.Lock()

# 通达信板块指数代码表(880xxx)懒加载缓存: {"loaded": bool, "boards": {code: name}}
_tdx_board_names: dict = {"loaded": False, "boards": {}}
_tdx_board_lock = threading.Lock()


# ---------------------------------------------------------------------------
# KOSPI 新浪快照 + 自累积曲线
# ---------------------------------------------------------------------------
class _KospiAccumulator:
    """KOSPI 分时曲线的双层累积器: 新浪实时覆盖层 + 东财全量基线层。

    新浪 b_KOSPI 快照实时但只有当前值 → 每次 upsert 当前分钟,构成实时尾巴;
    东财 trends2 有全天分钟曲线但全球指数免费行情滞后 15~20 分钟 → 低频回填,
    只负责补历史段。同一分钟两层都有值时以新浪为准;任一层日期不是今天则
    整层丢弃(避免韩国休市日把昨日曲线混进今天,分钟对齐会串值)。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._date = ""                       # 新浪覆盖层所属交易日
        self._points: dict[str, dict] = {}    # 新浪覆盖层: hhmm -> {price,pct}
        self._pre_close: Optional[float] = None
        self._base_date = ""                  # 东财基线所属交易日
        self._base_points: dict[str, dict] = {}
        self._base_pre_close: Optional[float] = None
        self._base_at: Optional[datetime] = None        # 基线最近一次成功拉取时间
        self._base_next_try: Optional[datetime] = None  # 基线失败后的重试时间(防打爆)

    @staticmethod
    def _today() -> str:
        return now_beijing().strftime("%Y-%m-%d")

    def set_em_base(self, fetched: dict) -> None:
        """用 _fetch_em_trends 的返回整体替换基线层(全量曲线,分钟级精度)。"""
        points = {p["time"]: {"price": p.get("price"), "pct": p.get("pct")} for p in fetched.get("points", [])}
        with self._lock:
            self._base_date = str(fetched.get("trade_date") or "")
            self._base_points = points
            if fetched.get("pre_close"):
                self._base_pre_close = float(fetched["pre_close"])
            self._base_at = now_beijing()
            self._base_next_try = None

    def note_base_failure(self) -> None:
        with self._lock:
            self._base_next_try = now_beijing() + timedelta(minutes=2)

    def base_expired(self, ttl_seconds: float) -> bool:
        with self._lock:
            now = now_beijing()
            if self._base_next_try is not None and now < self._base_next_try:
                return False
            if self._base_at is None:
                return True
            return (now - self._base_at).total_seconds() >= ttl_seconds

    def upsert_minute(self, hhmm: str, price: Optional[float], pct: Optional[float], pre_close: Optional[float] = None) -> None:
        with self._lock:
            if self._date != self._today():
                self._date = self._today()
                self._points = {}
            self._points[hhmm] = {"price": price, "pct": pct}
            if pre_close:
                self._pre_close = float(pre_close)

    def _fresh_layers_locked(self) -> tuple[dict, dict, bool, bool]:
        """(须持锁)返回(基线层, 覆盖层, 基线是否今日, 覆盖是否今日),过期层为空 dict。"""
        today = self._today()
        base = self._base_points if self._base_date == today else {}
        sina = self._points if self._date == today else {}
        return base, sina, bool(base), bool(sina)

    def latest_pct(self) -> Optional[float]:
        with self._lock:
            base, sina, _, _ = self._fresh_layers_locked()
            merged = {**base, **sina}
            if not merged:
                return None
            latest = max(merged.items(), key=lambda kv: kv[0])
            return latest[1].get("pct")

    def snapshot(self) -> Optional[dict]:
        """把合并后的曲线包装成 trends 同构 payload;两层都无今日数据返回 None。"""
        with self._lock:
            base, sina, has_base, has_sina = self._fresh_layers_locked()
            if not has_base and not has_sina:
                return None
            merged = {**base, **sina}
            if has_sina and has_base:
                source = "sina_em"
            elif has_sina:
                source = "sina_accum"
            else:
                source = "em_trends2"
            pre_close = self._pre_close if (self._date == self._today() and self._pre_close) else self._base_pre_close
            points = []
            for hhmm, item in sorted(merged.items()):
                naive = datetime.strptime(f"{self._today()} {hhmm}", "%Y-%m-%d %H:%M")
                points.append({
                    "time": hhmm,
                    "timestamp": int(to_chart_seconds(naive) or 0),
                    "price": item.get("price"),
                    "pct": item.get("pct"),
                })
            return {
                "kind": "em_global",
                "code": "KS11",
                "source": source,
                "trade_date": self._today(),
                "pre_close": pre_close,
                "pre_close_approx": False,
                "fetched_at": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
                "stale": False,
                "points": points,
            }


KOSPI_ACCUMULATOR = _KospiAccumulator()


def get_kospi_snapshot_sina(timeout: int = 6) -> Optional[dict]:
    """新浪 b_KOSPI 快照。实测字段: [1]=价 [2]=涨跌额 [3]=涨跌幅% [8]=开 [9]=昨收。"""
    try:
        response = requests.get(_SINA_KOSPI_URL, headers=_SINA_HEADERS, timeout=timeout)
        response.raise_for_status()
        response.encoding = "gbk"
        match = re.search(r'hq_str_b_KOSPI="([^"]*)"', response.text or "")
        if not match:
            return None
        # 名称后的首个分隔符是全角逗号(实测: 韩国KOSPI指数，6471.1700,...),先归一化
        parts = [p.strip() for p in match.group(1).replace("，", ",").split(",")]
        if len(parts) < 4:
            return None

        def _float(idx: int) -> Optional[float]:
            try:
                value = float(parts[idx])
            except (ValueError, IndexError):
                return None
            return value

        price = _float(1)
        pct = _float(3)
        pre_close = _float(9) if len(parts) > 9 else None
        if price is None or pct is None:
            return None
        # 字段[6]是该行情所属交易日(如 2026-08-19);韩国休市时返回的是旧 session,
        # 调用方据此不把旧 session 的值混进今天。解析失败则不给该字段(视为今天)。
        trade_date = None
        if len(parts) > 6 and re.match(r"^\d{4}-\d{2}-\d{2}$", str(parts[6]).strip()):
            trade_date = str(parts[6]).strip()
        return {
            "price": price,
            "pct": pct,
            "pre_close": pre_close,
            "trade_date": trade_date,
            "fetched_at": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        logger.debug("新浪KOSPI快照获取失败: %s", exc)
        return None


def _in_accum_window(hhmm: str) -> bool:
    start, end = ARB_KOSPI_ACCUM_WINDOW
    return str(start) <= hhmm <= str(end)


def _fetch_kospi_trends() -> Optional[dict]:
    """KOSPI 分时主链: 新浪实时快照优先,东财全量曲线低频回填,合并成当日曲线。

    东财全球指数免费行情实测滞后约 15~20 分钟,做主源会让曲线尾部(以及盘前
    KOSPI 提示)一直停在延迟值上;新浪 b_KOSPI 实时但只有当前价,所以每次调用
    都把当前分钟 upsert 进累积器,东财基线每 ARB_KOSPI_EM_BASE_TTL 秒才刷一次
    ——顺带把东财请求频率从每 12 秒降到每 10 分钟,降低被风控的概率。
    永不抛异常,两路都无今日数据时返回 None(交由上层陈旧缓存兜底)。
    """
    now = now_beijing()
    hhmm = now.strftime("%H:%M")
    today = now.strftime("%Y-%m-%d")
    if _in_accum_window(hhmm):
        snapshot = get_kospi_snapshot_sina(timeout=4)
        if snapshot and snapshot.get("trade_date") in (None, today):
            KOSPI_ACCUMULATOR.upsert_minute(hhmm, snapshot["price"], snapshot["pct"], snapshot.get("pre_close"))
    if KOSPI_ACCUMULATOR.base_expired(ARB_KOSPI_EM_BASE_TTL):
        try:
            KOSPI_ACCUMULATOR.set_em_base(_fetch_em_trends("100.KS11"))
        except Exception as exc:
            KOSPI_ACCUMULATOR.note_base_failure()
            logger.debug("KOSPI 东财基线刷新失败: %s", exc)
    payload = KOSPI_ACCUMULATOR.snapshot()
    if payload and payload.get("points"):
        return payload
    return None


# ---------------------------------------------------------------------------
# 东财 trends2
# ---------------------------------------------------------------------------
def _em_secid(kind: str, code: str) -> Optional[str]:
    text = str(code).strip().upper()
    if kind == "em_board":
        return f"90.{text}" if text.startswith("BK") else None
    if kind == "em_global":
        return f"100.{text}"
    if kind == "em_index":
        normalized = text.zfill(6)
        if not normalized.isdigit() or len(normalized) != 6:
            return None
        # 指数市场前缀与个股不同: 399xxx 深证 → 0, 000xxx 上证 → 1
        # (不能复用个股的 get_market_code, 000001 会被误判成深市)
        market = 0 if normalized.startswith("399") else 1
        return f"{market}.{normalized}"
    return None


def _fetch_em_trends(secid: str, timeout: int = 5) -> dict:
    url = _EM_TRENDS_URL.format(secid=secid)
    response = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
    response.raise_for_status()
    payload = response.json() or {}
    data = payload.get("data") or {}
    trends = data.get("trends") or []
    if not trends:
        raise ValueError(f"东财trends2返回空数据 secid={secid}")
    pre_close = None
    raw_pre = data.get("preClose") or data.get("preclose")
    try:
        if raw_pre is not None:
            pre_close = float(raw_pre)
    except (TypeError, ValueError):
        pre_close = None

    trade_date = str(data.get("date") or "")[:10]
    points = []
    first_open: Optional[float] = None
    for row in trends:
        # "2026-08-19 09:31,open,close,high,low,vol,amount,avg" 或 "09:31,..."
        segments = str(row).split(",")
        if len(segments) < 3:
            continue
        stamp = segments[0].strip()
        if " " in stamp:
            date_part, time_part = stamp.split(" ", 1)
            trade_date = date_part[:10]  # 行内日期比 envelope 的 date 字段更可靠
        else:
            time_part = stamp
            date_part = trade_date
        hhmm = time_part[:5]
        try:
            close = float(segments[2])
        except (TypeError, ValueError):
            continue
        if first_open is None:
            try:
                first_open = float(segments[1])
            except (TypeError, ValueError):
                first_open = None
        if not date_part:
            continue
        naive = datetime.strptime(f"{date_part[:10]} {hhmm}", "%Y-%m-%d %H:%M")
        points.append({
            "time": hhmm,
            "timestamp": int(to_chart_seconds(naive) or 0),
            "price": close,
            "pct": None,
        })
    if not points:
        raise ValueError(f"东财trends2解析后无有效点 secid={secid}")
    if pre_close is None:
        pre_close = first_open  # 兜底:用首点开盘价近似(标记 approx)
    approx = raw_pre is None
    if pre_close and pre_close > 0:
        for point in points:
            point["pct"] = round((point["price"] / pre_close - 1) * 100, 4)
    return {
        "trade_date": trade_date,
        "pre_close": pre_close,
        "pre_close_approx": approx,
        "points": points,
    }


# ---------------------------------------------------------------------------
# 通达信 880 板块指数
# ---------------------------------------------------------------------------
def _load_tdx_board_names() -> dict:
    """扫描 pytdx 上海市场证券列表,收集 880xxx 板块指数代码→名称(懒加载一次)。"""
    with _tdx_board_lock:
        if _tdx_board_names["loaded"]:
            return _tdx_board_names["boards"]
        boards: dict[str, str] = {}
        try:
            api = pytdx_data._get_api()
            if api:
                start = 0
                for _ in range(30):  # 上限保护:30000 条(880 板块在 SH 列表尾部)
                    batch = api.get_security_list(1, start) or []
                    if not batch:
                        break
                    for item in batch:
                        code = str(item.get("code", "")).strip()
                        if code.startswith("88"):
                            boards[code] = str(item.get("name", "")).strip()
                    start += len(batch)
                    if len(batch) < 1000:
                        break
        except Exception as exc:
            logger.debug("通达信板块指数列表加载失败: %s", exc)
        _tdx_board_names["boards"] = boards
        _tdx_board_names["loaded"] = True
        return boards


def _fetch_tdx_board_trends(code: str) -> dict:
    text = str(code).strip()
    df = pytdx_data.get_index_kline(text, "1min", 320)
    if df is None or df.empty or "datetime" not in df.columns:
        raise ValueError(f"pytdx 880板块无1分钟数据 code={text}")
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    latest_date = df["datetime"].dt.date.max()
    df = df[df["datetime"].dt.date == latest_date].reset_index(drop=True)
    if df.empty:
        raise ValueError(f"pytdx 880板块当日无数据 code={text}")

    # 昨收兜底链: 实时快照昨收 → 当日首根bar开盘近似
    pre_close = None
    quotes = pytdx_data.get_realtime_quotes([text])
    if quotes and quotes[0].get("pre_close"):
        pre_close = float(quotes[0]["pre_close"])
    approx = pre_close is None
    if pre_close is None:
        pre_close = float(df.iloc[0]["open"])
    if not pre_close or pre_close <= 0:
        raise ValueError(f"pytdx 880板块昨收无效 code={text}")

    points = []
    for _, row in df.iterrows():
        naive = pd.Timestamp(row["datetime"]).to_pydatetime().replace(tzinfo=None)
        price = float(row["close"])
        points.append({
            "time": naive.strftime("%H:%M"),
            "timestamp": int(to_chart_seconds(naive) or 0),
            "price": price,
            "pct": round((price / pre_close - 1) * 100, 4),
        })
    return {
        "trade_date": str(latest_date),
        "pre_close": pre_close,
        "pre_close_approx": approx,
        "points": points,
    }


def _fetch_index_minutes_pytdx(code: str) -> dict:
    """em_index 兜底: pytdx 指数 1 分钟线(复用 860 板块同样的整形逻辑)。"""
    return _fetch_tdx_board_trends(str(code).strip().zfill(6))


# ---------------------------------------------------------------------------
# 板块代码解析(名称 → 多源候选)
# ---------------------------------------------------------------------------
def _em_board_search(keyword: str) -> list[dict]:
    try:
        response = requests.get(_EM_BOARD_LIST_URL, headers=_HTTP_HEADERS, timeout=6)
        response.raise_for_status()
        payload = response.json() or {}
        rows = (payload.get("data") or {}).get("diff") or {}
        if isinstance(rows, dict):
            rows = list(rows.values())
        matched = []
        for item in rows:
            name = str(item.get("f14") or "").strip()
            code = str(item.get("f12") or "").strip().upper()
            if code.startswith("BK") and keyword in name:
                matched.append({"kind": "em_board", "code": code, "label": name, "source": "em"})
        return matched
    except Exception as exc:
        logger.debug("东财板块搜索失败 %s: %s", keyword, exc)
        return []


def _tdx_board_search(keyword: str) -> list[dict]:
    boards = _load_tdx_board_names()
    matched = []
    for code, name in boards.items():
        if keyword and keyword in name:
            matched.append({"kind": "tdx_board", "code": code, "label": name, "source": "tdx"})
    matched.sort(key=lambda item: item["code"])
    return matched[:10]


def resolve_board_code(keyword: str) -> list[dict]:
    """按关键词解析板块基准候选: 内置别名 → 东财板块列表 → bench_registry 缓存 → 通达信 880 表。"""
    text = str(keyword or "").strip()
    if not text:
        return []
    # 内置别名优先:核心板块(国家大基金持股等)不依赖在线解析
    for alias, items in _BUILTIN_BOARD_ALIASES.items():
        if text == alias or (text in alias and len(text) >= 2):
            return items
    cached = None
    try:
        cached = db.get_bench_registry(text)
    except Exception:
        cached = None

    fresh: list[dict] = []
    try:
        fresh = _em_board_search(text)
    except Exception:
        fresh = []
    if fresh:
        try:
            fresh.extend(_tdx_board_search(text))
        except Exception:
            pass
        try:
            db.upsert_bench_registry(text, fresh[:10])
        except Exception:
            pass
        return fresh[:10]
    if cached:
        return cached
    try:
        tdx_only = _tdx_board_search(text)
    except Exception:
        tdx_only = []
    if tdx_only:
        try:
            db.upsert_bench_registry(text, tdx_only)
        except Exception:
            pass
        return tdx_only
    return cached or []


def _tdx_twin_code(kind: str, label: Optional[str]) -> Optional[str]:
    """em_board 的 880 孪生码: 用板块名在通达信 880 表里找同名指数。

    label 由调用方传入(配对表里存的 bench_label / 搜索结果里的名称),
    registry 键是中文关键词,不能用 BK 码反查。
    """
    if kind != "em_board" or not label:
        return None
    text = str(label).strip()
    if not text:
        return None
    boards = _load_tdx_board_names()
    for tdx_code, name in boards.items():
        if name and (name == text or text in name or name in text):
            return tdx_code
    return None


# ---------------------------------------------------------------------------
# 统一出口(带缓存/退避/陈旧兜底)
# ---------------------------------------------------------------------------
def _key(kind: str, code: str) -> str:
    return f"{kind}:{str(code).strip().upper()}"


def _wrap_payload(kind: str, code: str, source: str, fetched: dict) -> dict:
    return {
        "kind": kind,
        "code": str(code).strip().upper(),
        "source": source,
        "trade_date": fetched.get("trade_date") or now_beijing().strftime("%Y-%m-%d"),
        "pre_close": fetched.get("pre_close"),
        "pre_close_approx": bool(fetched.get("pre_close_approx")),
        "fetched_at": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
        "stale": False,
        "points": fetched.get("points", []),
    }


def _fetch_primary(kind: str, code: str) -> dict:
    if kind == "tdx_board":
        return _fetch_tdx_board_trends(code)
    secid = _em_secid(kind, code)
    if not secid:
        raise ValueError(f"无法构造secid kind={kind} code={code}")
    return _fetch_em_trends(secid)


def get_benchmark_trends(kind: str, code: str, allow_stale: bool = True, label: Optional[str] = None) -> Optional[dict]:
    """取某基准的当日分钟分时。失败时按兜底链降级;全失败且缓存未超龄则返回 stale 副本。

    label(板块中文名)仅用于 em_board 主源失败时找通达信 880 孪生码。
    """
    if kind not in BENCH_KINDS:
        return None
    cache_key = _key(kind, code)
    now = now_beijing()

    with _trends_lock:
        cached = _trends_cache.get(cache_key)
        if cached and (now - cached[1]).total_seconds() < ARB_TRENDS_CACHE_TTL:
            return cached[0]
        blocked_until = _trends_retry_blocked_until.get(cache_key)
        if blocked_until is not None and now < blocked_until:
            if allow_stale and cached and (now - cached[1]).total_seconds() < ARB_TRENDS_STALE_MAX_SECONDS:
                stale_copy = dict(cached[0])
                stale_copy["stale"] = True
                return stale_copy
            return None

    payload: Optional[dict] = None
    try:
        if kind == "em_global":
            # KOSPI 单独走"新浪实时优先"链(内部不抛异常);None 视为整体失败进兜底
            payload = _fetch_kospi_trends()
            if payload is None:
                raise ValueError("KOSPI 新浪/东财两路均无今日数据")
        else:
            payload = _wrap_payload(kind, code, "tdx_board" if kind == "tdx_board" else "em_trends2", _fetch_primary(kind, code))
    except Exception as exc:
        logger.debug("基准分时主源失败 %s: %s", cache_key, exc)
        # 兜底链
        try:
            if kind == "em_board":
                twin = _tdx_twin_code(kind, label)
                if twin:
                    payload = _wrap_payload(kind, code, "tdx_board_fallback", _fetch_tdx_board_trends(twin))
            elif kind == "em_global":
                payload = KOSPI_ACCUMULATOR.snapshot()
                if payload is not None:
                    payload = dict(payload)
                    payload["stale"] = True
            elif kind == "em_index":
                payload = _wrap_payload(kind, code, "pytdx_fallback", _fetch_index_minutes_pytdx(code))
        except Exception as fallback_exc:
            logger.debug("基准分时兜底也失败 %s: %s", cache_key, fallback_exc)

    with _trends_lock:
        if payload is not None and payload.get("points"):
            _trends_cache[cache_key] = (payload, now_beijing())
            _trends_retry_blocked_until.pop(cache_key, None)
            return payload
        _trends_retry_blocked_until[cache_key] = now_beijing() + timedelta(seconds=45)
        cached = _trends_cache.get(cache_key)
        if allow_stale and cached and (now_beijing() - cached[1]).total_seconds() < ARB_TRENDS_STALE_MAX_SECONDS:
            stale_copy = dict(cached[0])
            stale_copy["stale"] = True
            return stale_copy
    return None
