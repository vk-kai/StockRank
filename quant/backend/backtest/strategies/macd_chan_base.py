from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .base import BacktestSignal, BaseBacktestStrategy
from backend.time_utils import format_beijing_time


@dataclass
class _MacdAreaSegment:
    sign: int
    start: int
    end: int
    area: float
    low_min: float
    high_max: float


class BaseMACDChanStrategy(BaseBacktestStrategy):
    min_bars = 60

    def __init__(self):
        self.fast = 12
        self.slow = 26
        self.signal = 9
        self.zero_axis_pct = 0.01
        self.zero_axis_pullback_pct = 0.015
        self.buy_cross_gap_pct = 0.0015
        self.sell_cross_gap_pct = 0.0015
        self.min_hist = 1e-6

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

    def _near_zero_axis(self, dif_value: float, dea_value: float, price: float) -> bool:
        threshold = max(abs(price) * self.zero_axis_pct, 0.003)
        return max(abs(dif_value), abs(dea_value)) <= threshold

    def _segment_lines_all_below_zero(
        self,
        dif_values: np.ndarray,
        dea_values: np.ndarray,
        segment_start: int,
        segment_end: int,
    ) -> bool:
        if segment_start < 0 or segment_end < segment_start:
            return False

        has_value = False
        for idx in range(segment_start, segment_end + 1):
            dif_value = dif_values[idx]
            dea_value = dea_values[idx]
            if np.isnan(dif_value) or np.isnan(dea_value):
                continue
            has_value = True
            if dif_value >= 0 or dea_value >= 0:
                return False
        return has_value

    def _segment_lines_all_above_zero(
        self,
        dif_values: np.ndarray,
        dea_values: np.ndarray,
        segment_start: int,
        segment_end: int,
    ) -> bool:
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

    def _segment_pullback_to_zero_ok(
        self,
        dif_values: np.ndarray,
        dea_values: np.ndarray,
        segment_start: int,
        segment_end: int,
        price: float,
        direction: str,
    ) -> bool:
        if segment_start < 0 or segment_end < segment_start:
            return False

        segment_values = []
        segment_abs = []
        for idx in range(segment_start, segment_end + 1):
            dif_value = dif_values[idx]
            dea_value = dea_values[idx]
            if np.isnan(dif_value) or np.isnan(dea_value):
                continue
            segment_values.append((dif_value, dea_value))
            segment_abs.append(max(abs(dif_value), abs(dea_value)))

        if len(segment_abs) < 2:
            return False

        threshold = max(abs(price) * self.zero_axis_pullback_pct, 0.0045)
        start_dif, start_dea = segment_values[0]
        start_abs = segment_abs[0]
        end_abs = segment_abs[-1]
        min_abs = min(segment_abs)
        near_zero_seen = min_abs <= threshold
        if direction == "buy":
            direction_ok = start_dif < 0 and start_dea < 0
        else:
            direction_ok = start_dif > 0 and start_dea > 0
        return (
            direction_ok
            and near_zero_seen
            and end_abs < start_abs - self.min_hist
            and min_abs < start_abs - self.min_hist
        )

    def _near_cross(
        self,
        dif_values: np.ndarray,
        dea_values: np.ndarray,
        current_index: int,
        price: float,
        direction: str,
    ) -> bool:
        if current_index < 2:
            return False

        gap_pct = self.buy_cross_gap_pct if direction == "buy" else self.sell_cross_gap_pct
        threshold = max(abs(price) * gap_pct, 0.0005)
        recent_gaps = []

        for idx in range(max(0, current_index - 2), current_index + 1):
            dif_value = dif_values[idx]
            dea_value = dea_values[idx]
            if np.isnan(dif_value) or np.isnan(dea_value):
                return False
            recent_gaps.append(self._cross_gap(dif_value, dea_value, direction))

        if len(recent_gaps) < 3:
            return False

        prev_gap_2, prev_gap_1, current_gap = recent_gaps[-3:]
        shrinking = prev_gap_2 > prev_gap_1 > current_gap + self.min_hist

        if direction == "buy":
            crossing_now = self._just_crossed(dif_values, dea_values, current_index, "buy")
            direction_ok = (
                (current_gap >= 0 and dif_values[current_index] <= dea_values[current_index])
                or (crossing_now and abs(current_gap) <= threshold)
            )
        else:
            crossing_now = self._just_crossed(dif_values, dea_values, current_index, "sell")
            direction_ok = (
                (current_gap >= 0 and dif_values[current_index] >= dea_values[current_index])
                or (crossing_now and abs(current_gap) <= threshold)
            )

        return shrinking and abs(current_gap) <= threshold and direction_ok

    def _cross_gap(self, dif_value: float, dea_value: float, direction: str) -> float:
        return dea_value - dif_value if direction == "buy" else dif_value - dea_value

    def _zero_axis_distance(self, dif_value: float, dea_value: float) -> float:
        return max(abs(dif_value), abs(dea_value))

    def _set_buy_retry_state(
        self,
        buy_program,
        dif_value: float,
        dea_value: float,
        hist_value: float,
        allow_retry: bool,
    ) -> None:
        if buy_program is None:
            return

        buy_program["armed"] = False
        buy_program["retry_pending"] = allow_retry
        if allow_retry:
            buy_program["retry_reference_hist_abs"] = abs(hist_value)
            buy_program["retry_reference_buy_gap"] = self._cross_gap(
                dif_value, dea_value, "buy"
            )

    def _hist_bar_expanding(self, hist_values: np.ndarray, current_index: int, direction_sign: int) -> bool:
        if current_index < 1:
            return False
        if self._sign(hist_values[current_index]) != direction_sign:
            return False
        if self._sign(hist_values[current_index - 1]) != direction_sign:
            return False
        return abs(hist_values[current_index]) > abs(hist_values[current_index - 1]) + self.min_hist

    def _just_crossed(self, dif_values: np.ndarray, dea_values: np.ndarray, current_index: int, direction: str) -> bool:
        if current_index < 1:
            return False
        if direction == "buy":
            return dif_values[current_index - 1] <= dea_values[current_index - 1] and dif_values[current_index] > dea_values[current_index]
        return dif_values[current_index - 1] >= dea_values[current_index - 1] and dif_values[current_index] < dea_values[current_index]

    def _post_second_green_chase_buy_distance_pct(self) -> float:
        # “2个点”按价格距离 2% 处理，适配不同价格区间。
        return 0.02

    def _post_second_green_max_bars(self) -> int:
        return 4

    def _hard_stop_loss_pct(self) -> float:
        return 0.03

    def _max_retry_attempts(self) -> int:
        return 2

    def _sell_reentry_max_bars(self) -> int:
        return 5

    def _build_position_reference(
        self,
        *,
        entry_price: float,
        entry_reference_low: float,
        first_green_area: float = float("inf"),
        first_green_low: float = 0.0,
        second_green_start: int = -1,
        entry_green_area: float = 0.0,
        entry_buy_gap: float = 0.0,
        post_second_green_first_red_low: Optional[float] = None,
        adjacent_red_sell_enabled: bool = False,
        adjacent_red_baseline_start: int = -1,
        adjacent_red_baseline_area: float = 0.0,
    ) -> dict:
        return {
            "first_green_area": float(first_green_area),
            "first_green_low": float(first_green_low),
            "second_green_start": int(second_green_start),
            "entry_reference_low": float(entry_reference_low),
            "entry_price": float(entry_price),
            "entry_green_area": float(entry_green_area),
            "entry_buy_gap": float(entry_buy_gap),
            "large_red_after_entry_seen": False,
            "large_red_after_entry_start": -1,
            "post_second_green_first_red_low": (
                None if post_second_green_first_red_low is None else float(post_second_green_first_red_low)
            ),
            "adjacent_red_sell_enabled": bool(adjacent_red_sell_enabled),
            "adjacent_red_baseline_start": int(adjacent_red_baseline_start),
            "adjacent_red_baseline_area": float(adjacent_red_baseline_area),
        }

    def _require_buy_lines_above_zero(self) -> bool:
        return False

    def _buy_lines_position_ok(self, dif_value: float, dea_value: float) -> bool:
        if not self._require_buy_lines_above_zero():
            return True
        return dif_value > 0 and dea_value > 0

    def _first_green_break_stop_pct(self) -> Optional[float]:
        return None

    def _buy_reason_suffix(self, pullback_required: bool, structure_above_zero: bool) -> str:
        if pullback_required:
            if self._require_buy_lines_above_zero():
                return ", 第一段绿柱区DIF/DEA均位于0轴下方，中间反向柱阶段DIF/DEA回抽0轴，当前DIF/DEA间距持续收敛并向上开始金叉，且位于0轴上方"
            return ", 第一段绿柱区DIF/DEA均位于0轴下方，中间反向柱阶段DIF/DEA回抽0轴，当前DIF/DEA间距持续收敛并向上开始金叉"
        if structure_above_zero:
            if self._require_buy_lines_above_zero():
                return ", 绿红绿区间DIF/DEA持续位于0轴上方，走势强势，当前DIF/DEA间距持续收敛并向上开始金叉，且位于0轴上方"
            return ", 绿红绿区间DIF/DEA持续位于0轴上方，走势强势，当前DIF/DEA间距持续收敛并向上开始金叉"
        if self._require_buy_lines_above_zero():
            return ", 当前DIF/DEA间距持续收敛并向上开始金叉，且位于0轴上方"
        return ", 当前DIF/DEA间距持续收敛并向上开始金叉"

    def _sell_reason_suffix(self, pullback_required: bool) -> str:
        if pullback_required:
            return ", 第一段红柱区DIF/DEA均位于0轴上方，中间反向柱阶段DIF/DEA回抽0轴，当前DIF/DEA间距持续收敛并向下开始死叉"
        return ", 当前DIF/DEA间距持续收敛并向下开始死叉"

    def _append_completed_segment(
        self,
        segments: List[_MacdAreaSegment],
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
            _MacdAreaSegment(
                sign=sign,
                start=start,
                end=end,
                area=float(area),
                low_min=float(low_min),
                high_max=float(high_max),
            )
        )

    def _segment_hist_turning_down(self, hist_values: np.ndarray, segment_start: int, current_index: int) -> bool:
        if segment_start < 0 or current_index - segment_start < 2:
            return False

        current_abs = abs(hist_values[current_index])
        prev_abs = abs(hist_values[current_index - 1])
        if current_abs >= prev_abs - self.min_hist:
            return False

        segment_abs = [abs(hist_values[idx]) for idx in range(segment_start, current_index + 1)]
        peak_abs = max(segment_abs)
        peak_index = segment_start + segment_abs.index(peak_abs)

        # 当前这片柱子至少要先明显放大过，再进入缩短阶段。
        return peak_index < current_index and peak_abs > segment_abs[0] + self.min_hist

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

        close_vals = close.values
        low_vals = low.values
        high_vals = high.values
        dif_vals = dif.values
        dea_vals = dea.values
        hist_vals = hist.values

        signals: List[BacktestSignal] = []
        completed_segments: List[_MacdAreaSegment] = []

        current_sign = 0
        current_start = -1
        current_area = 0.0
        current_low_min = np.inf
        current_high_max = -np.inf

        in_position = False
        sell_segment_start = None
        stop_reference = None
        buy_program = None
        reentry_watch = None

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

            if i < warmup or len(completed_segments) < 2 or current_sign == 0:
                continue

            first = completed_segments[-2]
            middle = completed_segments[-1]
            current = _MacdAreaSegment(
                sign=current_sign,
                start=current_start,
                end=i,
                area=float(current_area),
                low_min=float(current_low_min),
                high_max=float(current_high_max),
            )

            is_buy_pattern = first.sign == -1 and middle.sign == 1 and current.sign == -1
            near_golden_cross = self._near_cross(dif_vals, dea_vals, i, price, "buy")
            near_dead_cross = self._near_cross(dif_vals, dea_vals, i, price, "sell")
            buy_lines_position_ok = self._buy_lines_position_ok(dif_vals[i], dea_vals[i])
            current_segment_turning_down = self._segment_hist_turning_down(hist_vals, current.start, i)
            buy_middle_pullback_to_zero_ok = self._segment_pullback_to_zero_ok(
                dif_vals, dea_vals, middle.start, middle.end, price, "buy"
            )
            sell_middle_pullback_to_zero_ok = self._segment_pullback_to_zero_ok(
                dif_vals, dea_vals, middle.start, middle.end, price, "sell"
            )
            first_green_below_zero = self._segment_lines_all_below_zero(
                dif_vals, dea_vals, first.start, first.end
            )
            buy_pullback_required = first_green_below_zero
            buy_pullback_ok = (not buy_pullback_required) or buy_middle_pullback_to_zero_ok
            structure_above_zero = self._segment_lines_all_above_zero(
                dif_vals, dea_vals, first.start, i
            )

            if reentry_watch is not None and (
                current.sign not in (1, -1)
            ):
                reentry_watch = None

            if (
                reentry_watch is not None
                and i - reentry_watch.get("sell_bar_index", i) > self._sell_reentry_max_bars()
            ):
                reentry_watch = None

            if (
                buy_program is None
                or buy_program["second_green_start"] != current.start
                or buy_program["first_green_start"] != first.start
            ):
                buy_program = None

            if is_buy_pattern:
                if buy_program is None:
                    buy_program = {
                        "first_green_start": first.start,
                        "second_green_start": current.start,
                        "first_green_area": first.area,
                        "armed": True,
                        "invalidated": False,
                        "has_entry_attempt": False,
                        "retry_pending": False,
                        "retry_count": 0,
                        "retry_reference_hist_abs": float("inf"),
                        "retry_reference_buy_gap": float("inf"),
                        "first_entry_zero_axis_distance": float("inf"),
                    }
                if current.area >= first.area:
                    buy_program["invalidated"] = True
                if not near_golden_cross:
                    buy_program["armed"] = True
            else:
                buy_program = None

            if in_position and stop_reference is not None:
                first_green_area = stop_reference["first_green_area"]
                first_green_low = stop_reference["first_green_low"]
                second_green_start = stop_reference["second_green_start"]
                entry_reference_low = stop_reference["entry_reference_low"]
                entry_price = stop_reference["entry_price"]
                entry_green_area = stop_reference["entry_green_area"]
                entry_buy_gap = stop_reference.get("entry_buy_gap", 0.0)
                first_green_break_stop_pct = self._first_green_break_stop_pct()
                chase_red_low = stop_reference.get("post_second_green_first_red_low")
                hard_stop_loss_price = entry_price * (1 - self._hard_stop_loss_pct())
                adjacent_red_sell_enabled = stop_reference.get("adjacent_red_sell_enabled", False)
                adjacent_red_baseline_start = stop_reference.get("adjacent_red_baseline_start", -1)
                adjacent_red_baseline_area = stop_reference.get("adjacent_red_baseline_area", 0.0)

                if low_vals[i] <= hard_stop_loss_price:
                    drop_pct = (1 - low_vals[i] / entry_price) * 100 if entry_price > 0 else 0.0
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"硬止损: 当前价格相对最近买入价 {entry_price:.5f} 已下跌 "
                                f"{drop_pct:.2f}%，触发 {self._hard_stop_loss_pct() * 100:.1f}% 统一止损"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=(current.sign == -1),
                    )
                    sell_segment_start = None
                    continue

                if adjacent_red_sell_enabled:
                    last_completed_segment = completed_segments[-1] if completed_segments else None
                    if (
                        last_completed_segment is not None
                        and last_completed_segment.sign == 1
                        and last_completed_segment.start != adjacent_red_baseline_start
                    ):
                        adjacent_red_baseline_start = last_completed_segment.start
                        adjacent_red_baseline_area = last_completed_segment.area
                        stop_reference["adjacent_red_baseline_start"] = adjacent_red_baseline_start
                        stop_reference["adjacent_red_baseline_area"] = adjacent_red_baseline_area

                    if (
                        first.sign == 1
                        and middle.sign == -1
                        and current.sign == 1
                        and first.start == adjacent_red_baseline_start
                        and current.area < adjacent_red_baseline_area
                        and near_dead_cross
                        and current_segment_turning_down
                        and sell_segment_start != current.start
                    ):
                        sell_segment_start = current.start
                        in_position = False
                        stop_reference = None
                        reentry_watch = {
                            "sell_red_start": current.start,
                            "sell_red_area": float(current.area),
                            "sell_gap": self._cross_gap(dif_vals[i], dea_vals[i], "sell"),
                            "sell_bar_index": i,
                        }
                        signals.append(
                            self._create_signal(
                                direction="sell",
                                price=price,
                                time=self._format_time(times[i]),
                                reason=(
                                    f"追高卖点: 相邻红柱比较中，当前红柱面积={current.area:.5f} "
                                    f"< 前一片红柱面积={adjacent_red_baseline_area:.5f}，"
                                    "中间夹一片绿柱，当前再次接近死叉且红柱开始缩小"
                                ),
                            )
                        )
                        continue

                if (
                    chase_red_low is not None
                    and low_vals[i] < chase_red_low
                ):
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"止损: 追高买入后跌破第二个绿柱后首根红柱低点 "
                                f"{chase_red_low:.5f}"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=(current.sign == -1),
                    )
                    sell_segment_start = None
                    continue

                if (
                    current.sign == -1
                    and current.start == second_green_start
                    and self._hist_bar_expanding(hist_vals, i, -1)
                    and current.area > entry_green_area * 1.15
                    and self._cross_gap(dif_vals[i], dea_vals[i], "buy")
                    > entry_buy_gap + max(abs(price) * self.buy_cross_gap_pct, 0.0005)
                ):
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"止损: 买入后DIF/DEA重新快速远离，绿柱再次放大至 {current.area:.5f} "
                                f"> 入场绿柱面积={entry_green_area:.5f}"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=(current.sign == -1),
                    )
                    sell_segment_start = None
                    continue

                if (
                    first.sign == 1
                    and middle.sign == -1
                    and current.sign == 1
                    and middle.start == second_green_start
                    and sell_middle_pullback_to_zero_ok
                    and current.area >= first.area
                    and price < entry_price
                ):
                    stop_reference["large_red_after_entry_seen"] = True
                    stop_reference["large_red_after_entry_start"] = current.start

                short_red_bar_count = middle.end - middle.start + 1
                short_red_rebound_threshold = entry_green_area
                if (
                    first.sign == -1
                    and middle.sign == 1
                    and current.sign == -1
                    and first.start == second_green_start
                    and 1 <= short_red_bar_count <= 3
                    and current.start != second_green_start
                    and current.area > short_red_rebound_threshold
                ):
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"止损: 买点后短红柱仅 {short_red_bar_count} 根，随后新绿柱面积={current.area:.5f} "
                                f"> 买点所在整片绿柱区域参考面积={short_red_rebound_threshold:.5f}"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=(current.sign == -1),
                    )
                    sell_segment_start = None
                    continue

                if (
                    current.sign == -1
                    and current.start == second_green_start
                    and current.area * 2 > first_green_area
                ):
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"止损: 第二段绿柱当前已形成面积x2={current.area * 2:.5f} "
                                f"> 第一段绿柱面积={first_green_area:.5f}"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=(current.sign == -1),
                    )
                    sell_segment_start = None
                    continue

                if (
                    stop_reference.get("large_red_after_entry_seen")
                    and current.sign == -1
                    and current.start != second_green_start
                    and current.start > stop_reference.get("large_red_after_entry_start", -1)
                    and current.area > entry_green_area
                    and price < entry_price
                ):
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"止损: 红柱放大后新绿柱面积={current.area:.5f} "
                                f"> 买入区绿柱面积={entry_green_area:.5f}，且价格 {price:.5f} "
                                f"< 买入价 {entry_price:.5f}"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=(current.sign == -1),
                    )
                    sell_segment_start = None
                    continue

                if (
                    first_green_break_stop_pct is not None
                    and low_vals[i] < first_green_low * (1 - first_green_break_stop_pct)
                ):
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"止损: 买入后跌破第一片绿柱最低价 {first_green_low:.5f} 下方 "
                                f"{first_green_break_stop_pct * 100:.1f}%"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=(current.sign == -1),
                    )
                    sell_segment_start = None
                    continue

                if (
                    current.sign == -1
                    and current.start == second_green_start
                    and low_vals[i] < entry_reference_low
                ):
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"试错退出: 第二段绿柱买入后价格再创新低 "
                                f"{low_vals[i]:.5f} < 入场参考低点 {entry_reference_low:.5f}"
                            ),
                        )
                    )
                    in_position = False
                    stop_reference = None
                    self._set_buy_retry_state(
                        buy_program,
                        dif_vals[i],
                        dea_vals[i],
                        hist_vals[i],
                        allow_retry=True,
                    )
                    sell_segment_start = None
                    continue

            if not in_position:
                chase_buy_ready = False
                chase_buy_second_green = None
                if len(completed_segments) >= 3 and current.sign == 1:
                    chase_first = completed_segments[-3]
                    chase_middle = completed_segments[-2]
                    chase_second_green = completed_segments[-1]
                    second_green_bar_count = chase_second_green.end - chase_second_green.start + 1
                    second_green_distance_pct = (
                        (price - chase_second_green.low_min) / chase_second_green.low_min
                        if chase_second_green.low_min > 0
                        else np.inf
                    )
                    chase_buy_ready = (
                        chase_first.sign == -1
                        and chase_middle.sign == 1
                        and chase_second_green.sign == -1
                        and i == current.start
                        and second_green_bar_count <= self._post_second_green_max_bars()
                        and dif_vals[i] > dea_vals[i]
                        and second_green_distance_pct <= self._post_second_green_chase_buy_distance_pct()
                    )

                if chase_buy_ready and chase_second_green is not None:
                    in_position = True
                    stop_reference = self._build_position_reference(
                        entry_price=float(price),
                        entry_reference_low=chase_second_green.low_min,
                        first_green_area=chase_first.area,
                        first_green_low=chase_first.low_min,
                        second_green_start=chase_second_green.start,
                        entry_green_area=chase_second_green.area,
                        entry_buy_gap=self._cross_gap(dif_vals[i], dea_vals[i], "buy"),
                        post_second_green_first_red_low=float(low_vals[i]),
                        adjacent_red_sell_enabled=True,
                        adjacent_red_baseline_start=chase_middle.start,
                        adjacent_red_baseline_area=chase_middle.area,
                    )
                    sell_segment_start = None
                    reentry_watch = None
                    signals.append(
                        self._create_signal(
                            direction="buy",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"第二个绿柱后追高买点: 第二个绿柱仅 {second_green_bar_count} 根，"
                                f"当前价格距离第二个绿柱低点约 {second_green_distance_pct * 100:.2f}%，"
                                "黄白线已金叉并出现首根红柱"
                            ),
                        )
                    )
                    continue

                if (
                    reentry_watch is not None
                    and i - reentry_watch.get("sell_bar_index", i) <= self._sell_reentry_max_bars()
                    and current.sign == 1
                    and current.start == i
                    and self._just_crossed(dif_vals, dea_vals, i, "buy")
                ):
                    in_position = True
                    stop_reference = self._build_position_reference(
                        entry_price=float(price),
                        entry_reference_low=current.low_min,
                        entry_buy_gap=self._cross_gap(dif_vals[i], dea_vals[i], "buy"),
                        adjacent_red_sell_enabled=True,
                        adjacent_red_baseline_start=first.start,
                        adjacent_red_baseline_area=first.area,
                    )
                    sell_segment_start = None
                    reentry_watch = None
                    signals.append(
                        self._create_signal(
                            direction="buy",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=(
                                f"卖点失效追高买回: 卖出后 {self._sell_reentry_max_bars()} 根K线内出现红柱，"
                                "且DIF刚上穿DEA形成金叉，立即追高买回"
                            ),
                        )
                    )
                    continue

                retry_limit_reached = (
                    buy_program is not None
                    and buy_program["retry_pending"]
                    and buy_program.get("retry_count", 0) >= self._max_retry_attempts()
                )
                if retry_limit_reached:
                    buy_program["retry_pending"] = False
                    buy_program["armed"] = False
                    buy_program["invalidated"] = True

                allow_retry_buy = (
                    buy_program is not None
                    and buy_program["has_entry_attempt"]
                    and buy_program["retry_pending"]
                    and buy_program.get("retry_count", 0) < self._max_retry_attempts()
                    and current.area < first.area
                    and abs(hist_vals[i]) < buy_program.get("retry_reference_hist_abs", float("inf")) - self.min_hist
                    and self._cross_gap(dif_vals[i], dea_vals[i], "buy")
                    < buy_program.get("retry_reference_buy_gap", float("inf")) - self.min_hist
                    and self._zero_axis_distance(dif_vals[i], dea_vals[i])
                    < buy_program.get("first_entry_zero_axis_distance", float("inf")) - self.min_hist
                )
                allow_first_buy = current.area * 2 < first.area
                just_golden_crossed = self._just_crossed(dif_vals, dea_vals, i, "buy")
                allow_golden_cross_buy = just_golden_crossed and current.area < first.area
                if (
                    is_buy_pattern
                    and buy_pullback_ok
                    and near_golden_cross
                    and buy_lines_position_ok
                    and current_segment_turning_down
                    and buy_program is not None
                    and not buy_program["invalidated"]
                    and (
                        (buy_program["armed"] and (allow_first_buy or allow_golden_cross_buy))
                        or allow_retry_buy
                    )
                ):
                    sell_segment_start = None
                    in_position = True
                    stop_reference = self._build_position_reference(
                        entry_price=float(price),
                        entry_reference_low=current.low_min,
                        first_green_area=first.area,
                        first_green_low=first.low_min,
                        second_green_start=current.start,
                        entry_green_area=current.area,
                        entry_buy_gap=self._cross_gap(dif_vals[i], dea_vals[i], "buy"),
                    )
                    if not buy_program["has_entry_attempt"]:
                        buy_program["first_entry_zero_axis_distance"] = self._zero_axis_distance(
                            dif_vals[i], dea_vals[i]
                        )
                    buy_program["armed"] = False
                    buy_program["has_entry_attempt"] = True
                    buy_program["retry_pending"] = False
                    if allow_retry_buy:
                        buy_program["retry_count"] = buy_program.get("retry_count", 0) + 1
                    reentry_watch = None
                    if allow_retry_buy:
                        buy_reason = (
                            f"MACD背驰重试买点(第{buy_program.get('retry_count', 0) + 1}次): 止损退出后黄白线再次更接近金叉，且当前位置比第一次买入更靠近0轴，当前绿柱面积={current.area:.5f} "
                            f"< 第一绿柱面积={first.area:.5f}"
                            f"{self._buy_reason_suffix(buy_pullback_required, structure_above_zero)}"
                        )
                    elif allow_golden_cross_buy:
                        buy_reason = (
                            f"MACD金叉买点: 绿红绿结构, 黄白线金叉时第二片绿柱面积={current.area:.5f} "
                            f"< 第一片绿柱面积={first.area:.5f}"
                            f"{self._buy_reason_suffix(buy_pullback_required, structure_above_zero)}"
                        )
                    else:
                        buy_reason = (
                            f"MACD背驰买点: 绿红绿结构首次试错, 当前绿柱开始缩短, 面积x2={current.area * 2:.5f} "
                            f"< 第一绿柱面积={first.area:.5f}"
                            f"{self._buy_reason_suffix(buy_pullback_required, structure_above_zero)}"
                        )
                    signals.append(
                        self._create_signal(
                            direction="buy",
                            price=price,
                            time=self._format_time(times[i]),
                            reason=buy_reason,
                        )
                    )
                continue

            is_sell_pattern = first.sign == 1 and middle.sign == -1 and current.sign == 1
            first_red_above_zero = self._segment_lines_all_above_zero(
                dif_vals, dea_vals, first.start, first.end
            )
            middle_green_above_zero = self._segment_lines_all_above_zero(
                dif_vals, dea_vals, middle.start, middle.end
            )
            sell_pullback_required = first_red_above_zero and middle_green_above_zero
            sell_pullback_ok = (not sell_pullback_required) or sell_middle_pullback_to_zero_ok
            sell_area_ok = current.area < first.area
            if (
                is_sell_pattern
                and sell_pullback_ok
                and near_dead_cross
                and sell_area_ok
                and sell_segment_start != current.start
            ):
                sell_segment_start = current.start
                in_position = False
                stop_reference = None
                reentry_watch = {
                    "sell_red_start": current.start,
                    "sell_red_area": float(current.area),
                    "sell_gap": self._cross_gap(dif_vals[i], dea_vals[i], "sell"),
                    "sell_bar_index": i,
                }
                signals.append(
                    self._create_signal(
                        direction="sell",
                        price=price,
                        time=self._format_time(times[i]),
                        reason=(
                            f"MACD背驰卖点: 红绿红结构, 第二段红柱面积={current.area:.5f} "
                            f"< 第一红柱面积={first.area:.5f}"
                            f"{self._sell_reason_suffix(sell_pullback_required)}"
                        ),
                    )
                )

        return signals
