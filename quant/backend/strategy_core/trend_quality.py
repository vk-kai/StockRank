"""MACD 买点「趋势质量」评分: 把"强趋势首次回调 vs 下跌中继"的盘感拆成可计算变量。

背景(2026-09-16): 同样满足"MACD非背驰回抽零轴"买点的两只票,一只是强主升后
浅回调洗盘再起(中石科技 41→106→81→B),另一只是主升乏力后高位阶梯下跌的
下跌中继(东方盛虹 11.26→15.08→阶梯回落→B)。肉眼区分的依据并不是 MACD
本身,而是: 前期主升质量 + 回调深度 + 高低点结构 + 回调时长 + 量价关系 +
长期均线状态。本模块把这些"盘感"量化成评分,供策略在买点处调用。

评分项(总分100,缺数据的项按可得满分折算,避免数据缺失变相扣分):
- 回撤深度 30分: 本次回调吃掉前面主升段的比例,越浅越健康
- 高低点结构 25分: 自峰顶以来依次降低的反弹高点数(LH),越多越接近下跌中继
- 均线状态 15分: MA20/MA60 斜率向上 + 收盘站上 MA20
- 回调时长 10分: 回调根数/主升段根数,拖太久说明卖压在持续释放
- 量价结构 15分: 回调均量/主升均量(缩量健康) + 回调中下跌K线量/上涨K线量
- 趋势余量 5分: 收盘距 MA60 的 ATR 距离,越远说明长期趋势优势消耗越少

一票否决(直接 C 级,标注"下跌中继风险"):
- 回撤 ≥ 61.8%: 主升段被大幅吞没
- LH ≥ 4: 下降阶梯结构已经成形

各阈值是 V1 经验值,应基于全市场历史信号回测(信号后 5/10/20 日收益)再校准。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

_ATR_PERIOD = 20
_MA_SLOPE_LOOKBACK = 5
# 判定"降低高点"的相对容差(0.01%),过滤浮点噪声/绝对等高
_PIVOT_EPS = 1e-4


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window).mean().to_numpy()


def _pivot_highs(high: np.ndarray, start: int, end: int) -> list[float]:
    """(start, end) 开区间内的局部反弹高点(与左右相邻K线比较)。"""
    pivots: list[float] = []
    for j in range(start + 1, end):
        if np.isnan(high[j]) or np.isnan(high[j - 1]) or np.isnan(high[j + 1]):
            continue
        if high[j] > high[j - 1] and high[j] >= high[j + 1]:
            pivots.append(float(high[j]))
    return pivots


def _lower_high_count(pivots: list[float]) -> int:
    """从第一个反弹高点起,连续降低的高点个数(遇到升高即停,视为结构修复)。"""
    count = 0
    prev: Optional[float] = None
    for p in pivots:
        if prev is None or p < prev * (1 - _PIVOT_EPS):
            count += 1
            prev = p
        else:
            break
    return count


def compute_pullback_quality(
    df: pd.DataFrame,
    *,
    impulse_start: int,
    peak_idx: int,
    signal_idx: int,
) -> Optional[dict]:
    """计算回抽零轴买点处的趋势质量。

    参数:
        df: 原始K线(open/high/low/close 必需, volume/vol 可选)
        impulse_start: 主升段起点(第一片红柱起始索引,低点从这段找)
        peak_idx: 非背驰红柱顶点索引(最高价所在K线)
        signal_idx: 买点所在K线索引
    返回: 质量报告 dict(score/grade/metrics/summary/...),数据不足时返回 None
    """
    try:
        if df is None or len(df) == 0:
            return None
        n = len(df)
        if not (0 <= impulse_start < peak_idx < signal_idx < n):
            return None
        if signal_idx - peak_idx < 1:
            return None

        high = pd.to_numeric(df["high"], errors="coerce").to_numpy(dtype=float)
        low = pd.to_numeric(df["low"], errors="coerce").to_numpy(dtype=float)
        close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float)
        if np.isnan(close[signal_idx]) or np.isnan(high[peak_idx]):
            return None

        # ---- 主升段: 起点低点 → 峰顶 ----
        trough_slice = low[impulse_start : peak_idx + 1]
        if np.all(np.isnan(trough_slice)):
            return None
        trough_idx = impulse_start + int(np.nanargmin(trough_slice))
        trough = float(low[trough_idx])
        peak = float(high[peak_idx])
        if not np.isfinite(trough) or not np.isfinite(peak) or trough <= 0 or peak <= trough:
            return None

        # ---- ATR(峰值处, 20期TR均值; 样本不足一半周期则放弃) ----
        atr: Optional[float] = None
        atr_start = max(1, peak_idx - _ATR_PERIOD + 1)
        if peak_idx >= atr_start:
            pc = close[atr_start - 1 : peak_idx]
            h = high[atr_start : peak_idx + 1]
            l = low[atr_start : peak_idx + 1]
            with np.errstate(invalid="ignore"):
                tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
            tr = tr[np.isfinite(tr)]
            if len(tr) >= max(5, _ATR_PERIOD // 2):
                mean_tr = float(np.mean(tr))
                if mean_tr > 0:
                    atr = mean_tr

        impulse_pct = (peak - trough) / trough * 100.0
        impulse_atr = (peak - trough) / atr if atr else None

        # ---- 回调段: 峰顶 → 买点 ----
        pb_slice = low[peak_idx : signal_idx + 1]
        if np.all(np.isnan(pb_slice)):
            return None
        pb_low_idx = peak_idx + int(np.nanargmin(pb_slice))
        pb_low = float(low[pb_low_idx])
        retracement: Optional[float] = None
        if np.isfinite(pb_low):
            retracement = max(0.0, (peak - pb_low) / (peak - trough) * 100.0)

        pullback_bars = signal_idx - peak_idx
        impulse_bars = peak_idx - trough_idx
        duration_ratio = pullback_bars / max(impulse_bars, 1)

        pivots = _pivot_highs(high, peak_idx, signal_idx)
        lh_count = _lower_high_count(pivots)

        # ---- 均线状态 ----
        ma20 = _rolling_mean(close, 20)
        ma60 = _rolling_mean(close, 60)

        def _slope_up(ma: np.ndarray) -> Optional[bool]:
            a = ma[signal_idx]
            b = ma[signal_idx - _MA_SLOPE_LOOKBACK]
            if np.isnan(a) or np.isnan(b):
                return None
            return bool(a > b)

        ma20_up = _slope_up(ma20)
        ma60_up = _slope_up(ma60)
        close_above_ma20: Optional[bool] = None
        if not np.isnan(ma20[signal_idx]):
            close_above_ma20 = bool(close[signal_idx] > ma20[signal_idx])

        dist_ma60_atr: Optional[float] = None
        if atr and not np.isnan(ma60[signal_idx]):
            dist_ma60_atr = (float(close[signal_idx]) - float(ma60[signal_idx])) / atr

        # ---- 量价(volume/vol 可选) ----
        vol_col = None
        if "volume" in df.columns:
            vol_col = "volume"
        elif "vol" in df.columns:
            vol_col = "vol"
        pullback_vol_ratio: Optional[float] = None
        down_up_vol_ratio: Optional[float] = None
        if vol_col:
            vol = pd.to_numeric(df[vol_col], errors="coerce").to_numpy(dtype=float)
            imp_vols = vol[trough_idx : peak_idx + 1]
            pb_vols = vol[peak_idx + 1 : signal_idx + 1]
            imp_vols = imp_vols[np.isfinite(imp_vols) & (imp_vols > 0)]
            pb_vols = pb_vols[np.isfinite(pb_vols) & (pb_vols > 0)]
            if len(imp_vols) and len(pb_vols):
                imp_mean = float(np.mean(imp_vols))
                if imp_mean > 0:
                    pullback_vol_ratio = float(np.mean(pb_vols)) / imp_mean
            down_vols: list[float] = []
            up_vols: list[float] = []
            for j in range(peak_idx + 1, signal_idx + 1):
                c0, c1, v = close[j - 1], close[j], vol[j]
                if np.isnan(c0) or np.isnan(c1) or np.isnan(v) or v <= 0:
                    continue
                if c1 < c0:
                    down_vols.append(float(v))
                elif c1 > c0:
                    up_vols.append(float(v))
            if down_vols and up_vols:
                down_up_vol_ratio = float(np.mean(down_vols)) / float(np.mean(up_vols))

        # ================= 评分 =================
        items: list[tuple[float, float]] = []  # (得分, 满分)
        warnings: list[str] = []
        hard_fails: list[str] = []

        # 1) 回撤深度 30
        if retracement is not None:
            if retracement >= 61.8:
                items.append((0.0, 30.0))
                hard_fails.append(f"回撤{retracement:.0f}%≥61.8%")
            elif retracement >= 50.0:
                items.append((12.0, 30.0))
            elif retracement >= 38.2:
                items.append((22.0, 30.0))
            else:
                items.append((30.0, 30.0))

        # 2) 高低点结构 25
        if lh_count >= 4:
            items.append((0.0, 25.0))
            hard_fails.append(f"连续{lh_count}个降低高点")
        elif lh_count == 3:
            items.append((8.0, 25.0))
        elif lh_count == 2:
            items.append((18.0, 25.0))
        else:
            items.append((25.0, 25.0))

        # 3) 均线状态 15
        ma_earned = ma_max = 0.0
        if ma20_up is not None:
            ma_max += 6
            if ma20_up:
                ma_earned += 6
            else:
                warnings.append("MA20拐头向下")
        if ma60_up is not None:
            ma_max += 5
            if ma60_up:
                ma_earned += 5
        if close_above_ma20 is not None:
            ma_max += 4
            if close_above_ma20:
                ma_earned += 4
        if ma_max > 0:
            items.append((ma_earned, ma_max))

        # 4) 回调时长 10
        if duration_ratio is not None:
            if duration_ratio <= 0.5:
                items.append((10.0, 10.0))
            elif duration_ratio <= 1.0:
                items.append((6.0, 10.0))
            elif duration_ratio <= 1.6:
                items.append((3.0, 10.0))
            else:
                items.append((0.0, 10.0))
                warnings.append("回调时间超过主升段时间")

        # 5) 量价结构 15
        vol_earned = vol_max = 0.0
        if pullback_vol_ratio is not None:
            vol_max += 8
            if pullback_vol_ratio < 0.65:
                vol_earned += 8
            elif pullback_vol_ratio < 0.85:
                vol_earned += 5
            elif pullback_vol_ratio < 1.05:
                vol_earned += 2
            else:
                warnings.append("回调未缩量")
        if down_up_vol_ratio is not None:
            vol_max += 7
            if down_up_vol_ratio < 0.8:
                vol_earned += 7
            elif down_up_vol_ratio < 1.0:
                vol_earned += 4
        if vol_max > 0:
            items.append((vol_earned, vol_max))

        # 6) 趋势余量 5
        if dist_ma60_atr is not None:
            if dist_ma60_atr >= 2:
                items.append((5.0, 5.0))
            elif dist_ma60_atr >= 0.5:
                items.append((3.0, 5.0))
            else:
                items.append((0.0, 5.0))
                if dist_ma60_atr < 0:
                    warnings.append("收盘在MA60下方")

        total_earned = sum(e for e, _ in items)
        total_max = sum(m for _, m in items)
        score = round(total_earned / total_max * 100.0) if total_max > 0 else 0

        if hard_fails:
            grade = "C"
        elif score >= 75:
            grade = "A"
        elif score >= 55:
            grade = "B"
        else:
            grade = "C"

        # ---- 单行摘要(进 reason,扫描卡片hover/回测交易记录/信号诊断通用) ----
        head = f"质量{score}分({grade}级)"
        if grade == "C" and hard_fails:
            head += "⚠下跌中继风险"
        detail = [f"主升+{impulse_pct:.0f}%"]
        if impulse_atr:
            detail.append(f"{impulse_atr:.1f}ATR")
        if retracement is not None:
            detail.append(f"回撤{retracement:.0f}%")
        detail.append(f"LH{lh_count}")
        if duration_ratio is not None:
            detail.append(f"时长比{duration_ratio:.2f}")
        if pullback_vol_ratio is not None:
            detail.append(f"量比{pullback_vol_ratio:.2f}")
        ma_txt = ""
        if ma20_up is not None:
            ma_txt += "MA20↑" if ma20_up else "MA20↓"
        if ma60_up is not None:
            ma_txt += "MA60↑" if ma60_up else "MA60↓"
        if ma_txt:
            detail.append(ma_txt)
        summary = head + "｜" + " ".join(detail)
        if warnings:
            summary += " ⚠" + "/".join(warnings)

        return {
            "score": score,
            "grade": grade,
            "hard_fails": hard_fails,
            "warnings": warnings,
            "summary": summary,
            "metrics": {
                "impulse_pct": round(impulse_pct, 2),
                "impulse_atr": round(impulse_atr, 2) if impulse_atr else None,
                "retracement_pct": round(retracement, 2) if retracement is not None else None,
                "pullback_bars": pullback_bars,
                "impulse_bars": impulse_bars,
                "duration_ratio": round(duration_ratio, 3) if duration_ratio is not None else None,
                "lower_high_count": lh_count,
                "pullback_vol_ratio": round(pullback_vol_ratio, 3) if pullback_vol_ratio is not None else None,
                "down_up_vol_ratio": round(down_up_vol_ratio, 3) if down_up_vol_ratio is not None else None,
                "ma20_up": ma20_up,
                "ma60_up": ma60_up,
                "close_above_ma20": close_above_ma20,
                "dist_ma60_atr": round(dist_ma60_atr, 2) if dist_ma60_atr is not None else None,
            },
        }
    except Exception:
        # 评分是锦上添花,任何异常都不能影响买点本身
        return None
