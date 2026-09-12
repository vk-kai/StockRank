from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from backend.time_utils import format_beijing_time


@dataclass
class StrategySignal:
    direction: str
    price: float
    time: str
    reason: str


class MASupportPullbackCoreStrategy:
    """MA 均线支撑回踩做多策略。

    核心思路（参考中际旭创回踩 60 日线强支撑的走势）：

    1. 在 MA5/10/20/60/144 中寻找"基础均线"——某条均线被股价持续支撑（收盘价始终在
       均线上方，允许向下 5% 的缓冲），且持续时间达到该均线对应的确认窗口，则该
       均线成为当前"基础均线"。确认窗口随均线周期动态放大（`establish_window`）。
       MA144 也作为候选：长趋势支撑下可直接作为基础（入场），并在更短基础跌破时
       作为"向上回退"的接管均线。
    2. 当某条均线成为基础均线后，股价再次回踩到该均线附近（向下回踩至均线上方
       约 5% 以内的支撑带）时做多。回踩允许向下进入 5% 缓冲但收盘需守住支撑线。
    3. 持仓期间基础均线动态切换（可上可下）：
       - 向下收紧（逐档相邻）：当前基础未跌破时，若**相邻的更短一档**均线已确认（连续支撑
         达标），则下移一档（60→20→10→5），让止损跟随更紧的支撑。
       - 向上回退（卖出后回补）：当前基础均线跌破支撑缓冲线时，**先按当前基础卖出**；
         若存在**最近（最短）的更长且已确认、未破**的备用基础均线（如 60→144、20→60），
         则**立刻回补买入**并切换基础均线到它（后续卖点以新基础为准）；若所有更长均线都
         已跌破，则卖出后保持空仓。
    4. 当前基础均线跌破即触发卖出；若同时有更长备用均线守住支撑，则卖出后立即回补并切换
       基础，否则卖出后保持空仓。
    5. 买点结构校验（多头排列）：
       - 比**基础均线更长**的周期必须严格多头排列（短周期 > 长周期），例如基础=MA60
         时要求 MA60>MA144；基础=MA20 时要求 MA20>MA60>MA144。
       - 比**基础均线更短**的周期不得低于基础均线（彼此可缠绕），例如基础=MA20 时
         MA5、MA10 均 ≥ MA20。
       - 特例：当基础均线为 MA5（或其它配置在 `special_alignment_chains` 中的周期）时，
         多头排列改用其专属链校验——MA5 默认要求 MA5>MA60>MA144（即 MA5 必须站上 MA60、
         MA144，且 MA60>MA144 长周期保持多头）；MA10、MA20 不参与校验，可任意缠绕。
         原因：MA5 周期太短，若再强求 MA5>MA10>MA20>MA60>MA144 全链严格多头过于苛刻。
       - 当前策略配置下，**只允许 MA20 / MA60 / MA144 充当基础均线**；MA5、MA10 只作为
         辅助参考，不直接作为基础入场或基础切换目标。

    买点会标注依靠的是哪条基础均线及多头排列校验结果，卖点会标注因跌破哪条基础均线而离场。
    """

    name = "MA_SUPPORT_PULLBACK"
    min_bars = 150

    def __init__(self):
        # 候选基础均线周期，按从短到长排序。当前按你的要求，只允许 20/60/144 作为基础均线；
        # MA5/MA10 仍参与多头排列、短周期压制等辅助判断，但不再直接充当基础均线。
        self.ma_periods = (20, 60, 144)
        # 所有需要计算的均线周期：基础候选 + 辅助短周期参考。
        self.short_reference_periods = (5, 10)
        self.longer_reference_periods = ()
        self.all_periods = tuple(sorted(set(self.ma_periods) | set(self.short_reference_periods) | set(self.longer_reference_periods)))
        # 特殊基础均线的多头排列"专属链"：仅要求链中相邻均线严格多头（短>长），链外的候选
        # 周期可任意缠绕。MA5 太短，要求 MA5>MA10>MA20>MA60>MA144 全链多头过于苛刻，故仅要求
        # MA5>MA60>MA144（MA5 站上长周期 60/144，且 60/144 多头）；MA10、MA20 不参与。
        self.special_alignment_chains = {5: (5, 60, 144)}
        # 支撑缓冲：收盘价跌破 均线×(1-support_buffer) 视为"完全跌破"支撑。
        self.support_buffer = 0.05
        # 回踩买入带：股价回踩至 均线×(1+pullback_buy_band) 以内视为回到均线附近。
        self.pullback_buy_band = 0.05
        # 回踩确认：买入前要求"近 lookback 根K线内最高价曾较均线高出 entry_extension_ratio"，
        # 即股价确曾离开均线上攻、再回踩回来。该条件天然过滤掉短均线（如MA5）在平滑上行中
        # "永远在买入带内"的退化信号——平滑上行时股价很少高出MA5 2%以上，故不会误触发。
        self.entry_extension_ratio = 0.02
        self.entry_extension_lookback = 10
        # 基础均线确认窗口的上下限（动态窗口 = clamp(round(P*establish_ratio), min, max))。
        # 默认取 establish_ratio=0.75，min=10，max=20：
        #   MA5→10、MA10→10、MA20→15、MA60→20、MA144→20（约一个月，匹配"前一个月站上60日线"的直觉）。
        self.establish_ratio = 0.75
        self.min_establish_bars = 10
        self.max_establish_bars = 20
        # 硬性止损：当股价相对当前持仓买入价跌超 10%，且连续 5 个交易日都被其高一级别均线压制时，
        # 立即暂时卖出，直到下一个正常买点再入场。
        self.hard_stop_loss_pct = 0.10
        self.hard_stop_ma_pressure_days = 5
        # 短周期基础额外止损：当基础为 MA5/MA10，且 MA20 明显高于 MA5/MA10 达 short_base_stop_spread，
        # 认为短周期基础失效，直接触发止损卖出。
        self.short_base_stop_spread = 0.05
        self.eps = 1e-9

    # ------------------------------------------------------------------ utils
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

    def _establish_window(self, period: int) -> int:
        """根据均线周期动态计算"基础均线"所需的连续支撑确认根数。"""
        raw = round(period * self.establish_ratio)
        return int(max(self.min_establish_bars, min(raw, self.max_establish_bars)))

    def _longer_alignment_chain(self, base_period: int) -> List[int]:
        """基础均线及其更长周期构成的链（升序），用于多头排列校验。"""
        return [period for period in self.all_periods if period >= base_period]

    def _alignment_chain(self, base_period: int) -> List[int]:
        """多头排列校验实际使用的链。

        默认取 `_longer_alignment_chain`（基础均线及以上全部周期）；若基础均线配置了专属链
        （`special_alignment_chains`，如 MA5→(5,60,144)），则改用专属链，链外周期不参与校验。
        """
        special = self.special_alignment_chains.get(base_period)
        if special:
            return list(special)
        return self._longer_alignment_chain(base_period)

    def _is_longer_bull_aligned(self, ma_values: dict, base_period: int, index: int) -> bool:
        """更长周期必须严格多头排列：链上每条短周期均线 > 下一条长周期均线。

        例：base=MA60 → MA60>MA144；base=MA20 → MA20>MA60>MA144；
        base=MA5（专属链）→ MA5>MA60>MA144。
        """
        chain = self._alignment_chain(base_period)
        for j in range(len(chain) - 1):
            shorter_period = chain[j]
            longer_period = chain[j + 1]
            ma_short = ma_values[shorter_period].iloc[index]
            ma_long = ma_values[longer_period].iloc[index]
            if pd.isna(ma_short) or pd.isna(ma_long):
                return False
            if float(ma_short) <= float(ma_long) + self.eps:
                return False
        return True

    def _is_shorter_above_base(self, ma_values: dict, base_period: int, index: int) -> bool:
        """比基础均线更短的周期不得低于基础均线（彼此可缠绕，但都不能跌破基础）。

        例：base=MA20 → MA5≥MA20 且 MA10≥MA20。
        """
        ma_base = ma_values[base_period].iloc[index]
        if pd.isna(ma_base):
            return False
        ma_base = float(ma_base)
        for period in self.ma_periods:
            if period >= base_period:
                continue
            ma_short = ma_values[period].iloc[index]
            if pd.isna(ma_short):
                return False
            if float(ma_short) < ma_base - self.eps:
                return False
        return True

    def _alignment_label(self, base_period: int) -> str:
        """生成买点原因里的多头排列描述文本。"""
        longer_part = ">".join(f"MA{p}" for p in self._alignment_chain(base_period))
        shorter = [p for p in self.ma_periods if p < base_period]
        if shorter:
            shorter_part = "+".join(f"MA{p}" for p in shorter) + f">=MA{base_period}"
            return f"多头排列校验通过({longer_part}, {shorter_part})"
        return f"多头排列校验通过({longer_part})"

    @staticmethod
    def _format_pct(ratio: float) -> str:
        return f"{ratio * 100:.2f}%"

    # ------------------------------------------------------------- buy/sell
    def _build_buy_reason(
        self,
        period: int,
        ma_value: float,
        close_value: float,
        low_value: float,
        streak: int,
        recent_high: Optional[float],
        alignment_label: str = "",
    ) -> str:
        low_vs_ma = (low_value / ma_value - 1) if ma_value > 0 else 0.0
        close_vs_ma = (close_value / ma_value - 1) if ma_value > 0 else 0.0
        high_vs_ma = (
            (recent_high / ma_value - 1)
            if ma_value > 0 and self._is_valid_number(recent_high)
            else float("nan")
        )
        alignment_text = f"，{alignment_label}" if alignment_label else ""
        return (
            f"MA支撑回踩买点: 基础均线=MA{period}，近{streak}根K线持续受其支撑，"
            f"近{self.entry_extension_lookback}根高点={recent_high:.5f}"
            f"(距MA{period}={self._format_pct(high_vs_ma)}，确认曾离开均线上攻)，"
            f"本次回踩至均线附近(低点={low_value:.5f}，距MA{period}={self._format_pct(low_vs_ma)}，"
            f"收盘={close_value:.5f}，距MA{period}={self._format_pct(close_vs_ma)})"
            f"{alignment_text}，做多。"
        )

    def _build_sell_reason(
        self,
        period: int,
        ma_value: float,
        close_value: float,
        break_level: float,
        base_shifts: List[dict],
        reason_prefix: str = "MA支撑破位卖点",
        extra_text: str = "",
    ) -> str:
        shift_text = ""
        if base_shifts:
            shift_text = "；基础均线迁移：" + "→".join(
                f"MA{shift['from']}@{shift['time']}" for shift in base_shifts
            ) + f"→MA{period}"
        suffix = f"；{extra_text}" if extra_text else ""
        return (
            f"{reason_prefix}: 基础均线=MA{period}，"
            f"收盘={close_value:.5f} 跌破支撑缓冲线 {break_level:.5f}"
            f"(=MA{period}×(1-{self._format_pct(self.support_buffer)}), MA{period}={ma_value:.5f})"
            f"{shift_text}{suffix}。"
        )

    def _higher_period_for_base(self, base_period: int) -> Optional[int]:
        """返回基础均线的高一级别均线。"""
        ordered = list(self.ma_periods)
        try:
            idx = ordered.index(base_period)
        except ValueError:
            return None
        if idx + 1 >= len(ordered):
            return None
        return ordered[idx + 1]

    def _hard_stop_pressure_triggered(self, ma_values: dict, base_period: int, index: int) -> tuple[bool, str]:
        """硬性止损附加条件：连续 N 个交易日被高一级别均线压制。"""
        higher_period = self._higher_period_for_base(base_period)
        if higher_period is None:
            return False, ""
        ma_base = ma_values.get(base_period)
        ma_higher = ma_values.get(higher_period)
        if ma_base is None or ma_higher is None:
            return False, ""
        start = index - self.hard_stop_ma_pressure_days + 1
        if start < 0:
            return False, ""
        for j in range(start, index + 1):
            base_value = ma_base.iloc[j]
            higher_value = ma_higher.iloc[j]
            if pd.isna(base_value) or pd.isna(higher_value):
                return False, ""
            if float(base_value) >= float(higher_value) - self.eps:
                return False, ""
        return True, (
            f"连续{self.hard_stop_ma_pressure_days}个交易日 MA{base_period} 均位于其高一级别 MA{higher_period} 下方，"
            f"判定被更高一级别均线持续压制。"
        )

    def _build_hard_stop_reason(
        self,
        entry_price: float,
        close_value: float,
        pressure_text: str = "",
    ) -> str:
        stop_price = entry_price * (1 - self.hard_stop_loss_pct)
        drop_pct = (close_value / entry_price - 1) if entry_price > 0 else 0.0
        extra = f"；{pressure_text}" if pressure_text else ""
        return (
            f"硬性止损卖点: 当前收盘={close_value:.5f}，买入价={entry_price:.5f}，"
            f"相对买入价跌幅={self._format_pct(drop_pct)}，已跌破硬止损线 {stop_price:.5f}"
            f"(=买入价×(1-{self._format_pct(self.hard_stop_loss_pct)})){extra}，暂时卖出，等待下一个正常买点。"
        )

    def _build_rebuy_reason(
        self,
        old_base: int,
        new_base: int,
        ma_values: dict,
        i: int,
        close_value: float,
        break_level: float,
    ) -> str:
        new_ma_value = float(ma_values[new_base].iloc[i])
        return (
            f"MA支撑基础切换回补买点: 原基础均线=MA{old_base}收盘={close_value:.5f}"
            f"跌破支撑缓冲线{break_level:.5f}触发卖出，"
            f"备用基础均线=MA{new_base}（={new_ma_value:.5f}）守住支撑（已确认且未破），"
            f"切换基础均线到MA{new_base}并回补做多，后续卖点以MA{new_base}为准。"
        )

    def _short_base_stop_triggered(self, ma_values: dict, base_period: int, index: int) -> tuple[bool, str]:
        """短周期基础均线的额外止损：

        当基础均线是 MA5 或 MA10 时，若 MA20 同时高于 MA5 和 MA10，且高出幅度都达到
        `short_base_stop_spread`（默认 5%），则认为短周期基础失效，直接触发止损卖出。
        """
        if base_period not in (5, 10):
            return False, ""
        ma20 = ma_values.get(20)
        ma5 = ma_values.get(5)
        ma10 = ma_values.get(10)
        if ma20 is None or ma5 is None or ma10 is None:
            return False, ""
        v20 = ma20.iloc[index]
        v5 = ma5.iloc[index]
        v10 = ma10.iloc[index]
        if pd.isna(v20) or pd.isna(v5) or pd.isna(v10):
            return False, ""
        spread_20_vs_5 = (float(v20) / float(v5) - 1) if float(v5) > 0 else float("inf")
        spread_20_vs_10 = (float(v20) / float(v10) - 1) if float(v10) > 0 else float("inf")
        if (
            float(v20) > float(v5) + self.eps
            and float(v20) > float(v10) + self.eps
            and spread_20_vs_5 >= self.short_base_stop_spread - self.eps
            and spread_20_vs_10 >= self.short_base_stop_spread - self.eps
        ):
            return True, (
                f"短周期基础止损触发：当前基础均线=MA{base_period}，"
                f"MA20={float(v20):.5f} 相对 MA5={float(v5):.5f} 高出 {self._format_pct(spread_20_vs_5)}，"
                f"相对 MA10={float(v10):.5f} 高出 {self._format_pct(spread_20_vs_10)}，"
                f"均达到止损阈值 {self._format_pct(self.short_base_stop_spread)}，判定短周期基础失效。"
            )
        return False, ""

    def _pick_active_base_period(
        self,
        support_streaks: dict,
        establish_windows: dict,
        ma_values: dict,
        close_value: float,
        index: int,
        preferred_periods: Optional[List[int]] = None,
    ) -> Optional[int]:
        """从给定候选里选出当前可接管的基础均线。

        规则：
        1. 必须已确认（连续支撑根数达标）；
        2. 当前收盘仍守住该均线支撑缓冲线；
        3. 多头排列校验通过；
        4. 比该基础更短的周期不得低于该基础。

        返回满足条件的"最短"候选（周期最小者）。若传入 preferred_periods，则仅在该集合内挑选。
        也就是说：如果 MA60 和 MA144 同时都能成立为基础，则优先取 MA60；若 MA20/60/144
        同时成立，则优先取 MA20。
        """
        candidate_pool = preferred_periods if preferred_periods is not None else list(self.ma_periods)
        qualified: List[int] = []
        for period in candidate_pool:
            ma_value = float(ma_values[period].iloc[index])
            if not self._is_valid_number(ma_value) or ma_value <= 0:
                continue
            if support_streaks[period] < establish_windows[period]:
                continue
            break_level = ma_value * (1 - self.support_buffer)
            if close_value < break_level - self.eps:
                continue
            if not self._is_longer_bull_aligned(ma_values, period, index):
                continue
            if not self._is_shorter_above_base(ma_values, period, index):
                continue
            qualified.append(period)
        return min(qualified) if qualified else None

    # ----------------------------------------------------------- main logic
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
        high_values = work_df["high"]
        low_values = work_df["low"]
        close_values = work_df["close"]

        ma_values = {
            period: close_values.rolling(window=period).mean()
            for period in self.all_periods
        }
        # 近 lookback 根K线（不含当前根）的最高价，用于"曾离开均线上攻"的回踩确认。
        recent_high_max = high_values.rolling(window=self.entry_extension_lookback).max().shift(1)
        establish_windows = {period: self._establish_window(period) for period in self.ma_periods}

        signals: List[StrategySignal] = []

        # 每条均线的"连续支撑根数"：收盘价 >= 均线×(1-support_buffer) 则累计，否则清零。
        support_streaks = {period: 0 for period in self.ma_periods}

        in_position = False
        current_base_period: Optional[int] = None
        current_entry_price: Optional[float] = None
        base_shifts: List[dict] = []

        for i in range(len(work_df)):
            high_value = float(high_values.iloc[i])
            low_value = float(low_values.iloc[i])
            close_value = float(close_values.iloc[i])
            if not all(
                self._is_valid_number(value)
                for value in (high_value, low_value, close_value)
            ):
                # 出现异常值时，保守地把所有支撑计数清零，避免状态错乱。
                for period in self.ma_periods:
                    support_streaks[period] = 0
                continue

            # 先更新每条均线的支撑计数。
            for period in self.ma_periods:
                ma_value = float(ma_values[period].iloc[i])
                if not self._is_valid_number(ma_value) or ma_value <= 0:
                    support_streaks[period] = 0
                    continue
                break_level = ma_value * (1 - self.support_buffer)
                if close_value >= break_level - self.eps:
                    support_streaks[period] += 1
                else:
                    support_streaks[period] = 0

            if in_position and current_base_period is not None:
                # 持仓中：始终只遵守一个"当前基础均线"，但它可动态切换。
                ma_value = float(ma_values[current_base_period].iloc[i])
                if self._is_valid_number(ma_value) and ma_value > 0:
                    break_level = ma_value * (1 - self.support_buffer)
                    hard_stop_price = (
                        current_entry_price * (1 - self.hard_stop_loss_pct)
                        if current_entry_price is not None and current_entry_price > 0
                        else None
                    )
                    hard_stop_pressure_ok, hard_stop_pressure_text = self._hard_stop_pressure_triggered(
                        ma_values, current_base_period, i
                    )
                    if (
                        hard_stop_price is not None
                        and close_value < hard_stop_price - self.eps
                        and hard_stop_pressure_ok
                    ):
                        signals.append(
                            self._create_signal(
                                direction="sell",
                                price=close_value,
                                time=self._format_time(times[i]),
                                reason=self._build_hard_stop_reason(
                                    entry_price=float(current_entry_price),
                                    close_value=close_value,
                                    pressure_text=hard_stop_pressure_text,
                                ),
                            )
                        )
                        in_position = False
                        current_base_period = None
                        current_entry_price = None
                        base_shifts = []
                    else:
                        short_stop_triggered, short_stop_text = self._short_base_stop_triggered(
                        ma_values, current_base_period, i
                    )
                    if short_stop_triggered:
                        old_base = current_base_period
                        signals.append(
                            self._create_signal(
                                direction="sell",
                                price=close_value,
                                time=self._format_time(times[i]),
                                reason=self._build_sell_reason(
                                    period=old_base,
                                    ma_value=ma_value,
                                    close_value=close_value,
                                    break_level=break_level,
                                    base_shifts=base_shifts,
                                    reason_prefix="MA短周期基础失效止损卖点",
                                    extra_text=short_stop_text,
                                ),
                            )
                        )
                        in_position = False
                        current_base_period = None
                        current_entry_price = None
                        base_shifts = []
                    elif close_value < break_level - self.eps:
                        # 当前基础跌破：立即按当前基础卖出并结束本轮持仓。
                        old_base = current_base_period
                        signals.append(
                            self._create_signal(
                                direction="sell",
                                price=close_value,
                                time=self._format_time(times[i]),
                                reason=self._build_sell_reason(
                                    period=old_base,
                                    ma_value=ma_value,
                                    close_value=close_value,
                                    break_level=break_level,
                                    base_shifts=base_shifts,
                                ),
                            )
                        )
                        in_position = False
                        current_base_period = None
                        current_entry_price = None
                        base_shifts = []
                    else:
                        # 未跌破：若存在更短且也满足完整基础条件的基础均线，则切换到更短者。
                        next_base = self._pick_active_base_period(
                            support_streaks=support_streaks,
                            establish_windows=establish_windows,
                            ma_values=ma_values,
                            close_value=close_value,
                            index=i,
                        )
                        if (
                            next_base is not None
                            and next_base != current_base_period
                            and next_base < current_base_period
                        ):
                            base_shifts.append(
                                {
                                    "from": current_base_period,
                                    "to": next_base,
                                    "time": self._format_time(times[i]),
                                }
                            )
                            current_base_period = next_base
                continue

            # 空仓：从当前仍守住支撑、且满足完整基础条件的均线里挑新的基础均线。
            base_period = self._pick_active_base_period(
                support_streaks=support_streaks,
                establish_windows=establish_windows,
                ma_values=ma_values,
                close_value=close_value,
                index=i,
            )
            if base_period is None:
                continue

            ma_value = float(ma_values[base_period].iloc[i])
            if not self._is_valid_number(ma_value) or ma_value <= 0:
                continue

            buy_zone_upper = ma_value * (1 + self.pullback_buy_band)
            break_level = ma_value * (1 - self.support_buffer)

            # 回踩确认：近 lookback 根K线股价曾离开均线上攻（高出 entry_extension_ratio），
            # 当前根又回到均线附近（低点进买入带）且收盘守住支撑线，三者同时成立才做多。
            recent_high = recent_high_max.iloc[i]
            extended_above_ma = (
                self._is_valid_number(recent_high)
                and recent_high >= ma_value * (1 + self.entry_extension_ratio) - self.eps
            )
            pulled_back_to_ma = low_value <= buy_zone_upper + self.eps
            held_support = close_value >= break_level - self.eps
            # 多头排列：更长周期严格多头、更短周期不低于基础均线。
            # MA5 等专属链基础均线的特殊校验已封装在 _alignment_chain / _is_longer_bull_aligned 中。
            longer_aligned = self._is_longer_bull_aligned(ma_values, base_period, i)
            shorter_above = self._is_shorter_above_base(ma_values, base_period, i)
            if (
                extended_above_ma
                and pulled_back_to_ma
                and held_support
                and longer_aligned
                and shorter_above
            ):
                signals.append(
                    self._create_signal(
                        direction="buy",
                        price=close_value,
                        time=self._format_time(times[i]),
                        reason=self._build_buy_reason(
                            period=base_period,
                            ma_value=ma_value,
                            close_value=close_value,
                            low_value=low_value,
                            streak=support_streaks[base_period],
                            recent_high=recent_high,
                            alignment_label=self._alignment_label(base_period),
                        ),
                    )
                )
                in_position = True
                current_base_period = base_period
                current_entry_price = close_value
                base_shifts = []

        return signals
