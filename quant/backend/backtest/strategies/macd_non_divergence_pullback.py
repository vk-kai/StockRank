"""MACD 非背驰回抽0轴策略

策略逻辑：
1. 红柱非背驰向上：连续两片红柱，第二片面积 > 第一片面积，且股价突破第一片红柱对应最高价
2. 0轴要求：非背驰向上到达顶点时，黄白线(DIF/DEA)都在0轴以上
3. 小面积绿柱回调：回调时绿柱面积 < 非背驰红柱面积，且黄白线在0轴以上
4. 回调期间股价走势要求下上下结构：先下跌找第一个低点，再反弹，再下跌到第二个低点时买入
5. 买点：下上下结构形成后，黄白线在0轴之上，绿柱开始缩短，且布林通道收口时买入
6. 止损卖出：
   - 零轴止损：黄白线(DIF和DEA)都跌破0轴时立即卖出
   - 背驰卖点：红柱背驰（第二片红面积 < 非背驰红面积且接近死叉）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .base import BacktestSignal, BaseBacktestStrategy
from backend import config as backend_config
from backend.strategy_core.trend_quality import compute_pullback_quality
from backend.time_utils import format_beijing_time


@dataclass
class _MacdSegment:
    sign: int       # +1=红柱, -1=绿柱
    start: int      # 起始K线索引
    end: int        # 结束K线索引
    area: float     # 面积（该段所有|hist|之和）
    low_min: float  # 该段K线最低价
    high_max: float # 该段K线最高价


class MACDNonDivergencePullbackBacktestStrategy(BaseBacktestStrategy):
    name = "MACD_NON_DIVERGENCE_PULLBACK"
    description = "MACD 非背驰回抽0轴策略"
    min_bars = 60

    def __init__(self):
        self.fast = 12
        self.slow = 26
        self.signal = 9
        self.min_hist = 1e-6
        self.zero_axis_pct = 0.01        # 判定"在0轴上"的阈值
        self.boll_period = 20            # 布林通道周期
        self.boll_nbdev = 2              # 布林通道标准差倍数
        self.boll_contraction_lookback = 3  # 布林收口检查的K线数量

    def _sign(self, value: float, fallback: int = 0) -> int:
        if np.isnan(value):
            return fallback
        if value > self.min_hist:
            return 1
        if value < -self.min_hist:
            return -1
        return fallback

    def _format_time(self, value) -> str:
        if isinstance(value, str):
            return value
        return format_beijing_time(value, "%Y-%m-%d %H:%M")

    def _segment_lines_all_above_zero(
        self,
        dif_values: np.ndarray,
        dea_values: np.ndarray,
        segment_start: int,
        segment_end: int,
    ) -> bool:
        """判断整段内DIF和DEA是否始终在0轴上方"""
        if segment_start < 0 or segment_end < segment_start:
            return False
        has_value = False
        for idx in range(segment_start, segment_end + 1):
            dif_value = dif_values[idx]
            dea_value = dea_values[idx]
            if np.isnan(dif_value) or np.isnan(dea_value):
                continue
            has_value = True
            if dif_value <= 0 or dea_value <= 0:
                return False
        return has_value

    def _lines_above_zero(self, dif_value: float, dea_value: float) -> bool:
        """判断当前DIF/DEA是否都在0轴上方"""
        if np.isnan(dif_value) or np.isnan(dea_value):
            return False
        return dif_value > 0 and dea_value > 0

    def _boll_contraction(
        self,
        boll_upper: np.ndarray,
        boll_lower: np.ndarray,
        current_index: int,
    ) -> bool:
        """判断布林通道是否收口（上下轨逐渐靠近）

        检查最近 lookback 根K线的布林带宽是否持续缩小
        """
        lookback = self.boll_contraction_lookback
        if current_index < lookback:
            return False

        # 计算布林带宽（上轨-下轨）
        widths = []
        for idx in range(current_index - lookback, current_index + 1):
            upper = boll_upper[idx]
            lower = boll_lower[idx]
            if np.isnan(upper) or np.isnan(lower):
                return False
            widths.append(upper - lower)

        # 判断带宽是否持续缩小：每根K线的带宽都比前一根小或相等
        for j in range(1, len(widths)):
            if widths[j] > widths[j - 1]:
                return False

        return True

    def _near_dead_cross(
        self,
        dif_values: np.ndarray,
        dea_values: np.ndarray,
        current_index: int,
        price: float,
    ) -> bool:
        """判断是否接近死叉（DIF/DEA间距持续收敛并向下）"""
        if current_index < 2:
            return False
        threshold = max(abs(price) * 0.0015, 0.0005)
        recent_gaps = []
        for idx in range(max(0, current_index - 2), current_index + 1):
            dif_value = dif_values[idx]
            dea_value = dea_values[idx]
            if np.isnan(dif_value) or np.isnan(dea_value):
                return False
            recent_gaps.append(dif_value - dea_value)

        if len(recent_gaps) < 3:
            return False

        prev_gap_2, prev_gap_1, current_gap = recent_gaps[-3:]
        # 间距持续缩小
        shrinking = abs(prev_gap_2) > abs(prev_gap_1) + self.min_hist and abs(prev_gap_1) > abs(current_gap) + self.min_hist
        # 当前DIF >= DEA 且差距很小（接近死叉）
        approaching = dif_values[current_index] >= dea_values[current_index] and abs(current_gap) <= threshold
        return shrinking and approaching

    def _just_crossed_dead(
        self, dif_values: np.ndarray, dea_values: np.ndarray, current_index: int
    ) -> bool:
        """判断是否刚刚发生死叉"""
        if current_index < 1:
            return False
        return dif_values[current_index - 1] >= dea_values[current_index - 1] and dif_values[current_index] < dea_values[current_index]

    def _just_crossed_golden(
        self, dif_values: np.ndarray, dea_values: np.ndarray, current_index: int
    ) -> bool:
        """判断是否刚刚发生金叉（DIF从下方上穿DEA）"""
        if current_index < 1:
            return False
        if np.isnan(dif_values[current_index]) or np.isnan(dea_values[current_index]):
            return False
        if np.isnan(dif_values[current_index - 1]) or np.isnan(dea_values[current_index - 1]):
            return False
        return dif_values[current_index - 1] <= dea_values[current_index - 1] and dif_values[current_index] > dea_values[current_index]

    def _hist_bar_expanding(self, hist_values: np.ndarray, current_index: int, direction_sign: int) -> bool:
        """判断柱子是否在放大"""
        if current_index < 1:
            return False
        if self._sign(hist_values[current_index]) != direction_sign:
            return False
        if self._sign(hist_values[current_index - 1]) != direction_sign:
            return False
        return abs(hist_values[current_index]) > abs(hist_values[current_index - 1]) + self.min_hist

    def _segment_hist_turning_down(self, hist_values: np.ndarray, segment_start: int, current_index: int) -> bool:
        """判断当前柱段是否已经开始缩短（过峰值后回落）"""
        if segment_start < 0 or current_index - segment_start < 2:
            return False
        current_abs = abs(hist_values[current_index])
        prev_abs = abs(hist_values[current_index - 1])
        if current_abs >= prev_abs - self.min_hist:
            return False
        segment_abs = [abs(hist_values[idx]) for idx in range(segment_start, current_index + 1)]
        peak_abs = max(segment_abs)
        peak_index = segment_start + segment_abs.index(peak_abs)
        return peak_index < current_index and peak_abs > segment_abs[0] + self.min_hist

    def _check_down_up_down(
        self,
        low_vals: np.ndarray,
        high_vals: np.ndarray,
        pullback_start: int,
        current_index: int,
    ) -> tuple[bool, Optional[float]]:
        """检测绿柱回调期间股价是否形成"下上下"结构

        回调期间股价走势：先下跌(找到第一个低点) → 反弹(高点) → 再下跌(第二个低点)
        使用宽松的极值检测：在回调范围内找最低低点和随后的最高高点，
        再检查当前价格是否低于该高点（处于第二个"下"中）。
        返回 (是否满足下上下结构, 第一个低点价格)
        """
        if pullback_start < 0 or current_index - pullback_start < 2:
            return False, None

        # 在回调范围内找第一个低点（最低的low）
        first_low_idx = -1
        first_low_price = np.inf
        for idx in range(pullback_start, current_index):  # 不包含当前K线
            val = low_vals[idx]
            if np.isnan(val):
                continue
            if val < first_low_price:
                first_low_price = val
                first_low_idx = idx

        if first_low_idx < 0 or first_low_idx >= current_index:
            return False, None

        # 在第一个低点之后找反弹高点（最高的high）
        rebound_high_idx = -1
        rebound_high_price = -np.inf
        for idx in range(first_low_idx + 1, current_index + 1):
            val = high_vals[idx]
            if np.isnan(val):
                continue
            if val > rebound_high_price:
                rebound_high_price = val
                rebound_high_idx = idx

        if rebound_high_idx < 0:
            return False, None

        # 当前价格必须低于反弹高点（处于第二个"下"中）
        current_low = low_vals[current_index]
        if np.isnan(current_low):
            return False, None
        if current_low >= rebound_high_price:
            return False, None

        # 当前K线的low应该低于或接近反弹高点（确认在下跌中）
        return True, float(first_low_price)

    def _append_completed_segment(
        self,
        segments: List[_MacdSegment],
        sign: int,
        start: int,
        end: int,
        area: float,
        low_min: float,
        high_max: float,
    ) -> None:
        if sign == 0 or start < 0 or end < start:
            return
        segments.append(
            _MacdSegment(
                sign=sign,
                start=start,
                end=end,
                area=float(area),
                low_min=float(low_min),
                high_max=float(high_max),
            )
        )

    def generate_signals(self, df: pd.DataFrame) -> List[BacktestSignal]:
        if df is None or len(df) < self.slow + self.signal + 20:
            return []

        required_cols = {"close", "low", "high"}
        if not required_cols.issubset(df.columns):
            return []

        work_df = df.copy()
        time_col = "datetime" if "datetime" in work_df.columns else "date"
        times = work_df[time_col].values

        close = pd.to_numeric(work_df["close"], errors="coerce")
        low = pd.to_numeric(work_df["low"], errors="coerce")
        high = pd.to_numeric(work_df["high"], errors="coerce")

        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal, adjust=False).mean()
        hist = (dif - dea) * 2

        # 计算布林通道
        boll_mid = close.rolling(window=self.boll_period).mean()
        boll_std = close.rolling(window=self.boll_period).std(ddof=0)
        boll_upper = boll_mid + self.boll_nbdev * boll_std
        boll_lower = boll_mid - self.boll_nbdev * boll_std

        close_vals = close.values
        low_vals = low.values
        high_vals = high.values
        dif_vals = dif.values
        dea_vals = dea.values
        hist_vals = hist.values
        boll_upper_vals = boll_upper.values
        boll_lower_vals = boll_lower.values

        signals: List[BacktestSignal] = []
        completed_segments: List[_MacdSegment] = []

        current_sign = 0
        current_start = -1
        current_area = 0.0
        current_low_min = np.inf
        current_high_max = -np.inf

        in_position = False
        stop_reference = None
        # 非背驰监控状态：记录已确认的非背驰红柱对
        # non_div_state 结构:
        #   "first_red": 第一片红柱段
        #   "second_red": 第二片红柱段（非背驰）
        #   "peak_price": 第二片红柱期间的最高价
        #   "green_pullback_area": 当前回调绿柱面积
        #   "green_pullback_start": 当前回调绿柱起始索引
        #   "buy_triggered": 是否已触发买点
        #   "pullback_start": 绿柱回调起始K线索引
        non_div_state = None

        sell_segment_start = None

        warmup = self.slow + self.signal

        for i in range(len(work_df)):
            price = close_vals[i]
            if np.isnan(price) or np.isnan(dif_vals[i]) or np.isnan(dea_vals[i]) or np.isnan(hist_vals[i]):
                continue

            sign = self._sign(hist_vals[i], current_sign)
            if current_sign == 0:
                current_sign = sign
                current_start = i
                current_area = abs(hist_vals[i])
                current_low_min = low_vals[i]
                current_high_max = high_vals[i]
            elif sign != current_sign:
                self._append_completed_segment(
                    completed_segments,
                    current_sign,
                    current_start,
                    i - 1,
                    current_area,
                    current_low_min,
                    current_high_max,
                )
                current_sign = sign
                current_start = i
                current_area = abs(hist_vals[i])
                current_low_min = low_vals[i]
                current_high_max = high_vals[i]
            else:
                current_area += abs(hist_vals[i])
                current_low_min = min(current_low_min, low_vals[i])
                current_high_max = max(current_high_max, high_vals[i])

            if i < warmup or current_sign == 0:
                continue

            current = _MacdSegment(
                sign=current_sign,
                start=current_start,
                end=i,
                area=float(current_area),
                low_min=float(current_low_min),
                high_max=float(current_high_max),
            )

            # ===================== 持仓止损逻辑 =====================
            if in_position and stop_reference is not None:
                entry_price = stop_reference["entry_price"]
                first_red_area = stop_reference["first_red_area"]
                second_red_area = stop_reference["second_red_area"]
                first_red_start = stop_reference["first_red_start"]

                # 止损1: 黄白线都跌破0轴
                if dif_vals[i] <= 0 and dea_vals[i] <= 0:
                    signals.append(BacktestSignal(
                        direction="sell",
                        price=price,
                        time=self._format_time(times[i]),
                        reason=(
                            f"零轴止损: 黄白线都跌破0轴，DIF={dif_vals[i]:.5f}, DEA={dea_vals[i]:.5f}"
                        ),
                    ))
                    in_position = False
                    stop_reference = None
                    non_div_state = None
                    sell_segment_start = None
                    continue

                # 止损2: 红柱背驰卖点（当前红柱面积 < 非背驰红柱面积，且接近死叉）
                # 非背驰红柱是买入时的第二片红柱（second_red）
                if len(completed_segments) >= 2:
                    prev_red = completed_segments[-2]  # 前一片红柱（可能是非背驰红柱或更早的）
                    middle = completed_segments[-1]    # 中间的绿柱

                    # 当前红柱段与非背驰红柱段比较
                    # 注意：非背驰红柱（second_red）可能已经结束并在completed_segments中
                    # 也可能正在形成（如果买入后还没结束）
                    second_red_start = stop_reference.get("second_red_start", -1)
                    second_red_area = stop_reference.get("second_red_area", 0.0)

                    # 找到非背驰红柱的位置：可能在completed_segments中，也可能是当前段的前身
                    # 检查当前红柱是否是买入后新出现的红柱段（不是非背驰红柱本身）
                    if (
                        current.sign == 1  # 当前是红柱
                        and middle.sign == -1  # 中间是绿柱
                        and current.area < second_red_area  # 当前红柱面积 < 非背驰红柱面积（背驰）
                        and current.start != second_red_start  # 当前红柱不是非背驰红柱本身
                        and sell_segment_start != current.start
                    ):
                        near_dead = self._near_dead_cross(dif_vals, dea_vals, i, price)
                        turning_down = self._segment_hist_turning_down(hist_vals, current.start, i)
                        if near_dead and turning_down:
                            sell_segment_start = current.start
                            in_position = False
                            stop_reference = None
                            non_div_state = None
                            signals.append(BacktestSignal(
                                direction="sell",
                                price=price,
                                time=self._format_time(times[i]),
                                reason=(
                                    f"背驰卖点: 当前红柱面积={current.area:.5f} "
                                    f"< 非背驰红柱面积={second_red_area:.5f}，"
                                    "黄白线接近死叉且红柱开始缩小"
                                ),
                            ))
                            continue

                continue  # 持仓期间不检测买点

            # ===================== 非持仓：买点检测 =====================
            # 红柱阶段：检测非背驰模式并更新峰值
            if current.sign == 1:
                # 检测连续两片红柱的非背驰模式
                # 模式：红柱1-绿柱-红柱2(当前)，红柱2面积 > 红柱1面积 + 股价突破
                if len(completed_segments) >= 2:
                    seg_1 = completed_segments[-2]  # 第一片红柱
                    seg_2 = completed_segments[-1]  # 中间的绿柱
                    seg_3 = current                  # 当前正在形成的第二片红柱

                    if (
                        seg_1.sign == 1      # 第一片红柱
                        and seg_2.sign == -1  # 中间夹一片绿柱
                        and seg_3.sign == 1   # 第二片红柱（当前）
                        and seg_3.area > seg_1.area  # 非背驰：第二片红柱面积 > 第一片
                        and seg_3.high_max > seg_1.high_max  # 股价突破
                    ):
                        # 第二片红柱到达顶点时，黄白线都在0轴以上
                        # 只检查股价最高点处，不需要整段都在0轴上方
                        peak_idx_in_seg = -1
                        peak_high_in_seg = -np.inf
                        for idx in range(seg_3.start, seg_3.end + 1):
                            if not np.isnan(high_vals[idx]) and high_vals[idx] > peak_high_in_seg:
                                peak_high_in_seg = high_vals[idx]
                                peak_idx_in_seg = idx
                        lines_above_zero_at_peak = (
                            peak_idx_in_seg >= 0
                            and not np.isnan(dif_vals[peak_idx_in_seg])
                            and not np.isnan(dea_vals[peak_idx_in_seg])
                            and dif_vals[peak_idx_in_seg] > 0
                            and dea_vals[peak_idx_in_seg] > 0
                        )
                        if lines_above_zero_at_peak:
                            # 找到非背驰模式，记录第二片红柱期间的最高价及其索引
                            # (peak_idx 供趋势质量评分定位主升段峰顶)
                            peak_price = -np.inf
                            peak_idx_in_seg3 = -1
                            for idx in range(seg_3.start, seg_3.end + 1):
                                if not np.isnan(high_vals[idx]) and high_vals[idx] > peak_price:
                                    peak_price = high_vals[idx]
                                    peak_idx_in_seg3 = idx

                            non_div_state = {
                                "first_red": seg_1,
                                "second_red": seg_3,
                                "peak_price": peak_price,
                                "peak_idx": peak_idx_in_seg3,
                                "green_pullback_area": 0.0,
                                "green_pullback_start": -1,
                                "buy_triggered": False,
                                "pullback_start": -1,  # 绿柱回调起始K线索引
                            }

                # 如果已有非背驰状态且当前还在第二片红柱中，持续更新最高价
                if non_div_state is not None and not non_div_state["buy_triggered"]:
                    last_red = non_div_state["second_red"]
                    if current.start == last_red.start:
                        if not np.isnan(high_vals[i]) and high_vals[i] > non_div_state["peak_price"]:
                            non_div_state["peak_price"] = high_vals[i]
                            non_div_state["peak_idx"] = i
                        # 更新 second_red 引用，使其包含最新K线
                        non_div_state["second_red"] = current

                # 红柱阶段不检测买点
                continue

            # 以下是绿柱阶段(current.sign == -1)
            # 更新非背驰状态中的绿柱回调信息
            if non_div_state is not None and not non_div_state["buy_triggered"]:
                second_red = non_div_state["second_red"]

                # 记录绿柱回调的起始索引
                if non_div_state["pullback_start"] < 0:
                    non_div_state["pullback_start"] = current.start

                # 绿柱回调的面积必须小于非背驰红柱面积
                if current.area >= second_red.area:
                    # 绿柱面积过大，失效
                    non_div_state = None
                    continue

                # 回调时黄白线必须在0轴以上
                if not self._lines_above_zero(dif_vals[i], dea_vals[i]):
                    # 黄白线跌破0轴，失效
                    non_div_state = None
                    continue

                # 检测股价"下上下"结构
                pullback_start = non_div_state["pullback_start"]
                dud_ok, first_low_price = self._check_down_up_down(
                    low_vals, high_vals, pullback_start, i
                )
                if not dud_ok:
                    # 还未形成下上下结构，继续等待
                    continue

                # 买点条件：下上下结构形成 + 黄白线在0轴之上 + 绿柱开始缩短 + 布林收口
                if self._segment_hist_turning_down(hist_vals, current.start, i):
                    # 检查布林通道收口
                    if self._boll_contraction(boll_upper_vals, boll_lower_vals, i):
                        # 趋势质量评分: 区分"强趋势首次回调"与"下跌中继"
                        # (评分失败/数据不足返回 None,不影响买点本身)
                        quality = compute_pullback_quality(
                            work_df,
                            impulse_start=non_div_state["first_red"].start,
                            peak_idx=int(non_div_state.get("peak_idx") or -1),
                            signal_idx=i,
                        )
                        non_div_state["buy_triggered"] = True

                        # 可选质量过滤: MACD_PULLBACK_MIN_QUALITY_SCORE > 0 时,
                        # 低于阈值的买点直接丢弃(形态已消费,避免后续K线重复触发)
                        min_quality_score = int(
                            getattr(backend_config, "MACD_PULLBACK_MIN_QUALITY_SCORE", 0) or 0
                        )
                        if (
                            quality is not None
                            and min_quality_score > 0
                            and int(quality.get("score") or 0) < min_quality_score
                        ):
                            continue

                        in_position = True
                        stop_reference = {
                            "entry_price": float(price),
                            "first_red_area": non_div_state["first_red"].area,
                            "second_red_area": second_red.area,
                            "first_red_start": non_div_state["first_red"].start,
                            "second_red_start": second_red.start,
                        }
                        sell_segment_start = None
                        reason = (
                            f"非背驰回抽0轴买点: 红柱非背驰向上(第二片红柱面积={second_red.area:.5f} "
                            f"> 第一片红柱面积={non_div_state['first_red'].area:.5f}，"
                            f"股价突破{non_div_state['first_red'].high_max:.5f})，"
                            f"绿柱回调面积={current.area:.5f} < 红柱面积={second_red.area:.5f}，"
                            f"股价回调形成下上下结构(第一低点={first_low_price:.5f})，"
                            f"黄白线在0轴上方(DIF={dif_vals[i]:.5f}, DEA={dea_vals[i]:.5f})，"
                            "绿柱开始缩短，布林通道收口"
                        )
                        if quality:
                            reason += f"｜{quality['summary']}"
                        signals.append(BacktestSignal(
                            direction="buy",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=reason,
                            extra={"quality": quality} if quality else None,
                        ))
                        continue

        return signals
