from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd
from .macd_chan_utils import MACDChanClassicSignals
from backend.time_utils import format_beijing_time


@dataclass
class StrategySignal:
    direction: str
    price: float
    time: str
    reason: str


@dataclass
class _MacdAreaSegment:
    sign: int
    start: int
    end: int
    area: float


class MABullPullbackBollCoreStrategy:
    min_bars = 150

    def __init__(self):
        self.ma_periods = (5, 10, 20, 60, 144)
        self.big_bull_vs_prev5_avg_pct = 0.02
        self.hard_stop_loss_pct = 0.03
        self.max_upper_shadow_range_ratio = 0.5
        self.pullback_max_bars = 3
        self.stop_loss_break_ma5_bars = 3
        self.boll_period = 20
        self.boll_nbdev = 2
        self.eps = 1e-9
        self.fast_ma_trend_lookback = 3
        self.slow_ma_trend_lookback = 5
        self.reentry_buy_window_bars = 3
        self.ma_alignment_tolerance_pct = 0.002
        self.fast_ma_pullback_tolerance_pct = 0.003
        self.slow_ma_pullback_tolerance_pct = 0.0015
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        self.macd_zero_axis_pullback_pct = 0.015
        self.macd_sell_cross_gap_pct = 0.0015
        self.macd_min_hist = 1e-6

    def _create_signal(self, direction: str, price: float, time: str, reason: str) -> StrategySignal:
        return StrategySignal(
            direction=direction,
            price=round(float(price), 5),
            time=time,
            reason=reason,
        )

    def _format_time(self, value) -> str:
        if isinstance(value, str):
            return value
        return format_beijing_time(value, "%Y-%m-%d %H:%M")

    def _is_valid_number(self, value: float) -> bool:
        return not pd.isna(value)

    def _macd_sign(self, value: float, fallback: int = 0) -> int:
        if pd.isna(value):
            return fallback
        if value > self.macd_min_hist:
            return 1
        if value < -self.macd_min_hist:
            return -1
        return fallback

    def _macd_cross_gap(self, dif_value: float, dea_value: float) -> float:
        return dif_value - dea_value

    def _macd_just_dead_cross(
        self,
        dif_values,
        dea_values,
        current_index: int,
    ) -> bool:
        if current_index < 1:
            return False
        return (
            dif_values.iloc[current_index - 1] >= dea_values.iloc[current_index - 1]
            and dif_values.iloc[current_index] < dea_values.iloc[current_index]
        )

    def _macd_near_dead_cross(
        self,
        dif_values,
        dea_values,
        current_index: int,
        price: float,
    ) -> bool:
        if current_index < 2:
            return False

        threshold = max(abs(price) * self.macd_sell_cross_gap_pct, 0.0005)
        recent_gaps = []
        for idx in range(current_index - 2, current_index + 1):
            dif_value = dif_values.iloc[idx]
            dea_value = dea_values.iloc[idx]
            if pd.isna(dif_value) or pd.isna(dea_value):
                return False
            recent_gaps.append(self._macd_cross_gap(dif_value, dea_value))

        prev_gap_2, prev_gap_1, current_gap = recent_gaps
        shrinking = prev_gap_2 > prev_gap_1 > current_gap + self.macd_min_hist
        crossing_now = self._macd_just_dead_cross(dif_values, dea_values, current_index)
        direction_ok = (
            (current_gap >= 0 and dif_values.iloc[current_index] >= dea_values.iloc[current_index])
            or (crossing_now and abs(current_gap) <= threshold)
        )
        return shrinking and abs(current_gap) <= threshold and direction_ok

    def _macd_segment_lines_all_above_zero(
        self,
        dif_values,
        dea_values,
        segment_start: int,
        segment_end: int,
    ) -> bool:
        if segment_start < 0 or segment_end < segment_start:
            return False

        has_value = False
        for idx in range(segment_start, segment_end + 1):
            dif_value = dif_values.iloc[idx]
            dea_value = dea_values.iloc[idx]
            if pd.isna(dif_value) or pd.isna(dea_value):
                continue
            has_value = True
            if dif_value <= 0 or dea_value <= 0:
                return False
        return has_value

    def _macd_segment_pullback_to_zero_ok(
        self,
        dif_values,
        dea_values,
        segment_start: int,
        segment_end: int,
        price: float,
    ) -> bool:
        if segment_start < 0 or segment_end < segment_start:
            return False

        segment_values = []
        segment_abs = []
        for idx in range(segment_start, segment_end + 1):
            dif_value = dif_values.iloc[idx]
            dea_value = dea_values.iloc[idx]
            if pd.isna(dif_value) or pd.isna(dea_value):
                continue
            segment_values.append((dif_value, dea_value))
            segment_abs.append(max(abs(dif_value), abs(dea_value)))

        if len(segment_abs) < 2:
            return False

        threshold = max(abs(price) * self.macd_zero_axis_pullback_pct, 0.0045)
        start_dif, start_dea = segment_values[0]
        start_abs = segment_abs[0]
        end_abs = segment_abs[-1]
        min_abs = min(segment_abs)
        near_zero_seen = min_abs <= threshold
        return (
            start_dif > 0
            and start_dea > 0
            and near_zero_seen
            and end_abs < start_abs - self.macd_min_hist
            and min_abs < start_abs - self.macd_min_hist
        )

    def _append_macd_completed_segment(
        self,
        segments: List[_MacdAreaSegment],
        sign: int,
        start: int,
        end: int,
        area: float,
    ) -> None:
        if sign == 0 or start < 0 or end < start:
            return
        segments.append(
            _MacdAreaSegment(
                sign=sign,
                start=start,
                end=end,
                area=float(area),
            )
        )

    def _build_macd_classic_sell_filter_reason(
        self,
        first: _MacdAreaSegment,
        current: _MacdAreaSegment,
        pullback_required: bool,
    ) -> str:
        suffix = (
            "第一段红柱和中间绿柱都运行在0轴上方，中间绿柱已完成回抽0轴，"
            if pullback_required
            else ""
        )
        return (
            "当前K线同时命中MACD红绿红经典卖点过滤："
            f"第二片红柱面积={current.area:.5f} < 第一片红柱面积={first.area:.5f}，"
            f"{suffix}DIF/DEA间距持续收敛并向下开始死叉"
        )

    def build_macd_classic_sell_filter_reasons(
        self,
        df: pd.DataFrame,
    ) -> List[Optional[str]]:
        if df is None or len(df) == 0 or "close" not in df.columns:
            return []

        close_values = pd.to_numeric(df["close"], errors="coerce")
        ema_fast = close_values.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close_values.ewm(span=self.macd_slow, adjust=False).mean()
        dif_values = ema_fast - ema_slow
        dea_values = dif_values.ewm(span=self.macd_signal, adjust=False).mean()
        hist_values = (dif_values - dea_values) * 2

        reasons: List[Optional[str]] = [None] * len(df)
        completed_segments: List[_MacdAreaSegment] = []
        current_sign = 0
        current_start = -1
        current_area = 0.0
        warmup = self.macd_slow + self.macd_signal

        for i in range(len(df)):
            price = close_values.iloc[i]
            dif_value = dif_values.iloc[i]
            dea_value = dea_values.iloc[i]
            hist_value = hist_values.iloc[i]
            if any(pd.isna(value) for value in (price, dif_value, dea_value, hist_value)):
                continue

            sign = self._macd_sign(hist_value, current_sign)
            if current_sign == 0:
                current_sign = sign
                current_start = i
                current_area = abs(hist_value)
            elif sign != current_sign:
                self._append_macd_completed_segment(
                    completed_segments,
                    current_sign,
                    current_start,
                    i - 1,
                    current_area,
                )
                current_sign = sign
                current_start = i
                current_area = abs(hist_value)
            else:
                current_area += abs(hist_value)

            if i < warmup or len(completed_segments) < 2 or current_sign == 0:
                continue

            first = completed_segments[-2]
            middle = completed_segments[-1]
            current = _MacdAreaSegment(
                sign=current_sign,
                start=current_start,
                end=i,
                area=float(current_area),
            )
            is_sell_pattern = first.sign == 1 and middle.sign == -1 and current.sign == 1
            if not is_sell_pattern:
                continue

            first_red_above_zero = self._macd_segment_lines_all_above_zero(
                dif_values,
                dea_values,
                first.start,
                first.end,
            )
            middle_green_above_zero = self._macd_segment_lines_all_above_zero(
                dif_values,
                dea_values,
                middle.start,
                middle.end,
            )
            pullback_required = first_red_above_zero and middle_green_above_zero
            pullback_ok = (not pullback_required) or self._macd_segment_pullback_to_zero_ok(
                dif_values,
                dea_values,
                middle.start,
                middle.end,
                price,
            )
            if (
                pullback_ok
                and current.area < first.area
                and self._macd_near_dead_cross(dif_values, dea_values, i, price)
            ):
                reasons[i] = self._build_macd_classic_sell_filter_reason(
                    first,
                    current,
                    pullback_required,
                )

        return reasons

    def _is_ma_trending_up(
        self,
        ma_series: pd.Series,
        index: int,
        lookback: int,
        allow_flat: bool = False,
        tolerance_pct: float = 0.0,
    ) -> bool:
        if index < lookback:
            return False
        current = ma_series.iloc[index]
        previous = ma_series.iloc[index - lookback]
        if pd.isna(current) or pd.isna(previous):
            return False
        threshold = previous * (1 - tolerance_pct)
        if allow_flat:
            return current >= threshold - self.eps
        return current > threshold + self.eps

    def _evaluate_ma_bull_alignment(self, ma_values: dict[int, pd.Series], index: int) -> tuple[bool, list[str]]:
        ma5 = ma_values[5].iloc[index]
        ma10 = ma_values[10].iloc[index]
        ma20 = ma_values[20].iloc[index]
        ma60 = ma_values[60].iloc[index]
        ma144 = ma_values[144].iloc[index]
        values = (ma5, ma10, ma20, ma60, ma144)
        if any(pd.isna(value) for value in values):
            return False, ["均线数据不完整，暂时无法判断MA多头趋势"]

        failures: list[str] = []
        align_tol = self.ma_alignment_tolerance_pct

        if ma5 < ma20 * (1 - align_tol) - self.eps:
            failures.append(
                f"MA5 低于 MA20 容差线，MA5={ma5:.5f}，MA20={ma20:.5f}，容差={align_tol * 100:.2f}%"
            )
        if ma10 < ma20 * (1 - align_tol) - self.eps:
            failures.append(
                f"MA10 低于 MA20 容差线，MA10={ma10:.5f}，MA20={ma20:.5f}，容差={align_tol * 100:.2f}%"
            )
        if ma20 < ma60 * (1 - align_tol) - self.eps:
            failures.append(
                f"MA20 低于 MA60 容差线，MA20={ma20:.5f}，MA60={ma60:.5f}，容差={align_tol * 100:.2f}%"
            )
        if ma60 < ma144 * (1 - align_tol) - self.eps:
            failures.append(
                f"MA60 低于 MA144 容差线，MA60={ma60:.5f}，MA144={ma144:.5f}，容差={align_tol * 100:.2f}%"
            )

        if not self._is_ma_trending_up(
            ma_values[5],
            index,
            self.fast_ma_trend_lookback,
            allow_flat=True,
            tolerance_pct=self.fast_ma_pullback_tolerance_pct,
        ):
            failures.append(
                f"MA5 相比 {self.fast_ma_trend_lookback} 根前回落过多，当前={ma5:.5f}，允许回撤={self.fast_ma_pullback_tolerance_pct * 100:.2f}%"
            )
        if not self._is_ma_trending_up(
            ma_values[10],
            index,
            self.fast_ma_trend_lookback,
            allow_flat=True,
            tolerance_pct=self.fast_ma_pullback_tolerance_pct,
        ):
            failures.append(
                f"MA10 相比 {self.fast_ma_trend_lookback} 根前回落过多，当前={ma10:.5f}，允许回撤={self.fast_ma_pullback_tolerance_pct * 100:.2f}%"
            )
        if not self._is_ma_trending_up(
            ma_values[20],
            index,
            self.slow_ma_trend_lookback,
            allow_flat=True,
            tolerance_pct=self.slow_ma_pullback_tolerance_pct,
        ):
            failures.append(
                f"MA20 相比 {self.slow_ma_trend_lookback} 根前走弱，当前={ma20:.5f}，允许回撤={self.slow_ma_pullback_tolerance_pct * 100:.2f}%"
            )
        if not self._is_ma_trending_up(
            ma_values[60],
            index,
            self.slow_ma_trend_lookback,
            allow_flat=True,
            tolerance_pct=self.slow_ma_pullback_tolerance_pct,
        ):
            failures.append(
                f"MA60 相比 {self.slow_ma_trend_lookback} 根前走弱，当前={ma60:.5f}，允许回撤={self.slow_ma_pullback_tolerance_pct * 100:.2f}%"
            )
        if not self._is_ma_trending_up(
            ma_values[144],
            index,
            self.slow_ma_trend_lookback,
            allow_flat=True,
            tolerance_pct=self.slow_ma_pullback_tolerance_pct * 2,
        ):
            failures.append(
                f"MA144 相比 {self.slow_ma_trend_lookback} 根前走弱，当前={ma144:.5f}，允许回撤={self.slow_ma_pullback_tolerance_pct * 200:.2f}%"
            )

        return len(failures) == 0, failures

    def _is_ma_bull_aligned(self, ma_values: dict[int, pd.Series], index: int) -> bool:
        aligned, _ = self._evaluate_ma_bull_alignment(ma_values, index)
        return aligned

    def _is_big_bull_candle(
        self,
        open_value: float,
        high_value: float,
        low_value: float,
        close_value: float,
        previous_five_close_avg: float,
    ) -> bool:
        if previous_five_close_avg <= 0:
            return False

        if self._is_one_price_limit_like_bull(
            open_value,
            high_value,
            low_value,
            close_value,
            previous_five_close_avg,
        ):
            return True

        gain_pct = close_value / previous_five_close_avg - 1
        body = close_value - open_value
        upper_shadow = high_value - max(open_value, close_value)
        candle_range = high_value - low_value
        if body <= 0 or gain_pct <= self.big_bull_vs_prev5_avg_pct:
            return False
        if candle_range <= self.eps:
            return False

        return upper_shadow / candle_range <= self.max_upper_shadow_range_ratio + self.eps

    def _is_one_price_limit_like_bull(
        self,
        open_value: float,
        high_value: float,
        low_value: float,
        close_value: float,
        previous_five_close_avg: float,
    ) -> bool:
        if previous_five_close_avg <= 0:
            return False

        gain_pct = close_value / previous_five_close_avg - 1
        price_unit = max(abs(close_value), 1.0)
        one_price_tolerance = max(self.eps, price_unit * 0.0001)
        one_price = (
            abs(open_value - close_value) <= one_price_tolerance
            and abs(high_value - close_value) <= one_price_tolerance
            and abs(low_value - close_value) <= one_price_tolerance
        )
        return one_price and gain_pct > self.big_bull_vs_prev5_avg_pct + self.eps

    def _is_bull_pullback_confirmation_bar(
        self,
        open_value: float,
        low_value: float,
        close_value: float,
        ma5_value: float,
    ) -> bool:
        if pd.isna(ma5_value) or ma5_value <= 0:
            return False

        if close_value >= ma5_value - self.eps:
            return True

        if low_value >= ma5_value - self.eps:
            return True

        body_low = min(open_value, close_value)
        body_high = max(open_value, close_value)
        return body_low - self.eps <= ma5_value <= body_high + self.eps

    def _build_buy_reason(self, trigger_time: str, distance: int, ma5_value: float) -> str:
        return (
            f"MA多头趋势后大阳线观察买点: 触发K线={trigger_time}, "
            f"后三根K线均站上MA5或实体轻触MA5, "
            f"第{distance}根K线确认买入, MA5={ma5_value:.5f}"
        )

    def _build_reentry_buy_reason(self, sell_time: str, distance: int, ma5_value: float) -> str:
        return (
            f"卖出后追高再买: 距离卖点 {sell_time} 第{distance}个交易日内重新站上MA5, "
            f"当前MA5={ma5_value:.5f}"
        )

    def _build_hard_stop_loss_reason(
        self,
        entry_price: float,
        stop_price: float,
        entry_bar_low: float,
        trigger_low: float,
        close_value: float,
    ) -> str:
        return (
            f"硬止损卖点: 买入信号价={entry_price:.5f}, "
            f"买入K线低点={entry_bar_low:.5f}, "
            f"触发{self.hard_stop_loss_pct * 100:.1f}%收盘止损线={stop_price:.5f}, "
            f"当前最低价={trigger_low:.5f}, 当前收盘价={close_value:.5f}"
        )

    def _build_stop_loss_reason(self, ma5_value: float, close_value: float, danger_time: str) -> str:
        return (
            f"一卖确认卖点: 危险位置出现在 {danger_time}, "
            f"之后连续{self.stop_loss_break_ma5_bars}根K线收盘跌破MA5, "
            f"当前收盘={close_value:.5f}, MA5={ma5_value:.5f}"
        )

    def _build_ma5_break_stop_loss_reason(self, ma5_value: float, close_value: float) -> str:
        return (
            f"止损卖点: 连续{self.stop_loss_break_ma5_bars}根K线收盘跌破MA5, "
            f"当前收盘={close_value:.5f}, MA5={ma5_value:.5f}"
        )

    def _create_boll_sell_state(self) -> dict:
        return {
            "has_super_strong_breakout": False,
            "reentered_inside_after_breakout": False,
            "breakout_reference_high": None,
        }

    def _create_one_sell_danger_state(
        self,
        signal_time: str,
        previous_high: float,
        boll_upper: float,
    ) -> dict:
        return {
            "signal_time": signal_time,
            "previous_high": previous_high,
            "boll_upper": boll_upper,
        }

    def _create_reentry_buy_state(self, sell_index: int, sell_time: str) -> dict:
        return {
            "sell_index": sell_index,
            "sell_time": sell_time,
        }

    def _get_boll_one_sell_signal(
        self,
        state: dict,
        high_value: float,
        close_value: float,
        upper_value: float,
    ) -> Optional[dict]:
        if not self._is_valid_number(upper_value):
            return None

        is_in_super_strong = close_value > upper_value + self.eps
        reference_high = state.get("breakout_reference_high")

        if is_in_super_strong:
            state["has_super_strong_breakout"] = True
            state["reentered_inside_after_breakout"] = False
            state["breakout_reference_high"] = (
                high_value
                if reference_high is None
                else max(reference_high, high_value)
            )
            return None

        if state.get("has_super_strong_breakout") and not state.get("reentered_inside_after_breakout"):
            state["reentered_inside_after_breakout"] = True
            if reference_high is None:
                state["breakout_reference_high"] = high_value
            return None

        if (
            state.get("has_super_strong_breakout")
            and state.get("reentered_inside_after_breakout")
            and reference_high is not None
            and high_value > reference_high + self.eps
        ):
            return {
                "previous_high": float(reference_high),
                "boll_upper": upper_value,
            }

        return None

    def generate_signals(self, df: pd.DataFrame) -> List[StrategySignal]:
        if df is None or len(df) < self.min_bars:
            return []

        required_cols = {"open", "high", "low", "close"}
        if not required_cols.issubset(df.columns):
            return []

        work_df = df.copy()
        time_col = "datetime" if "datetime" in work_df.columns else "date"
        if time_col not in work_df.columns:
            return []

        for col in ("open", "high", "low", "close"):
            work_df[col] = pd.to_numeric(work_df[col], errors="coerce")
        work_df = work_df.dropna(subset=[time_col, "open", "high", "low", "close"]).reset_index(drop=True)
        if len(work_df) < self.min_bars:
            return []

        times = work_df[time_col].values
        open_values = work_df["open"]
        high_values = work_df["high"]
        low_values = work_df["low"]
        close_values = work_df["close"]

        ma_values = {
            period: close_values.rolling(window=period).mean()
            for period in self.ma_periods
        }
        boll_mid = close_values.rolling(window=self.boll_period).mean()
        boll_std = close_values.rolling(window=self.boll_period).std(ddof=0)
        boll_upper = boll_mid + self.boll_nbdev * boll_std
        macd_analyzer = MACDChanClassicSignals()
        macd_sell_filter_reasons = macd_analyzer.reasons_for_df(work_df)

        signals: List[StrategySignal] = []
        active_setups: List[dict] = []
        in_position = False
        entry_index: Optional[int] = None
        entry_price: Optional[float] = None
        entry_bar_low: Optional[float] = None
        consecutive_below_ma5 = 0
        boll_sell_state: Optional[dict] = None
        one_sell_danger_state: Optional[dict] = None
        reentry_buy_state: Optional[dict] = None

        for i in range(1, len(work_df)):
            open_value = float(open_values.iloc[i])
            high_value = float(high_values.iloc[i])
            low_value = float(low_values.iloc[i])
            close_value = float(close_values.iloc[i])
            if not all(
                self._is_valid_number(value)
                for value in (open_value, high_value, low_value, close_value)
            ):
                continue

            if in_position:
                ma5_value = float(ma_values[5].iloc[i])

                if entry_price is not None and entry_price > 0 and entry_bar_low is not None:
                    hard_stop_price = entry_price * (1 - self.hard_stop_loss_pct)
                    broke_entry_bar_low = low_value < entry_bar_low - self.eps
                    close_below_hard_stop = close_value <= hard_stop_price + self.eps
                    if broke_entry_bar_low and close_below_hard_stop:
                        signals.append(
                            self._create_signal(
                                direction="sell",
                                price=close_value,
                                time=self._format_time(times[i]),
                                reason=self._build_hard_stop_loss_reason(
                                    entry_price=entry_price,
                                    stop_price=hard_stop_price,
                                    entry_bar_low=entry_bar_low,
                                    trigger_low=low_value,
                                    close_value=close_value,
                                ),
                            )
                        )
                        in_position = False
                        entry_index = None
                        entry_price = None
                        entry_bar_low = None
                        consecutive_below_ma5 = 0
                        boll_sell_state = None
                        one_sell_danger_state = None
                        reentry_buy_state = None
                        active_setups = []
                        continue

                if entry_index is not None and i > entry_index:
                    upper_value = float(boll_upper.iloc[i])
                    if (
                        one_sell_danger_state is not None
                        and self._is_valid_number(upper_value)
                        and close_value > upper_value + self.eps
                    ):
                        one_sell_danger_state = None
                        consecutive_below_ma5 = 0

                    one_sell_signal = None
                    if boll_sell_state is not None:
                        one_sell_signal = self._get_boll_one_sell_signal(
                            boll_sell_state,
                            high_value,
                            close_value,
                            upper_value,
                        )
                    if one_sell_signal is not None:
                        one_sell_danger_state = self._create_one_sell_danger_state(
                            signal_time=self._format_time(times[i]),
                            previous_high=float(one_sell_signal["previous_high"]),
                            boll_upper=float(one_sell_signal["boll_upper"]),
                        )

                if self._is_valid_number(ma5_value) and close_value < ma5_value - self.eps:
                    consecutive_below_ma5 += 1
                else:
                    consecutive_below_ma5 = 0

                if consecutive_below_ma5 >= self.stop_loss_break_ma5_bars:
                    sell_time = self._format_time(times[i])
                    sell_reason = (
                        self._build_stop_loss_reason(
                            ma5_value,
                            close_value,
                            str(one_sell_danger_state["signal_time"]),
                        )
                        if one_sell_danger_state is not None
                        else self._build_ma5_break_stop_loss_reason(ma5_value, close_value)
                    )
                    signals.append(
                        self._create_signal(
                            direction="sell",
                            price=close_value,
                            time=sell_time,
                            reason=sell_reason,
                        )
                    )
                    in_position = False
                    entry_index = None
                    entry_price = None
                    entry_bar_low = None
                    consecutive_below_ma5 = 0
                    boll_sell_state = None
                    reentry_buy_state = (
                        self._create_reentry_buy_state(i, sell_time)
                        if one_sell_danger_state is not None
                        else None
                    )
                    one_sell_danger_state = None
                    active_setups = []
                    continue

                continue

            if reentry_buy_state is not None:
                distance_from_sell = i - int(reentry_buy_state["sell_index"])
                if distance_from_sell > self.reentry_buy_window_bars:
                    reentry_buy_state = None
                elif distance_from_sell >= 1:
                    ma5_value = float(ma_values[5].iloc[i])
                    macd_filter_reason = (
                        macd_sell_filter_reasons[i]
                        if i < len(macd_sell_filter_reasons)
                        else None
                    )
                    if (
                        self._is_valid_number(ma5_value)
                        and close_value > ma5_value + self.eps
                        and not macd_filter_reason
                    ):
                        signals.append(
                            self._create_signal(
                                direction="buy",
                                price=close_value,
                                time=self._format_time(times[i]),
                                reason=self._build_reentry_buy_reason(
                                    str(reentry_buy_state["sell_time"]),
                                    distance_from_sell,
                                    ma5_value,
                                ),
                            )
                        )
                        in_position = True
                        entry_index = i
                        entry_price = close_value
                        entry_bar_low = low_value
                        consecutive_below_ma5 = 0
                        boll_sell_state = self._create_boll_sell_state()
                        one_sell_danger_state = None
                        reentry_buy_state = None
                        active_setups = []
                        continue

            if active_setups:
                ma5_value = float(ma_values[5].iloc[i])
                next_active_setups: List[dict] = []
                pending_buy_setup: Optional[dict] = None
                for setup in active_setups:
                    distance = i - int(setup["trigger_index"])
                    if distance > self.pullback_max_bars:
                        continue
                    if distance < 1:
                        next_active_setups.append(setup)
                        continue
                    if not self._is_bull_pullback_confirmation_bar(
                        open_value,
                        low_value,
                        close_value,
                        ma5_value,
                    ):
                        continue
                    if distance < self.pullback_max_bars:
                        next_active_setups.append(setup)
                        continue
                    previous_five_close_avg = float(close_values.iloc[i - 5:i].mean()) if i >= 5 else 0.0
                    if self._is_one_price_limit_like_bull(
                        open_value,
                        high_value,
                        low_value,
                        close_value,
                        previous_five_close_avg,
                    ):
                        continue
                    macd_filter_reason = (
                        macd_sell_filter_reasons[i]
                        if i < len(macd_sell_filter_reasons)
                        else None
                    )
                    if macd_filter_reason:
                        continue
                    pending_buy_setup = setup
                    break

                if pending_buy_setup is not None:
                    signals.append(
                        self._create_signal(
                            direction="buy",
                            price=close_value,
                            time=self._format_time(times[i]),
                            reason=self._build_buy_reason(
                                str(pending_buy_setup["trigger_time"]),
                                self.pullback_max_bars,
                                ma5_value,
                            ),
                        )
                    )
                    in_position = True
                    entry_index = i
                    entry_price = close_value
                    entry_bar_low = low_value
                    consecutive_below_ma5 = 0
                    boll_sell_state = self._create_boll_sell_state()
                    one_sell_danger_state = None
                    active_setups = []
                    continue

                active_setups = next_active_setups

            if i < 5:
                continue
            previous_five_close_avg = float(close_values.iloc[i - 5:i].mean())
            if (
                self._is_valid_number(previous_five_close_avg)
                and self._is_ma_bull_aligned(ma_values, i)
                and self._is_big_bull_candle(
                    open_value,
                    high_value,
                    low_value,
                    close_value,
                    previous_five_close_avg,
                )
            ):
                active_setups.append({
                    "trigger_index": i,
                    "trigger_time": self._format_time(times[i]),
                })

        return signals
