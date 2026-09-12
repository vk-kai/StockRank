# -*- coding: utf-8 -*-
"""背离判定纯函数层(无 IO / 无时钟依赖,便于单测)。

输入是对齐后的分钟级累计涨跌幅%序列:
- S: 个股累计涨跌幅%
- B: 基准累计涨跌幅%

算法(参数由 config.ARB_* 提供):
1. 样本 < min_samples → warmup,不判定;
2. ρ = 近 corr_window 分钟增量的 pearson 相关,ρ < corr_min → decoupled(走势脱钩);
   ρ 只看折线形状,与涨跌幅大小无关(个股每分钟涨3倍于基准,ρ 依然=1)。
   逐分钟硬对齐会被分钟级抖动/个股慢一两拍打散(肉眼看明明吻合),故取
   max(原始口径, 平滑 corr_smooth_window 分钟口径) × 0/±1..±corr_max_lag 分钟错位
   里的最好值——原始口径保底,平滑+错位只解困不误杀;
3. β = 增量 Theil-Sen 稳健斜率(近 beta_window 样本,点对斜率的中位数),
   clamp [beta_min, beta_max]——OLS 会被一两根大K线拖偏,单笔大单/跳价
   不再扭曲"个股相对基准的弹性";必须用原始增量(平滑会压低共同波形幅度);
4. 价差 s = S − β·B,σ = 近 sigma_window 个 Δs 的 MAD 稳健口径
   (中位绝对偏差×1.4826,两三根跳变K线不会把"典型波动"撑大),
   近 drift_minutes 分钟漂移 z_s = Δs / (σ·√drift);
   漂移阈值优先与该对"今天自身"的历史同类漂移比分位(排除最近
   bench_mom_window 分钟——当前这波行情不参与自己的定标),当前漂移进入
   自身前 (1−drift_tail_q) 尾部才算异常;自身样本不足(开盘初期)退回
   σ 倍数(spread_k)口径——统一阈值对跳动的票太松、对安静的票太紧,
   自身分布自适应两头都解;
5. 基准动量 z_B = 近 bench_mom_window 分钟 B 变动 / (σ_B·√window),σ_B 同 MAD 口径;
6. 买点 = z_B ≥ +bench_mom_z 且 价差漂移过阈(自身尾部或 σ 倍数) 且
   基准窗口内真实涨幅 ≥ bench_mom_min_pct(基准涨、个股滞涨);卖点对称
   (基准跌、个股抗跌 + 最小真实跌幅门槛)。真实涨幅门槛用于防死水行情:
   波动极小时 z 值很容易过阈,但基准实际没怎么动,不提示。
reason 文案一律大白话(基准X分钟涨/跌了多少、个股跟没跟),不出现 β/ρ/σ/z 术语。
"""
from __future__ import annotations

import math
from typing import Optional


def align_series(stock_points: list[dict], bench_points: list[dict]) -> list[tuple]:
    """按 HH:MM 对齐个股与基准序列,基准前向填充。

    points 形如 [{"time": "09:31", "pct": 0.45}, ...];pct 为 None 的点跳过。
    KOSPI 早于 A 股开盘的场景下,基准 08:00 起的值会前向填充到个股 09:31 首点上。
    返回 [(time, stock_pct, bench_pct), ...] 按时间升序,只保留双方都有值的时刻。
    """
    bench_map = {str(p["time"]): p["pct"] for p in bench_points if p.get("pct") is not None}
    stock_map = {str(p["time"]): p["pct"] for p in stock_points if p.get("pct") is not None}
    if not bench_map or not stock_map:
        return []

    merged: list[tuple] = []
    last_bench: Optional[float] = None
    for hhmm in sorted(set(stock_map) | set(bench_map)):
        if hhmm in bench_map:
            last_bench = bench_map[hhmm]
        if hhmm in stock_map and last_bench is not None:
            merged.append((hhmm, stock_map[hhmm], last_bench))
    return merged


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    """皮尔逊相关;样本 < 3 或任一侧零方差返回 None。"""
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    mean_x = sum(xs[:n]) / n
    mean_y = sum(ys[:n]) / n
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for x, y in zip(xs[:n], ys[:n]):
        dx = x - mean_x
        dy = y - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _moving_average(values: list[float], window: int) -> list[float]:
    """居中滑动平均(window<=1 原样返回);ρ/β 计算前去分钟级毛刺,对齐肉眼看折线的尺度。"""
    n = len(values)
    if window <= 1 or n <= 1:
        return list(values)
    half = window // 2
    out: list[float] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        seg = values[lo:hi]
        out.append(sum(seg) / len(seg))
    return out


def _lagged_pearson(xs: list[float], ys: list[float], window: int, max_lag: int) -> tuple[Optional[float], int]:
    """在 0/±1..±max_lag 分钟错位里找最好的形态相关(lag>0 = 个股慢 lag 分钟)。

    个股恒定慢一两拍时折线形状其实吻合,逐分钟硬对齐会把 ρ 打到 0;
    取错位族里的最大值,任何一个小错位下形状对得上就算吻合。
    """
    best_r: Optional[float] = None
    best_lag = 0
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            a, b = xs[lag:], ys[: len(ys) - lag]
        elif lag < 0:
            a, b = xs[: len(xs) + lag], ys[-lag:]
        else:
            a, b = xs, ys
        if len(a) < 3:
            continue
        r = _pearson(a[-window:], b[-window:])
        if r is not None and (best_r is None or r > best_r):
            best_r = r
            best_lag = lag
    return best_r, best_lag


def _quantile(sorted_values: list[float], q: float) -> float:
    """最近邻秩分位数(输入需已升序);用于"自身历史波动分布"的尾部阈值。"""
    if not sorted_values:
        return 0.0
    k = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return float(sorted_values[k])


def _ols_slope(xs: list[float], ys: list[float]) -> Optional[float]:
    """普通最小二乘斜率(基准增量零方差时返回 None;也作 Theil-Sen 无有效点对时的兜底)。"""
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mean_x = sum(xs[:n]) / n
    mean_y = sum(ys[:n]) / n
    var_x = sum((x - mean_x) ** 2 for x in xs[:n])
    if var_x <= 0:
        return None
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    return cov / var_x


def _theil_sen_slope(xs: list[float], ys: list[float], max_points: int = 150) -> Optional[float]:
    """Theil-Sen 稳健斜率: 所有点对斜率的中位数。

    OLS 会被一两根大K线拖偏(窗内极少量异常点就能把斜率拉走),Theil-Sen
    要接近一半的点对变坏才会动——盘中单笔大单/跳价不再扭曲"个股相对基准
    的弹性"。超过 max_points 根时只取最近 max_points 根(纯为算力上限,
    默认 beta_window=90 远低于它)。
    """
    n = min(len(xs), len(ys))
    if n > max_points:
        xs, ys = xs[n - max_points:], ys[n - max_points:]
        n = max_points
    slopes: list[float] = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if dx == 0:
                continue
            slopes.append((ys[j] - ys[i]) / dx)
    if not slopes:
        return None
    slopes.sort()
    mid = len(slopes) // 2
    if len(slopes) % 2:
        return slopes[mid]
    return 0.5 * (slopes[mid - 1] + slopes[mid])


def _robust_sigma(values: list[float]) -> float:
    """MAD 稳健 σ: 中位绝对偏差 × 1.4826(正态下与标准差同尺度)。

    普通标准差被尾部拉高:两三根跳变K线就能把"典型波动"撑大一倍,后面的
    漂移 z 值全被压小、信号漏报。MAD 只看中间一半样本,跳变不参与定标。
    中位数/中位绝对偏差统一取下中位(sorted[(n-1)//2]):最近邻秩分位数在
    q=0.5 受 round-half-to-even 影响,窗口长度奇偶变化时 σ 会在 MAD 与 std
    两种口径间跳 3 倍,窗口逐分钟增长的上午尤其要命。
    退化保护: 超过半数样本完全相同(网格化报价/死水段)时 MAD=0,退回普通
    标准差(此时若真无波动仍为 0,由调用方走 flat 分支)。
    """
    if not values:
        return 0.0
    svals = sorted(values)
    med = svals[(len(svals) - 1) // 2]
    devs = sorted(abs(v - med) for v in values)
    mad = devs[(len(devs) - 1) // 2]
    if mad > 0:
        return 1.4826 * mad
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _snapshot_base(samples: int) -> dict:
    return {
        "status": "warmup",
        "samples": samples,
        "corr": None,
        "beta": None,
        "spread": None,
        "spread_sigma": None,
        "drift_z": None,
        "bench_mom_z": None,
        "corr_lag": None,
        "stock_pct": None,
        "bench_pct": None,
        "signal": None,
        "reason": "",
    }


def evaluate(
    aligned: list[tuple],
    *,
    corr_window: int = 15,
    corr_min: float = 0.5,
    beta_window: int = 90,
    beta_min: float = 0.2,
    beta_max: float = 5.0,
    sigma_window: int = 60,
    spread_k: float = 2.0,
    drift_minutes: int = 5,
    bench_mom_window: int = 15,
    bench_mom_z: float = 1.0,
    bench_mom_min_pct: float = 0.25,
    corr_smooth_window: int = 3,
    corr_max_lag: int = 2,
    min_samples: int = 25,
    drift_tail_q: float = 0.95,
    drift_tail_min_samples: int = 30,
) -> dict:
    """对齐序列 → 快照 dict(status/corr/beta/.../signal/reason)。"""
    n = len(aligned)
    snap = _snapshot_base(n)
    # 预热/异常分支也带上最新涨跌幅:面板"个股/基准"两格不再显示 --
    if n:
        snap["stock_pct"] = float(aligned[-1][1])
        snap["bench_pct"] = float(aligned[-1][2])
    if n < min_samples:
        snap["reason"] = f"开盘数据还不够({n}/{min_samples}分钟),再观察一会儿"
        return snap

    S = [float(p[1]) for p in aligned]
    B = [float(p[2]) for p in aligned]
    rS_raw = [S[i + 1] - S[i] for i in range(n - 1)]
    rB_raw = [B[i + 1] - B[i] for i in range(n - 1)]
    if len(rS_raw) < 3:
        snap["reason"] = "数据还在积累,预热中"
        return snap
    # 形态吻合度/β 用平滑后的增量: 只比折线形状,与涨跌幅大小无关;
    # 个股分钟级抖动/慢一拍在逐分钟对比下会误杀(肉眼明明吻合),平滑后按形状判。
    sS = _moving_average(S, corr_smooth_window)
    sB = _moving_average(B, corr_smooth_window)
    rS = [sS[i + 1] - sS[i] for i in range(n - 1)]
    rB = [sB[i + 1] - sB[i] for i in range(n - 1)]

    # 形态相关: 原始与平滑两种口径 × 0/±1..±corr_max_lag 分钟错位,取最好。
    # 原始口径保底(=旧行为): 平滑/错位只为抖动和慢一拍解困,
    # 取 max 保证只会比旧版更宽容,绝不会把原先吻合的判成脱钩。
    corr: Optional[float] = None
    corr_lag = 0
    candidates: list[tuple[float, int]] = []
    for xs, ys in ((rS_raw, rB_raw), (rS, rB)):
        r, lag = _lagged_pearson(xs, ys, corr_window, corr_max_lag)
        if r is not None:
            candidates.append((r, lag))
    # 长窗口形态相关(回看与 β 同尺度): 短窗会被"基准突然剧烈单边走"的几根
    # 增量自毒化——那恰是最该出信号的瞬间(基准大跌个股抗跌=卖点,反之=买点):
    # 短窗 ρ 被事件自己砸破门槛/个股零响应时 pearson 直接不可用 → 误判脱钩
    # 或 flat、信号被吞,且个股死活不跟就一直吞。长窗回答"这对组合近期是否
    # 稳定联动",瞬时背离交给漂移/动量门量化。同样取 max: 只放宽闸门不收紧;
    # 真正全天脱钩的对长窗照样低,仍被拦。
    long_win = max(corr_window, beta_window)
    r_long, lag_long = _lagged_pearson(rS_raw, rB_raw, long_win, corr_max_lag)
    if r_long is not None:
        candidates.append((r_long, lag_long))
    if candidates:
        corr, corr_lag = max(candidates)
        snap["corr"] = round(corr, 4)
        snap["corr_lag"] = corr_lag

    # β: 增量 Theil-Sen 稳健斜率,clamp(必须用原始增量——平滑会压低共同波形
    # 的幅度,斜率失真会连带价差/σ 全歪;平滑只服务于上面的脱钩闸门)。OLS 会被
    # 一两根大K线拖偏,单笔大单/跳价不再扭曲"个股相对基准的弹性";点对全退化
    # (基准增量全相同)时退回 OLS。
    seg_rS = rS_raw[-beta_window:]
    seg_rB = rB_raw[-beta_window:]
    n_seg = len(seg_rB)
    mean_rB = sum(seg_rB) / n_seg
    var_rB = sum((v - mean_rB) ** 2 for v in seg_rB)
    if var_rB <= 0:
        snap["status"] = "flat"
        d_flat = B[-1] - (B[-(beta_window + 1)] if n > beta_window else B[0])
        snap["reason"] = f"基准近{beta_window}分钟基本没动({d_flat:+.2f}%),没有可背离的行情,暂停判定"
        return snap
    raw_beta = _theil_sen_slope(seg_rB, seg_rS)
    if raw_beta is None:
        raw_beta = _ols_slope(seg_rB, seg_rS)
    if raw_beta is None:
        snap["status"] = "flat"
        snap["reason"] = "基准增量缺乏有效波动,算不出个股相对基准的弹性,暂停判定"
        return snap
    beta = max(beta_min, min(beta_max, raw_beta))
    snap["beta"] = round(beta, 4)

    # 价差与σ(MAD 稳健口径:跳变K线不撑大"典型波动",否则漂移 z 被压小漏报)
    spread_series = [S[i] - beta * B[i] for i in range(n)]
    delta_s = [spread_series[i + 1] - spread_series[i] for i in range(n - 1)]
    sigma = _robust_sigma(delta_s[-sigma_window:])
    snap["spread"] = round(spread_series[-1], 4)
    snap["spread_sigma"] = round(sigma, 6) if sigma > 0 else 0.0
    # 数值零门槛: 价差增量只剩浮点尾差(ulp 级)时 σ 可能为 1e-16 而非精确 0,
    # 直接用会让 z 值爆成 1e14 的垃圾——涨跌幅数据网格是 1e-4 量级,低于
    # 1e-12 一律视为完全同步。下游 z_b 同理。
    if sigma < 1e-12:
        snap["status"] = "flat"
        snap["reason"] = "个股与基准涨跌完全同步,没有差异可判,暂停判定"
        return snap

    # 开盘急速通道:样本还铺不满整窗时,漂移/动量窗口收缩到已有样本数
    # (下限3分钟保底统计意义),刚开盘样本一过 min_samples 就能判定,
    # 不用再等满 drift/bench_mom 整窗——开盘前几分正是套利背离最集中的时候
    drift_window = min(drift_minutes, max(3, n - 1))
    z_s: Optional[float] = None
    drift: Optional[float] = None
    # 非 None = 启用"该对今天自身波动分布"的尾部阈值(自适应口径);
    # None = 自身样本不足,退回 σ 倍数(spread_k)口径,即旧行为。
    tail_threshold: Optional[float] = None
    if n > drift_window:
        drift = spread_series[-1] - spread_series[-1 - drift_window]
        z_s = drift / (sigma * math.sqrt(drift_window))
        snap["drift_z"] = round(z_s, 3)
        # 自身分布定标: 收集今天(排除最近 max(bench_mom_window, drift_window)
        # 分钟——当前这波行情不参与自己的定标)的同类漂移幅度,当前漂移进入
        # 自身前 (1-drift_tail_q) 尾部才算异常。统一 σ 倍数阈值对跳动的票太松、
        # 对安静的票太紧,和自身比两头都解。
        hist_abs: list[float] = []
        hist_end = n - max(bench_mom_window, drift_window)
        for i in range(drift_window, hist_end):
            hist_abs.append(abs(spread_series[i] - spread_series[i - drift_window]))
        if len(hist_abs) >= drift_tail_min_samples:
            hist_abs.sort()
            threshold = _quantile(hist_abs, drift_tail_q)
            if threshold > 0:
                tail_threshold = threshold

    # 基准动量 z_B(σ_B 同 MAD 稳健口径,原始增量)
    sigma_b = _robust_sigma(rB_raw[-sigma_window:])
    mom_window = min(bench_mom_window, max(3, n - 1))
    z_b: Optional[float] = None
    d_bench = None
    if sigma_b >= 1e-12 and n > mom_window:
        d_bench = B[-1] - B[-1 - mom_window]
        z_b = d_bench / (sigma_b * math.sqrt(mom_window))
        snap["bench_mom_z"] = round(z_b, 3)

    if corr is None:
        snap["status"] = "flat"
        snap["reason"] = "吻合度算不出来(一边完全没波动),暂停判定"
        return snap
    if corr < corr_min:
        snap["status"] = "decoupled"
        # 带具体时间段和窗口内各自涨幅:直接看出"哪个时间段、各自走了多少、差在哪"
        win = aligned[-(corr_window + 1):] if n > corr_window else aligned
        d_s = S[-1] - float(win[0][1])
        d_b = B[-1] - float(win[0][2])
        snap["reason"] = (
            f"近{corr_window}分钟({win[0][0]}~{win[-1][0]})个股{d_s:+.2f}%、基准{d_b:+.2f}%,"
            f"两条折线的形态持续对不上(最好口径吻合度{corr:.2f},拉长到{long_win}分钟"
            f"也低于{corr_min:.2f}的门槛),暂停判定"
        )
        return snap

    snap["status"] = "ok"
    if z_s is None or z_b is None:
        snap["reason"] = "个股和基准联动正常,继续观察"
        return snap

    # 价差漂移过阈: 自身分布尾部优先(该对今天少见才算少见),样本不足用 σ 倍数
    if tail_threshold is not None:
        down_hit = drift is not None and drift <= -tail_threshold
        up_hit = drift is not None and drift >= tail_threshold
        tail_pct = max(1, int(round((1.0 - drift_tail_q) * 100)))
        tail_note = f",这个落差在今天它自身的波动里排前{tail_pct}%"
    else:
        down_hit = z_s <= -spread_k
        up_hit = z_s >= spread_k
        tail_note = ""

    d_stock = S[-1] - S[-1 - mom_window] if n > mom_window else None
    stock_leg = f"个股{d_stock:+.2f}%" if d_stock is not None else "个股"
    mom_hit_up = z_b >= bench_mom_z and down_hit
    mom_hit_down = z_b <= -bench_mom_z and up_hit

    if mom_hit_up and d_bench >= bench_mom_min_pct:
        snap["signal"] = "buy"
        snap["reason"] = (
            f"基准{mom_window}分钟涨了{abs(d_bench):.2f}%而{stock_leg}没跟上{tail_note},"
            f"个股偏慢 → 关注补涨(买点)"
        )
    elif mom_hit_down and d_bench <= -bench_mom_min_pct:
        snap["signal"] = "sell"
        snap["reason"] = (
            f"基准{mom_window}分钟跌了{abs(d_bench):.2f}%而{stock_leg}仍扛着没跌{tail_note},"
            f"个股偏慢 → 警惕补跌(卖点)"
        )
    elif mom_hit_up or mom_hit_down:
        snap["reason"] = f"基准{mom_window}分钟才动{d_bench:+.2f}%,幅度不够,继续观察"
    else:
        snap["reason"] = (
            f"基准{mom_window}分钟{d_bench:+.2f}%,{stock_leg},基本同步"
        )
    return snap
