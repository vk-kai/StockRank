from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class MacdAreaSegment:
    sign: int
    start: int
    end: int
    area: float


class MACDChanClassicSignals:
    def __init__(self):
        self.fast = 12
        self.slow = 26
        self.signal = 9
        self.zero_axis_pullback_pct = 0.015
        self.sell_cross_gap_pct = 0.0015
        self.min_hist = 1e-6

    def _sign(self, value: float, fallback: int = 0) -> int:
        if pd.isna(value):
            return fallback
        if value > self.min_hist:
            return 1
        if value < -self.min_hist:
            return -1
        return fallback

    def _cross_gap(self, dif_value: float, dea_value: float) -> float:
        return dif_value - dea_value

    def _just_dead_cross(self, dif_values: pd.Series, dea_values: pd.Series, i: int) -> bool:
        if i < 1:
            return False
        return dif_values.iloc[i - 1] >= dea_values.iloc[i - 1] and dif_values.iloc[i] < dea_values.iloc[i]

    def _near_dead_cross(self, dif_values: pd.Series, dea_values: pd.Series, i: int, price: float) -> bool:
        if i < 2:
            return False
        threshold = max(abs(price) * self.sell_cross_gap_pct, 0.0005)
        gaps = []
        for idx in range(i - 2, i + 1):
            dv = dif_values.iloc[idx]
            ev = dea_values.iloc[idx]
            if pd.isna(dv) or pd.isna(ev):
                return False
            gaps.append(self._cross_gap(dv, ev))
        g2, g1, g0 = gaps
        shrinking = g2 > g1 > g0 + self.min_hist
        crossing_now = self._just_dead_cross(dif_values, dea_values, i)
        direction_ok = (g0 >= 0 and dif_values.iloc[i] >= dea_values.iloc[i]) or (crossing_now and abs(g0) <= threshold)
        return shrinking and abs(g0) <= threshold and direction_ok

    def _segment_lines_all_above_zero(self, dif_values: pd.Series, dea_values: pd.Series, s: int, e: int) -> bool:
        if s < 0 or e < s:
            return False
        has = False
        for idx in range(s, e + 1):
            dv = dif_values.iloc[idx]
            ev = dea_values.iloc[idx]
            if pd.isna(dv) or pd.isna(ev):
                continue
            has = True
            if dv <= 0 or ev <= 0:
                return False
        return has

    def _segment_pullback_to_zero_ok(self, dif_values: pd.Series, dea_values: pd.Series, s: int, e: int, price: float) -> bool:
        if s < 0 or e < s:
            return False
        vals = []
        mags = []
        for idx in range(s, e + 1):
            dv = dif_values.iloc[idx]
            ev = dea_values.iloc[idx]
            if pd.isna(dv) or pd.isna(ev):
                continue
            vals.append((dv, ev))
            mags.append(max(abs(dv), abs(ev)))
        if len(mags) < 2:
            return False
        threshold = max(abs(price) * self.zero_axis_pullback_pct, 0.0045)
        sd, se = vals[0]
        start_abs = mags[0]
        end_abs = mags[-1]
        min_abs = min(mags)
        near_zero = min_abs <= threshold
        return sd > 0 and se > 0 and near_zero and end_abs < start_abs - self.min_hist and min_abs < start_abs - self.min_hist

    def reasons_for_df(self, df: pd.DataFrame) -> List[Optional[str]]:
        if df is None or len(df) == 0 or "close" not in df.columns:
            return []
        close = pd.to_numeric(df["close"], errors="coerce")
        dif = close.ewm(span=self.fast, adjust=False).mean() - close.ewm(span=self.slow, adjust=False).mean()
        dea = dif.ewm(span=self.signal, adjust=False).mean()
        hist = (dif - dea) * 2
        reasons: List[Optional[str]] = [None] * len(df)
        segments: List[MacdAreaSegment] = []
        cur_sign = 0
        cur_start = -1
        cur_area = 0.0
        warmup = self.slow + self.signal
        for i in range(len(df)):
            price = close.iloc[i]
            dv = dif.iloc[i]
            ev = dea.iloc[i]
            hv = hist.iloc[i]
            if any(pd.isna(v) for v in (price, dv, ev, hv)):
                continue
            sign = self._sign(hv, cur_sign)
            if cur_sign == 0:
                cur_sign = sign
                cur_start = i
                cur_area = abs(hv)
            elif sign != cur_sign:
                if cur_sign != 0 and cur_start >= 0 and i - 1 >= cur_start:
                    segments.append(MacdAreaSegment(sign=cur_sign, start=cur_start, end=i - 1, area=float(cur_area)))
                cur_sign = sign
                cur_start = i
                cur_area = abs(hv)
            else:
                cur_area += abs(hv)
            if i < warmup or len(segments) < 2 or cur_sign == 0:
                continue
            first = segments[-2]
            middle = segments[-1]
            current = MacdAreaSegment(sign=cur_sign, start=cur_start, end=i, area=float(cur_area))
            is_sell = first.sign == 1 and middle.sign == -1 and current.sign == 1
            if not is_sell:
                continue
            first_above = self._segment_lines_all_above_zero(dif, dea, first.start, first.end)
            middle_above = self._segment_lines_all_above_zero(dif, dea, middle.start, middle.end)
            pullback_required = first_above and middle_above
            pullback_ok = (not pullback_required) or self._segment_pullback_to_zero_ok(dif, dea, middle.start, middle.end, price)
            if pullback_ok and current.area < first.area and self._near_dead_cross(dif, dea, i, price):
                suffix = "第一段红柱和中间绿柱都运行在0轴上方，中间绿柱已完成回抽0轴，" if pullback_required else ""
                reasons[i] = (
                    "当前K线同时命中MACD红绿红经典卖点过滤："
                    f"第二片红柱面积={current.area:.5f} < 第一片红柱面积={first.area:.5f}，"
                    f"{suffix}DIF/DEA间距持续收敛并向下开始死叉"
                )
        return reasons
