# -*- coding: utf-8 -*-
"""套利背离监控引擎(由 main.arb_monitor_task 每 ARB_MONITOR_INTERVAL_SECONDS 秒驱动一次)。

职责:
- KOSPI 分钟曲线(新浪实时快照优先,东财全量曲线低频回填),供盘前提示用;
- 盘前(09:15-09:30): KOSPI 累计涨跌幅显著而个股竞价平开 → preopen 提示;
- 盘中(两个交易时段): 每对 个股×基准 → 背离判定 → 过冷却入库 → 返回新告警供 WS 广播;
- 维护 runtime 快照供 /api/market/arb/status。

tick 在 to_thread 里跑,用非阻塞锁防重入;单对失败不影响其余对。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from backend import config, db
from backend.arb import divergence
from backend.market import benchmark_data, intraday_series, pytdx_data
from backend.market.akshare_data import is_trading_date
from backend.time_utils import now_beijing

logger = logging.getLogger(__name__)

_TICK_LOCK = threading.Lock()

# 运行态(仅供 status API 读取,不落库)
runtime: dict = {
    "last_tick": None,
    "last_error": None,
    "monitor_enabled": None,
    "trading_day": None,
    "date": None,    # 当前处理日(跨日清空 pairs 快照用)
    "phase": "off",  # off|disabled|not_trading_day|preopen|session|idle
    "kospi_pct": None,
    "pairs": {},     # pair_id -> live snapshot
}
# 同对同向冷却: (pair_id, direction) -> aware datetime
_cooldown: dict = {}
# 盘外展示快照重建的节流: pair_id -> monotonic 秒(错误态自愈重试,避免每15s打一次数据源)
_display_retry_at: dict = {}
_DISPLAY_RETRY_SECONDS = 60


def _in_window(hhmm: str, window) -> bool:
    return str(window[0]) <= hhmm <= str(window[1])


def _in_sessions(hhmm: str, sessions) -> bool:
    return any(_in_window(hhmm, session) for session in sessions)


def _evaluate_kwargs() -> dict:
    return {
        "corr_window": config.ARB_CORR_WINDOW,
        "corr_min": config.ARB_CORR_MIN,
        "corr_smooth_window": config.ARB_CORR_SMOOTH_WINDOW,
        "corr_max_lag": config.ARB_CORR_MAX_LAG,
        "beta_window": config.ARB_BETA_WINDOW,
        "beta_min": config.ARB_BETA_MIN,
        "beta_max": config.ARB_BETA_MAX,
        "sigma_window": config.ARB_SIGMA_WINDOW,
        "spread_k": config.ARB_SPREAD_K,
        "drift_minutes": config.ARB_DRIFT_MINUTES,
        "drift_tail_q": config.ARB_DRIFT_TAIL_Q,
        "drift_tail_min_samples": config.ARB_DRIFT_TAIL_MIN_SAMPLES,
        "bench_mom_window": config.ARB_BENCH_MOM_WINDOW,
        "bench_mom_z": config.ARB_BENCH_MOM_Z,
        "bench_mom_min_pct": config.ARB_BENCH_MOM_MIN_PCT,
        "min_samples": config.ARB_MIN_OVERLAP_SAMPLES,
    }


def _pair_snapshot(pair: dict) -> dict:
    """某对的 live 快照骨架(状态灯/指标 chip 的数据源)。"""
    return {
        "pair_id": int(pair["id"]),
        "stock_code": pair.get("stock_code"),
        "stock_name": pair.get("stock_name"),
        "bench_kind": pair.get("bench_kind"),
        "bench_code": pair.get("bench_code"),
        "bench_label": pair.get("bench_label"),
        "enabled": bool(pair.get("enabled")),
        "preopen_enabled": bool(pair.get("preopen_enabled")),
        "status": "warmup",
        "signal": None,
        "reason": "等待首轮采样",
        "samples": 0,
        "corr": None,
        "beta": None,
        "spread": None,
        "spread_sigma": None,
        "drift_z": None,
        "bench_mom_z": None,
        "stock_pct": None,
        "bench_pct": None,
        "kospi_pct": None,
        "bench_source": None,
        "bench_stale": False,
        "error": None,
        "curve": [],  # [[HH:MM, 个股%, 基准%], ...] 卡片右侧迷你分时图
    }


def _compact_curve(aligned: list[tuple], max_points: int = 160) -> list[list]:
    """对齐分钟序列 → 迷你分时图数据 [[HH:MM, 个股%, 基准%], ...]。

    随快照经 /arb/status 下发(面板 30s 轮询刷新);超过 max_points 等距抽稀,
    永远保留最后一个点(右端=最新)。
    """
    if not aligned:
        return []

    def _pt(p) -> list:
        return [str(p[0]), round(float(p[1]), 3), round(float(p[2]), 3)]

    step = max(1, -(-len(aligned) // max_points))
    out = [_pt(p) for p in aligned[::step]]
    if out[-1][0] != str(aligned[-1][0]):
        out.append(_pt(aligned[-1]))
    return out


def _update_kospi_accumulator(now: datetime) -> None:
    """08:00-14:35 之间维护 KOSPI 分钟曲线(新浪实时优先、东财低频回填,见 benchmark_data)。"""
    hhmm = now.strftime("%H:%M")
    if not _in_window(hhmm, config.ARB_KOSPI_ACCUM_WINDOW):
        return
    try:
        benchmark_data.get_benchmark_trends("em_global", "KS11", allow_stale=False)
    except Exception as exc:
        logger.debug("KOSPI 曲线刷新失败: %s", exc)
    runtime["kospi_pct"] = benchmark_data.KOSPI_ACCUMULATOR.latest_pct()


def _stock_quotes_batch(codes: list) -> dict:
    """一轮一次批量查价(去重后单次 pytdx 请求)。

    盘前竞价价、盘中昨收都从这里取;逐对单码查价会把 pytdx 请求放大 N 倍
    (20 对 = 每 15 秒 20 次单码请求,批量后恒为 1 次)。
    """
    unique = sorted({str(c).strip().zfill(6) for c in codes if c})
    if not unique:
        return {}
    try:
        quotes = pytdx_data.get_realtime_quotes(unique)
    except Exception as exc:
        logger.debug("个股批量报价失败: %s", exc)
        return {}
    valid: dict = {}
    for q in quotes:
        try:
            price = float(q.get("price") or 0)
        except (TypeError, ValueError):
            continue
        # 集合竞价期 pytdx 可能给出 price=0 的报价(涨跌幅被算成 -100%),视同无报价:
        # 拿不到有效竞价就保留昨日展示,等有真实价格再开始
        if price <= 0:
            continue
        valid[q["code"]] = q
    return valid


# 昨日收盘涨跌幅缓存: code -> (计算日, 昨日全天涨跌幅%)
_prev_daily_pct_cache: dict[str, tuple[str, Optional[float]]] = {}


def _yesterday_close_pct(code: str, today: str) -> Optional[float]:
    """昨日全天涨跌幅%(昨日收盘 / 前日收盘),用于识别盘前拿到的"昨日收盘快照"。

    集合竞价期部分 pytdx 服务器的报价不是 price=0,而是上一交易日的收盘快照
    (price=昨收、change_pct=昨日全天涨跌幅),直接当今日竞价价会把昨天当成
    今天——面板显示错,个股"平开"判断失真还可能触发假盘前提示。昨日全天
    涨跌幅当天不变,按 (code, 日期) 缓存,每对每天至多多一次日线请求。
    """
    key = str(code or "").strip().zfill(6)
    if not key:
        return None
    cached = _prev_daily_pct_cache.get(key)
    if cached and cached[0] == today:
        return cached[1]
    pct: Optional[float] = None
    try:
        df = pytdx_data.get_kline(key, "daily", 3)
        by_date: dict[str, float] = {}
        if df is not None and not df.empty and "datetime" in df.columns:
            for _, row in df.iterrows():
                day = str(row.get("datetime", ""))[:10]
                try:
                    close = float(row.get("close") or 0)
                except (TypeError, ValueError):
                    continue
                if len(day) == 10 and day < today and close > 0:
                    by_date[day] = close
        days = sorted(by_date)
        if len(days) >= 2 and by_date[days[-2]] > 0:
            pct = round((by_date[days[-1]] / by_date[days[-2]] - 1) * 100, 2)
    except Exception as exc:
        logger.debug("昨日收盘涨跌幅获取失败 %s: %s", key, exc)
        return None  # 失败不缓存,下轮重试
    _prev_daily_pct_cache[key] = (today, pct)
    return pct


def _cooldown_ok(pair_id: int, direction: str, now: datetime) -> bool:
    last = _cooldown.get((pair_id, direction))
    if last is not None and (now - last).total_seconds() < config.ARB_ALERT_COOLDOWN_MINUTES * 60:
        return False
    return True


def _try_alert(pair: dict, snap: dict, direction: str, signal_time: str, trade_date: str,
               reason: str, now: datetime, stock_pct=None, bench_pct=None, beta=None,
               corr=None, spread_sigma=None) -> Optional[dict]:
    pair_id = int(pair["id"])
    if not _cooldown_ok(pair_id, direction, now):
        return None
    alert = db.insert_arb_alert(
        pair_id=pair_id,
        stock_code=pair.get("stock_code"),
        stock_name=pair.get("stock_name"),
        bench_kind=pair.get("bench_kind"),
        bench_code=pair.get("bench_code"),
        bench_label=pair.get("bench_label"),
        direction=direction,
        signal_time=signal_time,
        trade_date=trade_date,
        reason=reason,
        owner_username=pair.get("owner_username"),
        stock_pct=stock_pct,
        bench_pct=bench_pct,
        beta=beta,
        corr=corr,
        spread_sigma=spread_sigma,
    )
    if alert is not None:
        _cooldown[(pair_id, direction)] = now
    return alert


def _tick_preopen(pair: dict, snap: dict, now: datetime, hhmm: str, trade_date: str, quote_map: dict) -> Optional[dict]:
    """盘前 KOSPI 提示: KOSPI 累计涨跌超阈值 + 个股竞价平开 → 提示。signal_time 固定 09:15,每日至多一条。"""
    kospi_pct = runtime.get("kospi_pct")
    snap["kospi_pct"] = kospi_pct
    # 卡片"基准"格渲染的是 bench_pct:盘前基准就是 KOSPI,先填上,
    # 竞价报价不可用时面板也不至于把基准显示成 --
    snap["bench_pct"] = kospi_pct
    if kospi_pct is None:
        snap["status"] = "warmup"
        snap["reason"] = "KOSPI 早盘数据尚未累积"
        return None

    quote = quote_map.get(str(pair.get("stock_code") or "").strip().zfill(6))
    stock_pct = quote.get("change_pct") if quote else None
    if stock_pct is None:
        snap["status"] = "warmup"
        snap["reason"] = "个股竞价报价不可用"
        return None
    try:
        stock_pct = float(stock_pct)
    except (TypeError, ValueError):
        snap["status"] = "warmup"
        snap["reason"] = "个股竞价报价异常"
        return None

    # 集合竞价期 pytdx 可能回的是"昨日收盘快照"(price>0、change_pct=昨日全天涨跌幅),
    # 不是今日竞价价。涨跌幅与昨日全天涨跌幅一致(且价格确实≠昨收,排除真平开竞价)
    # 时视为旧快照:宁可显示"尚未就绪",也不能把昨天的数字当今天的竞价展示/判定。
    yesterday_pct = _yesterday_close_pct(pair.get("stock_code"), trade_date)
    if yesterday_pct is not None and abs(stock_pct - yesterday_pct) <= 0.05:
        same_price = False
        try:
            same_price = (
                quote.get("pre_close") is not None
                and abs(float(quote.get("price")) - float(quote.get("pre_close"))) < 1e-6
            )
        except (TypeError, ValueError):
            same_price = False
        if not same_price:
            snap["stock_pct"] = None
            snap["status"] = "warmup"
            snap["reason"] = "个股竞价报价尚未就绪(数据源仍是昨日收盘快照)"
            return None

    snap["stock_pct"] = stock_pct
    snap["status"] = "preopen"
    snap["reason"] = f"盘前观察:KOSPI {kospi_pct:+.2f}%,个股竞价 {stock_pct:+.2f}%"

    if abs(stock_pct) > config.ARB_PREOPEN_STOCK_FLAT_PCT:
        return None
    threshold = config.ARB_PREOPEN_KOSPI_PCT
    if kospi_pct >= threshold:
        snap["signal"] = "preopen_buy"
        snap["reason"] = (
            f"KOSPI 早盘累计 {kospi_pct:+.2f}%(≥{threshold}%)而个股竞价平开({stock_pct:+.2f}%)"
            f" → 盘前偏多提示"
        )
        return _try_alert(
            pair, snap, "preopen_buy", "09:15", trade_date, snap["reason"], now,
            stock_pct=stock_pct, bench_pct=kospi_pct,
        )
    if kospi_pct <= -threshold:
        snap["signal"] = "preopen_sell"
        snap["reason"] = (
            f"KOSPI 早盘累计 {kospi_pct:+.2f}%(≤-{threshold}%)而个股竞价平开({stock_pct:+.2f}%)"
            f" → 盘前偏空提示"
        )
        return _try_alert(
            pair, snap, "preopen_sell", "09:15", trade_date, snap["reason"], now,
            stock_pct=stock_pct, bench_pct=kospi_pct,
        )
    return None


def _pair_aligned_series(pair: dict, snap: dict, quote_map: dict, *,
                         require_today: bool = False, today: str = "") -> Optional[list[tuple]]:
    """公共取数段:基准分时 + 个股分钟 + 昨收归一 → 对齐序列。

    失败时把 error/reason 写进 snap 并返回 None;成功返回 aligned。
    盘中判定(require_today=True,必须双边都是今日数据,防止 09:30 刚开盘时
    拿"昨日整日曲线"判定背离)与盘外展示快照(require_today=False,刻意展示
    最后交易时段)共用。
    """
    bench = None
    try:
        bench = benchmark_data.get_benchmark_trends(
            pair.get("bench_kind"), pair.get("bench_code"), label=pair.get("bench_label")
        )
    except Exception as exc:
        logger.debug("基准分时获取失败 pair=%s: %s", pair.get("id"), exc)
    if not bench or not bench.get("points"):
        snap["status"] = "error"
        snap["error"] = "基准分时数据不可用"
        snap["reason"] = snap["error"]
        return None
    snap["bench_source"] = bench.get("source")
    snap["bench_stale"] = bool(bench.get("stale"))
    if require_today and str(bench.get("trade_date") or "") != today:
        snap["status"] = "warmup"
        snap["reason"] = f"基准分时仍是 {bench.get('trade_date') or '上一交易日'} 的数据,今日行情尚未开始"
        return None

    code = str(pair.get("stock_code") or "").strip().zfill(6)
    try:
        df = intraday_series.get_latest_session_minutes(code, 320, is_index=False)
    except Exception as exc:
        snap["status"] = "error"
        snap["error"] = f"个股分时获取失败: {exc}"
        snap["reason"] = snap["error"]
        return None
    if df is None or df.empty:
        snap["status"] = "warmup"
        snap["reason"] = "个股当日分钟线尚无数据"
        return None
    if require_today and "datetime" in df.columns:
        # get_latest_session_minutes 会顺延回上一个有数据的交易日,盘中判定必须拦住
        latest_day = str(df["datetime"].max())[:10]
        if latest_day != today:
            snap["status"] = "warmup"
            snap["reason"] = "个股当日分钟线尚未就绪"
            return None

    # 昨收: 实时报价优先,缺失时用当日首根开盘价近似
    quote = quote_map.get(code)
    pre_close = None
    if quote and quote.get("pre_close"):
        try:
            pre_close = float(quote["pre_close"])
        except (TypeError, ValueError):
            pre_close = None
    approx = pre_close is None
    if pre_close is None:
        # 当日首根 bar 近似昨收:开盘价优先,竞价期开盘价可能为 0 → 再试收盘价
        try:
            for candidate in (df.iloc[0]["open"], df.iloc[0]["close"]):
                try:
                    val = float(candidate)
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    pre_close = val
                    break
        except (IndexError, KeyError):
            pre_close = None
    if not pre_close or pre_close <= 0:
        snap["status"] = "error"
        snap["error"] = "个股昨收不可用,无法归一化"
        snap["reason"] = snap["error"]
        return None

    stock_points = intraday_series.minutes_to_pct_points(df, pre_close)
    snap["pre_close_approx"] = approx
    return divergence.align_series(stock_points, bench.get("points") or [])


def _tick_display(pair: dict, snap: dict, preopen: bool = False) -> None:
    """非交易时段(收盘后/午休/非交易日)的展示快照:重建最后交易时段的曲线+涨跌幅,不判定。

    仅在 runtime 里没有可保留的旧快照时调用(如进程在盘外重启)。
    preopen=True 时是盘前窗口里未开启盘前提示的对,文案相应区分。
    """
    snap["status"] = "off"
    snap["reason"] = (
        "盘前窗口:该对未开启盘前提示,显示最后交易时段状态"
        if preopen else "非交易时段,显示最后交易时段状态"
    )
    try:
        aligned = _pair_aligned_series(pair, snap, {})
    except Exception as exc:
        logger.debug("盘外展示快照重建失败 pair=%s: %s", pair.get("id"), exc)
        return
    if not aligned:
        return
    snap["curve"] = _compact_curve(aligned)
    snap["stock_pct"] = float(aligned[-1][1])
    snap["bench_pct"] = float(aligned[-1][2])


def _tick_intraday(pair: dict, snap: dict, now: datetime, hhmm: str, trade_date: str, quote_map: dict) -> Optional[dict]:
    """盘中背离判定。"""
    aligned = _pair_aligned_series(pair, snap, quote_map, require_today=True, today=trade_date)
    if aligned is None:
        return None
    snap["curve"] = _compact_curve(aligned)
    result = divergence.evaluate(aligned, **_evaluate_kwargs())

    keep = ("status", "samples", "corr", "beta", "spread", "spread_sigma", "drift_z",
            "bench_mom_z", "stock_pct", "bench_pct", "signal", "reason")
    for key in keep:
        if key in result:
            snap[key] = result[key]

    # 全球基准(如 KOSPI)北京时间 14:30 收盘:收盘后基准折线冻结,个股自己走
    # 会被误判成"形态对不上",而且基准不动也不存在新的套利机会 → 不再判定,
    # 只保留曲线/涨跌幅快照供查看。
    if str(pair.get("bench_kind") or "") == "em_global" and hhmm > config.ARB_GLOBAL_BENCH_CLOSE:
        snap["status"] = "flat"
        snap["signal"] = None
        snap["reason"] = (
            f"基准已收盘(KOSPI 北京时间 {config.ARB_GLOBAL_BENCH_CLOSE} 收盘),"
            "收盘后不存在套利机会,暂停判定"
        )
        return None

    if result.get("signal") in ("buy", "sell"):
        signal_time = now.strftime("%H:%M")
        return _try_alert(
            pair, snap, result["signal"], signal_time, trade_date, result.get("reason", ""), now,
            stock_pct=result.get("stock_pct"),
            bench_pct=result.get("bench_pct"),
            beta=result.get("beta"),
            corr=result.get("corr"),
            spread_sigma=result.get("spread_sigma"),
        )
    return None


def _run_tick_locked() -> list[dict]:
    now = now_beijing()
    runtime["last_tick"] = now.strftime("%Y-%m-%d %H:%M:%S")
    runtime["last_error"] = None

    settings = db.get_arb_settings()
    enabled = bool(settings.get("enabled"))
    runtime["monitor_enabled"] = enabled
    if not enabled:
        runtime["phase"] = "disabled"
        runtime["pairs"] = {}
        return []

    hhmm = now.strftime("%H:%M")
    in_window = _in_window(hhmm, config.ARB_MONITOR_WINDOW)
    today = now.strftime("%Y-%m-%d")

    # 跨日清理:上一交易日的运行态快照一律不继承。否则昨天盘前的"盘前观察"
    # 文案、昨天收盘后的"基准已收盘"状态会原样带到今天(面板看起来像今天的
    # 实时数据,实际全是昨天的数字)。
    if runtime.get("date") != today:
        runtime["date"] = today
        runtime["pairs"] = {}
        runtime["kospi_pct"] = None
        _display_retry_at.clear()

    trading: Optional[bool] = None
    if in_window:
        try:
            trading = bool(is_trading_date(now))
        except Exception:
            trading = now.weekday() < 5
    runtime["trading_day"] = trading

    preopen_phase = _in_window(hhmm, config.ARB_PREOPEN_WINDOW)
    session_phase = _in_sessions(hhmm, config.ARB_ALERT_SESSIONS)
    # 活跃 = 盘前或盘中交易时段(要判定/提示);其余(午休/收盘后/盘外/非交易日)只展示
    active = bool(trading) and (preopen_phase or session_phase)

    if not in_window:
        runtime["phase"] = "off"
    elif not trading:
        runtime["phase"] = "not_trading_day"
    elif preopen_phase:
        runtime["phase"] = "preopen"
    elif session_phase:
        runtime["phase"] = "session"
    else:
        runtime["phase"] = "idle"

    # 跨日清理冷却
    for key, ts in list(_cooldown.items()):
        if ts.strftime("%Y-%m-%d") != today:
            _cooldown.pop(key, None)

    if in_window:
        _update_kospi_accumulator(now)

    pairs = db.list_arb_pairs(enabled_only=True)
    # 全部配对一次性批量查价(盘前竞价价/盘中昨收共用,见 _stock_quotes_batch)
    quote_map = _stock_quotes_batch([p.get("stock_code") for p in pairs]) if active else {}
    prev_snapshots = runtime.get("pairs") or {}
    snapshots: dict = {}
    new_alerts: list[dict] = []
    for pair in pairs:
        pair_id = int(pair["id"])
        prev = prev_snapshots.get(pair_id)
        # 盘前提示按对开关: preopen_enabled=0 的对在盘前窗口按非活跃处理
        # (保留最后快照/节流重建,不判定不推送);盘中判定不受它影响。
        pair_active = active and not (preopen_phase and not bool(pair.get("preopen_enabled")))
        if not pair_active:
            # 非交易时段(收盘后/午休/盘前等待)不清空数据:保留最后一刻的完整快照
            # (曲线/涨跌幅/判定状态);旧快照缺失或为错误态(如数据源瞬断时冻结的
            # "不可用"文案)时节流重建,自愈成"最后交易时段"的展示快照。
            if prev is not None and prev.get("status") != "error":
                if preopen_phase and prev.get("status") == "off":
                    # 盘前窗口里沿用的昨收展示快照,文案要说明是盘前等待,避免误读成实时
                    prev["reason"] = "盘前窗口:该对未开启盘前提示,显示最后交易时段状态"
                snapshots[pair_id] = prev
                continue
            now_s = time.monotonic()
            if now_s - _display_retry_at.get(pair_id, 0.0) >= _DISPLAY_RETRY_SECONDS:
                _display_retry_at[pair_id] = now_s
                snap = _pair_snapshot(pair)
                _tick_display(pair, snap, preopen=preopen_phase)
            else:
                snap = prev if prev is not None else _pair_snapshot(pair)
            snapshots[pair_id] = snap
            continue
        snap = _pair_snapshot(pair)
        snapshots[pair_id] = snap
        try:
            if preopen_phase:
                alert = _tick_preopen(pair, snap, now, hhmm, today, quote_map)
            else:
                alert = _tick_intraday(pair, snap, now, hhmm, today, quote_map)
            if alert is not None:
                new_alerts.append(alert)
        except Exception as exc:
            snap["status"] = "error"
            snap["error"] = str(exc)
            snap["reason"] = f"监控异常: {exc}"
            logger.warning("套利监控单对异常 pair=%s: %s", pair.get("id"), exc)
        # 竞价无有效报价/当日分钟线尚未就绪 → 不拿空白或 0 价脏数据覆盖,
        # 继续展示上一份"今天真实判定过"的快照(ok/flat/decoupled,曲线是今天的);
        # 昨收展示快照(off)和盘前快照(preopen)一律不回填——盘前拿不到竞价就
        # 坦诚显示"尚未就绪",绝不能把昨天的曲线/涨跌幅当成今天的盘前观察。
        prefer_prev = bool(
            prev and prev.get("curve") and not snap.get("curve")
            and prev.get("status") in ("ok", "flat", "decoupled")
            and (snap.get("status") == "warmup" or (preopen_phase and snap.get("status") == "error"))
        )
        if prefer_prev:
            snapshots[pair_id] = prev
    runtime["pairs"] = snapshots

    if new_alerts:
        logger.info("套利背离新告警 %d 条", len(new_alerts))
    return new_alerts


def run_arb_tick() -> list[dict]:
    """一轮监控;返回新告警列表(供 WS 广播)。非阻塞防重入。"""
    if not _TICK_LOCK.acquire(blocking=False):
        return []
    try:
        return _run_tick_locked()
    except Exception as exc:
        runtime["last_error"] = str(exc)
        logger.exception("套利监控 tick 异常: %s", exc)
        return []
    finally:
        _TICK_LOCK.release()


def get_runtime_status() -> dict:
    """status API 的运行态视图。"""
    return {
        "enabled": runtime.get("monitor_enabled"),
        "phase": runtime.get("phase"),
        "trading_day": runtime.get("trading_day"),
        "last_tick": runtime.get("last_tick"),
        "last_error": runtime.get("last_error"),
        "kospi_pct": runtime.get("kospi_pct"),
        "interval_seconds": config.ARB_MONITOR_INTERVAL_SECONDS,
        "pairs": list((runtime.get("pairs") or {}).values()),
    }
