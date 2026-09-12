from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from backend.backtest.strategies import get_backtest_strategy
from backend.backtest.strategies.macd_chan_base import BaseMACDChanStrategy, _MacdAreaSegment
from backend.strategy_core import MABullPullbackBollCoreStrategy, MASupportPullbackCoreStrategy
from backend.time_utils import to_chart_seconds, to_epoch_seconds


def _make_eval(direction: str, point_key: str, point_name: str, status: str, reason: str) -> dict:
    return {
        "direction": direction,
        "point_key": point_key,
        "point_name": point_name,
        "status": status,
        "reason": reason,
    }


MACD_POINT_CATALOG = [
    ("buy", "divergence_buy", "MACD背驰买点"),
    ("buy", "golden_cross_buy", "MACD金叉买点"),
    ("buy", "retry_buy", "MACD背驰重试买点"),
    ("buy", "second_green_chase_buy", "第二个绿柱后追高买点"),
    ("buy", "reentry_buy", "卖点失效追高买回"),
    ("sell", "divergence_sell", "MACD背驰卖点"),
    ("sell", "adjacent_red_chase_sell", "追高卖点"),
    ("sell", "hard_stop_sell", "硬止损卖点"),
    ("sell", "red_low_break_sell", "跌破首根红柱低点止损卖点"),
    ("sell", "gap_expand_sell", "DIF/DEA重新远离止损卖点"),
    ("sell", "short_red_rebound_sell", "短红柱后新绿柱放大止损卖点"),
    ("sell", "double_area_sell", "第二段绿柱面积翻倍止损卖点"),
    ("sell", "post_large_red_sell", "红柱放大后新绿柱反扑止损卖点"),
    ("sell", "first_green_break_sell", "跌破第一片绿柱低点止损卖点"),
    ("sell", "new_low_exit_sell", "再创新低试错退出卖点"),
]

MA_BULL_POINT_CATALOG = [
    ("buy", "pullback_buy", "大阳回踩MA5确认买点"),
    ("buy", "reentry_buy", "卖出后追高再买买点"),
    ("sell", "hard_stop_sell", "硬止损卖点"),
    ("sell", "one_sell_confirm_sell", "一卖确认卖点"),
    ("sell", "ma5_break_sell", "连续跌破MA5止损卖点"),
]

MA_SUPPORT_POINT_CATALOG = [
    ("buy", "pullback_buy", "回踩基础均线买点"),
    ("buy", "switch_rebuy", "基础切换回补买点"),
    ("sell", "support_break_sell", "跌破基础均线支撑卖点"),
]

NON_DIVERGENCE_POINT_CATALOG = [
    ("buy", "non_divergence_pullback_buy", "非背驰回抽0轴买点"),
    ("sell", "hard_stop_sell", "止损卖出（下跌10%）"),
    ("sell", "zero_axis_stop_sell", "零轴止损（黄白线都跌破0轴）"),
    ("sell", "divergence_sell", "红柱背驰卖点"),
]


def get_strategy_point_catalog(strategy_name: str) -> list[dict]:
    if strategy_name in {"MACD_CHAN_DIVERGENCE", "MACD_CHAN_THIRD_BUY"}:
        return [
            {"direction": direction, "point_key": point_key, "point_name": point_name}
            for direction, point_key, point_name in MACD_POINT_CATALOG
        ]
    if strategy_name == "MA_BULL_PULLBACK_BOLL":
        return [
            {"direction": direction, "point_key": point_key, "point_name": point_name}
            for direction, point_key, point_name in MA_BULL_POINT_CATALOG
        ]
    if strategy_name == "MA_SUPPORT_PULLBACK":
        return [
            {"direction": direction, "point_key": point_key, "point_name": point_name}
            for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
        ]
    if strategy_name == "MACD_NON_DIVERGENCE_PULLBACK":
        return [
            {"direction": direction, "point_key": point_key, "point_name": point_name}
            for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
        ]
    return []


def _timestamp_seconds(value) -> Optional[int]:
    return to_epoch_seconds(value)


def _chart_timestamp_seconds(value, *, date_only: bool = False) -> Optional[int]:
    return to_chart_seconds(value, date_only=date_only)


def _matches_target_timestamp(value, target_timestamp: int, *, date_only: bool = False) -> bool:
    target = int(target_timestamp)
    return (
        _timestamp_seconds(value) == target
        or _chart_timestamp_seconds(value, date_only=date_only) == target
    )


def _find_target_index(df: pd.DataFrame, time_col: str, target_timestamp: int) -> Optional[int]:
    if df is None or df.empty or time_col not in df.columns:
        return None
    date_only = time_col == "date"
    for index, value in enumerate(df[time_col].tolist()):
        if _matches_target_timestamp(value, target_timestamp, date_only=date_only):
            return index
    return None


def _signals_at_bar(signal_list: list, target_timestamp: int) -> list:
    matched = []
    for signal in signal_list:
        signal_time = getattr(signal, "time", None)
        date_only = isinstance(signal_time, str) and ":" not in signal_time
        if _matches_target_timestamp(signal_time, target_timestamp, date_only=date_only):
            matched.append(signal)
    return matched


def _first_matched_reason(
    matched_signals: list,
    direction: str,
    matcher: Callable[[str], bool],
) -> Optional[str]:
    for signal in matched_signals:
        if getattr(signal, "direction", "") != direction:
            continue
        reason = str(getattr(signal, "reason", "") or "")
        if matcher(reason):
            return reason
    return None


def _segment_name(sign_value: int) -> str:
    if sign_value > 0:
        return "红柱"
    if sign_value < 0:
        return "绿柱"
    return "零轴"


def _format_pattern(first: Optional[_MacdAreaSegment], middle: Optional[_MacdAreaSegment], current: Optional[_MacdAreaSegment]) -> str:
    if first is None or middle is None or current is None:
        return "结构尚未形成"
    return f"{_segment_name(first.sign)}-{_segment_name(middle.sign)}-{_segment_name(current.sign)}"


def _join_failures(default_text: str, failures: list[str]) -> str:
    if not failures:
        return default_text
    return "；".join(failures)


def _current_gap(strategy: BaseMACDChanStrategy, dif_value: float, dea_value: float, direction: str) -> float:
    return strategy._cross_gap(dif_value, dea_value, direction)


def _match_macd_reason_to_key(reason: str) -> Optional[str]:
    if reason.startswith("MACD背驰重试买点"):
        return "retry_buy"
    if reason.startswith("MACD金叉买点"):
        return "golden_cross_buy"
    if reason.startswith("MACD背驰买点"):
        return "divergence_buy"
    if reason.startswith("第二个绿柱后追高买点"):
        return "second_green_chase_buy"
    if reason.startswith("卖点失效追高买回"):
        return "reentry_buy"
    if reason.startswith("MACD背驰卖点"):
        return "divergence_sell"
    if reason.startswith("追高卖点"):
        return "adjacent_red_chase_sell"
    if reason.startswith("硬止损"):
        return "hard_stop_sell"
    if "第二个绿柱后首根红柱低点" in reason:
        return "red_low_break_sell"
    if "DIF/DEA重新快速远离" in reason:
        return "gap_expand_sell"
    if "买点后短红柱仅" in reason:
        return "short_red_rebound_sell"
    if "面积x2=" in reason and "第一段绿柱面积" in reason:
        return "double_area_sell"
    if "红柱放大后新绿柱面积" in reason:
        return "post_large_red_sell"
    if "第一片绿柱最低价" in reason:
        return "first_green_break_sell"
    if reason.startswith("试错退出"):
        return "new_low_exit_sell"
    return None


def _macd_reason_matcher(point_key: str) -> Callable[[str], bool]:
    return lambda reason: _match_macd_reason_to_key(reason) == point_key


def _ma_reason_matcher(point_key: str) -> Callable[[str], bool]:
    def _match(reason: str) -> bool:
        if point_key == "pullback_buy":
            return reason.startswith("MA多头趋势后大阳线观察买点")
        if point_key == "reentry_buy":
            return reason.startswith("卖出后追高再买")
        if point_key == "hard_stop_sell":
            return reason.startswith("硬止损卖点")
        if point_key == "one_sell_confirm_sell":
            return reason.startswith("一卖确认卖点")
        if point_key == "ma5_break_sell":
            return reason.startswith("止损卖点: 连续")
        return False
    return _match


def _ma_support_reason_matcher(point_key: str) -> Callable[[str], bool]:
    def _match(reason: str) -> bool:
        if point_key == "pullback_buy":
            return reason.startswith("MA支撑回踩买点")
        if point_key == "switch_rebuy":
            return reason.startswith("MA支撑基础切换回补买点")
        if point_key == "support_break_sell":
            return reason.startswith("MA支撑破位卖点")
        return False
    return _match


def _build_macd_out_of_range_evaluations(strategy_name: str, range_reason: str) -> list[dict]:
    return [
        _make_eval(direction, point_key, point_name, "out_of_range", range_reason)
        for direction, point_key, point_name in MACD_POINT_CATALOG
    ]


def _build_ma_out_of_range_evaluations(range_reason: str) -> list[dict]:
    return [
        _make_eval(direction, point_key, point_name, "out_of_range", range_reason)
        for direction, point_key, point_name in MA_BULL_POINT_CATALOG
    ]


def _build_ma_support_out_of_range_evaluations(range_reason: str) -> list[dict]:
    return [
        _make_eval(direction, point_key, point_name, "out_of_range", range_reason)
        for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
    ]


def _describe_not_ready_macd(strategy_name: str, matched_signals: list, reason: str) -> list[dict]:
    evaluations = []
    for direction, point_key, point_name in MACD_POINT_CATALOG:
        matched_reason = _first_matched_reason(matched_signals, direction, _macd_reason_matcher(point_key))
        evaluations.append(
            _make_eval(
                direction,
                point_key,
                point_name,
                "matched" if matched_reason else "not_matched",
                matched_reason or reason,
            )
        )
    return evaluations


def _build_macd_evaluations(
    strategy_name: str,
    strategy: BaseMACDChanStrategy,
    matched_signals: list,
    *,
    price: float,
    low_value: float,
    dif_value: float,
    dea_value: float,
    hist_values: np.ndarray,
    current_index: int,
    first: Optional[_MacdAreaSegment],
    middle: Optional[_MacdAreaSegment],
    current: Optional[_MacdAreaSegment],
    is_buy_pattern: bool,
    near_golden_cross: bool,
    near_dead_cross: bool,
    buy_lines_position_ok: bool,
    current_segment_turning_down: bool,
    buy_middle_pullback_to_zero_ok: bool,
    sell_middle_pullback_to_zero_ok: bool,
    first_green_below_zero: bool,
    buy_pullback_required: bool,
    buy_pullback_ok: bool,
    structure_above_zero: bool,
    sell_pullback_required: bool,
    sell_pullback_ok: bool,
    in_position: bool,
    stop_reference: Optional[dict],
    sell_segment_start,
    buy_program: Optional[dict],
    reentry_watch: Optional[dict],
    completed_segments: list[_MacdAreaSegment],
    current_sign: int,
) -> list[dict]:
    evaluations: list[dict] = []
    pattern_text = _format_pattern(first, middle, current)
    buy_gap = _current_gap(strategy, dif_value, dea_value, "buy")
    sell_gap = _current_gap(strategy, dif_value, dea_value, "sell")

    def matched_or(point_key: str, direction: str, point_name: str, fallback_reason: str) -> dict:
        matched_reason = _first_matched_reason(matched_signals, direction, _macd_reason_matcher(point_key))
        return _make_eval(
            direction,
            point_key,
            point_name,
            "matched" if matched_reason else "not_matched",
            matched_reason or fallback_reason,
        )

    if first is None or middle is None or current is None:
        reason = "当前K线前还没有形成足够完整的MACD柱体结构，至少需要先出现可分析的三段柱区。"
        return _describe_not_ready_macd(strategy_name, matched_signals, reason)

    allow_first_buy = current.area * 2 < first.area
    evaluations.append(matched_or(
        "divergence_buy",
        "buy",
        "MACD背驰买点",
        _join_failures(
            "当前K线不满足MACD背驰买点。",
            [
                f"当前柱体结构是 {pattern_text}，背驰买点要求绿柱-红柱-绿柱结构" if not is_buy_pattern else "",
                (
                    "第一片绿柱位于0轴下方时，中间红柱需要回抽0轴；当前中间红柱没有完成回抽0轴"
                    if buy_pullback_required and not buy_middle_pullback_to_zero_ok else ""
                ),
                f"当前黄白线还没有进入买点要求的金叉收敛区，DIF={dif_value:.5f}, DEA={dea_value:.5f}, 买入间距={buy_gap:.5f}" if not near_golden_cross else "",
                f"第二片绿柱还没有开始缩短，当前柱绝对值={abs(hist_values[current_index]):.5f}" if not current_segment_turning_down else "",
                (
                    f"首次试错要求第二片绿柱面积x2 < 第一片绿柱面积；当前x2={current.area * 2:.5f}, 第一片面积={first.area:.5f}"
                    if not allow_first_buy else ""
                ),
                (
                    "当前不是空仓观察状态，背驰买点要求出现买点前策略处于空仓"
                    if in_position else ""
                ),
                (
                    "当前买点程序已失效，通常是因为第二片绿柱面积已经不再小于第一片绿柱"
                    if buy_program is not None and buy_program.get("invalidated") else ""
                ),
                (
                    "当前还没有进入首次试错触发窗口"
                    if buy_program is None else ""
                ),
            ],
        ),
    ))

    matched_reason = _first_matched_reason(matched_signals, "buy", _macd_reason_matcher("golden_cross_buy"))
    if matched_reason:
        evaluations.append(_make_eval("buy", "golden_cross_buy", "MACD金叉买点", "matched", matched_reason))
    else:
        failures = []
        if not is_buy_pattern:
            failures.append(f"当前柱体结构是 {pattern_text}，金叉买点要求绿柱-红柱-绿柱结构")
        if buy_pullback_required and not buy_middle_pullback_to_zero_ok:
            failures.append("中间红柱没有完成回抽0轴，不能确认金叉买点")
        if not near_golden_cross:
            failures.append(f"黄白线尚未收敛到金叉附近，DIF={dif_value:.5f}, DEA={dea_value:.5f}, 买入间距={buy_gap:.5f}")
        if not buy_lines_position_ok:
            failures.append("该策略要求买点出现时DIF/DEA位于0轴上方，当前未满足")
        if not current_segment_turning_down:
            failures.append("第二片绿柱还未出现由放大转缩短的动作")
        if in_position:
            failures.append("当前K线前策略仍处于持仓状态，金叉买点要求空仓")
        if buy_program is None:
            failures.append("当前还没有建立到对应的买点观察程序")
        elif buy_program.get("invalidated"):
            failures.append("当前买点程序已经失效")
        if not (current.area < first.area):
            failures.append(f"金叉买点要求第二片绿柱面积 < 第一片绿柱面积；当前分别为 {current.area:.5f} 和 {first.area:.5f}")
        evaluations.append(_make_eval("buy", "golden_cross_buy", "MACD金叉买点", "not_matched", _join_failures("当前K线不满足MACD金叉买点。", [item for item in failures if item])))

    matched_reason = _first_matched_reason(matched_signals, "buy", _macd_reason_matcher("retry_buy"))
    if matched_reason:
        evaluations.append(_make_eval("buy", "retry_buy", "MACD背驰重试买点", "matched", matched_reason))
    else:
        failures = []
        if in_position:
            failures.append("当前K线前策略仍在持仓，重试买点必须发生在止损退出之后的空仓阶段")
        if buy_program is None:
            failures.append("当前没有处于背驰买点观察程序中")
        elif not buy_program.get("retry_pending"):
            failures.append("当前没有处于止损后的重试观察窗口")
        elif buy_program.get("retry_count", 0) >= strategy._max_retry_attempts():
            failures.append(f"重试次数已达到上限 {strategy._max_retry_attempts()} 次")
        if not is_buy_pattern:
            failures.append(f"当前柱体结构是 {pattern_text}，重试买点仍要求绿柱-红柱-绿柱结构")
        if not near_golden_cross:
            failures.append(f"黄白线还没有再次收敛到金叉附近，买入间距={buy_gap:.5f}")
        if buy_pullback_required and not buy_middle_pullback_to_zero_ok:
            failures.append("中间红柱未完成回抽0轴")
        if buy_program is not None and not buy_program.get("invalidated"):
            retry_reference_hist_abs = float(buy_program.get("retry_reference_hist_abs", float("inf")))
            retry_reference_buy_gap = float(buy_program.get("retry_reference_buy_gap", float("inf")))
            first_entry_zero_axis_distance = float(buy_program.get("first_entry_zero_axis_distance", float("inf")))
            if not (current.area < first.area):
                failures.append(f"重试买点要求第二片绿柱面积 < 第一片绿柱面积；当前分别为 {current.area:.5f} 和 {first.area:.5f}")
            if not (abs(hist_values[current_index]) < retry_reference_hist_abs):
                failures.append(f"当前绿柱绝对值 {abs(hist_values[current_index]):.5f} 没有比上次止损参考值 {retry_reference_hist_abs:.5f} 更小")
            if not (buy_gap < retry_reference_buy_gap):
                failures.append(f"当前买入间距 {buy_gap:.5f} 没有比上次参考间距 {retry_reference_buy_gap:.5f} 更收敛")
            zero_axis_distance = strategy._zero_axis_distance(dif_value, dea_value)
            if not (zero_axis_distance < first_entry_zero_axis_distance):
                failures.append(f"当前离0轴距离 {zero_axis_distance:.5f} 没有比第一次入场时的 {first_entry_zero_axis_distance:.5f} 更近")
        evaluations.append(_make_eval("buy", "retry_buy", "MACD背驰重试买点", "not_matched", _join_failures("当前K线不满足MACD背驰重试买点。", [item for item in failures if item])))

    matched_reason = _first_matched_reason(matched_signals, "buy", _macd_reason_matcher("second_green_chase_buy"))
    if matched_reason:
        evaluations.append(_make_eval("buy", "second_green_chase_buy", "第二个绿柱后追高买点", "matched", matched_reason))
    else:
        failures = []
        if in_position:
            failures.append("当前K线前策略已经持仓，追高买点要求空仓")
        if len(completed_segments) < 3 or current_sign != 1:
            failures.append("当前还没有进入第二个绿柱后的首根红柱场景")
        else:
            chase_first = completed_segments[-3]
            chase_middle = completed_segments[-2]
            chase_second_green = completed_segments[-1]
            second_green_bar_count = chase_second_green.end - chase_second_green.start + 1
            second_green_distance_pct = (
                (price - chase_second_green.low_min) / chase_second_green.low_min
                if chase_second_green.low_min > 0 else np.inf
            )
            if not (chase_first.sign == -1 and chase_middle.sign == 1 and chase_second_green.sign == -1):
                failures.append(
                    f"最近三段已完成柱体结构为 {_segment_name(chase_first.sign)}-{_segment_name(chase_middle.sign)}-{_segment_name(chase_second_green.sign)}，不属于追高买点要求的绿红绿完成结构"
                )
            if current.start != current_index:
                failures.append("追高买点只在第二个绿柱后出现首根红柱的当根K线上触发")
            if not (second_green_bar_count <= strategy._post_second_green_max_bars()):
                failures.append(
                    f"第二个绿柱长度为 {second_green_bar_count} 根，超过允许的 {strategy._post_second_green_max_bars()} 根"
                )
            if not (dif_value > dea_value):
                failures.append(f"当前黄白线尚未形成金叉，DIF={dif_value:.5f}, DEA={dea_value:.5f}")
            if not (second_green_distance_pct <= strategy._post_second_green_chase_buy_distance_pct()):
                failures.append(
                    f"当前价格距离第二个绿柱低点约 {second_green_distance_pct * 100:.2f}%，超过允许的 {strategy._post_second_green_chase_buy_distance_pct() * 100:.2f}%"
                )
        evaluations.append(_make_eval("buy", "second_green_chase_buy", "第二个绿柱后追高买点", "not_matched", _join_failures("当前K线不满足第二个绿柱后追高买点。", [item for item in failures if item])))

    matched_reason = _first_matched_reason(matched_signals, "buy", _macd_reason_matcher("reentry_buy"))
    if matched_reason:
        evaluations.append(_make_eval("buy", "reentry_buy", "卖点失效追高买回", "matched", matched_reason))
    else:
        failures = []
        if in_position:
            failures.append("当前K线前策略仍在持仓，买回点只能出现在卖出后的空仓阶段")
        if reentry_watch is None:
            failures.append("当前前面没有刚出现可用于买回观察的卖点")
        else:
            distance = current_index - int(reentry_watch.get("sell_bar_index", current_index))
            if distance > strategy._sell_reentry_max_bars():
                failures.append(
                    f"距离最近卖点已过去 {distance} 根K线，超过允许的 {strategy._sell_reentry_max_bars()} 根"
                )
        if not (current.sign == 1 and current.start == current_index):
            failures.append("买回点要求当前这根K线正好是新红柱启动的首根K线")
        evaluations.append(_make_eval("buy", "reentry_buy", "卖点失效追高买回", "not_matched", _join_failures("当前K线不满足卖点失效追高买回。", [item for item in failures if item])))

    matched_reason = _first_matched_reason(matched_signals, "sell", _macd_reason_matcher("divergence_sell"))
    if matched_reason:
        evaluations.append(_make_eval("sell", "divergence_sell", "MACD背驰卖点", "matched", matched_reason))
    else:
        failures = []
        is_sell_pattern = first.sign == 1 and middle.sign == -1 and current.sign == 1
        sell_area_ok = current.area < first.area
        if not is_sell_pattern:
            failures.append(f"当前柱体结构是 {pattern_text}，背驰卖点要求红柱-绿柱-红柱结构")
        if sell_pullback_required and not sell_middle_pullback_to_zero_ok:
            failures.append("第一段红柱和中间绿柱位于0轴上方时，中间绿柱需要回抽0轴；当前未完成回抽")
        if not near_dead_cross:
            failures.append(f"黄白线还没有进入死叉收敛区，DIF={dif_value:.5f}, DEA={dea_value:.5f}, 卖出间距={sell_gap:.5f}")
        if not sell_area_ok:
            failures.append(f"第二段红柱面积 {current.area:.5f} 没有小于第一段红柱面积 {first.area:.5f}")
        if in_position is False:
            failures.append("当前K线前策略并未持仓，背驰卖点通常发生在持仓退出场景")
        if sell_segment_start == current.start:
            failures.append("这一段红柱已经触发过一次卖点，当前K线不会重复记同类卖点")
        evaluations.append(_make_eval("sell", "divergence_sell", "MACD背驰卖点", "not_matched", _join_failures("当前K线不满足MACD背驰卖点。", [item for item in failures if item])))

    if stop_reference is not None:
        entry_price = float(stop_reference["entry_price"])
        entry_green_area = float(stop_reference.get("entry_green_area", 0.0))
        entry_buy_gap = float(stop_reference.get("entry_buy_gap", 0.0))
        first_green_area = float(stop_reference.get("first_green_area", 0.0))
        first_green_low = float(stop_reference.get("first_green_low", 0.0))
        second_green_start = int(stop_reference.get("second_green_start", -1))
        entry_reference_low = float(stop_reference.get("entry_reference_low", 0.0))
        chase_red_low = stop_reference.get("post_second_green_first_red_low")
        hard_stop_loss_price = entry_price * (1 - strategy._hard_stop_loss_pct()) if entry_price > 0 else 0.0
        adjacent_red_sell_enabled = bool(stop_reference.get("adjacent_red_sell_enabled", False))
        adjacent_red_baseline_start = int(stop_reference.get("adjacent_red_baseline_start", -1))
        adjacent_red_baseline_area = float(stop_reference.get("adjacent_red_baseline_area", 0.0))
        large_red_after_entry_seen = bool(stop_reference.get("large_red_after_entry_seen"))
        large_red_after_entry_start = int(stop_reference.get("large_red_after_entry_start", -1))
    else:
        entry_price = 0.0
        entry_green_area = 0.0
        entry_buy_gap = 0.0
        first_green_area = 0.0
        first_green_low = 0.0
        second_green_start = -1
        entry_reference_low = 0.0
        chase_red_low = None
        hard_stop_loss_price = 0.0
        adjacent_red_sell_enabled = False
        adjacent_red_baseline_start = -1
        adjacent_red_baseline_area = 0.0
        large_red_after_entry_seen = False
        large_red_after_entry_start = -1

    def _sell_eval(point_key: str, point_name: str, fail_list: list[str]) -> dict:
        return matched_or(point_key, "sell", point_name, _join_failures(f"当前K线不满足{point_name}。", [item for item in fail_list if item]))

    failures = []
    if not in_position:
        failures.append("硬止损卖点要求当前这根K线前策略已经持仓")
    else:
        if not (low_value <= hard_stop_loss_price):
            failures.append(f"当前最低价 {low_value:.5f} 还没有跌到统一止损价 {hard_stop_loss_price:.5f}")
        if not (price <= hard_stop_loss_price):
            failures.append(f"当前收盘价 {price:.5f} 还没有收在统一止损线 {hard_stop_loss_price:.5f} 下方")
    evaluations.append(_sell_eval("hard_stop_sell", "硬止损卖点", failures))

    failures = []
    if not in_position:
        failures.append("追高卖点要求当前这根K线前策略已经持仓")
    if not adjacent_red_sell_enabled:
        failures.append("当前持仓不是由追高买点建立，因此不启用相邻红柱追高卖点")
    if not (first.sign == 1 and middle.sign == -1 and current.sign == 1):
        failures.append(f"当前柱体结构是 {pattern_text}，追高卖点要求红柱-绿柱-红柱")
    if first.start != adjacent_red_baseline_start:
        failures.append("当前这段红柱不是和入场后基准红柱做相邻比较的那一组")
    if not (current.area < adjacent_red_baseline_area):
        failures.append(f"当前红柱面积 {current.area:.5f} 没有小于前一片红柱面积 {adjacent_red_baseline_area:.5f}")
    if not near_dead_cross:
        failures.append(f"黄白线还没有再次收敛到死叉附近，卖出间距={sell_gap:.5f}")
    if not current_segment_turning_down:
        failures.append("当前红柱还没有开始缩短")
    if sell_segment_start == current.start:
        failures.append("这一片红柱已经触发过一次卖点")
    evaluations.append(_sell_eval("adjacent_red_chase_sell", "追高卖点", failures))

    failures = []
    if not in_position:
        failures.append("该止损卖点要求当前这根K线前策略已经持仓")
    if chase_red_low is None:
        failures.append("当前持仓并不是第二个绿柱后追高买入形成的仓位，因此不存在首根红柱低点止损线")
    elif not (low_value < float(chase_red_low)):
        failures.append(f"当前最低价 {low_value:.5f} 还没有跌破首根红柱低点 {float(chase_red_low):.5f}")
    evaluations.append(_sell_eval("red_low_break_sell", "跌破首根红柱低点止损卖点", failures))

    failures = []
    if not in_position:
        failures.append("该止损卖点要求当前这根K线前策略已经持仓")
    if not (current.sign == -1):
        failures.append("当前不是绿柱区，不能判断DIF/DEA重新远离止损")
    if current.start != second_green_start:
        failures.append("该卖点只监控买入所在的第二段绿柱内部")
    if current_index < 1 or strategy._sign(hist_values[current_index]) != -1 or strategy._sign(hist_values[current_index - 1]) != -1:
        failures.append("当前还没有形成连续两根绿柱来确认重新远离")
    elif not strategy._hist_bar_expanding(hist_values, current_index, -1):
        failures.append("当前绿柱没有继续放大")
    if not (current.area > entry_green_area * 1.15):
        failures.append(f"当前绿柱面积 {current.area:.5f} 还没有明显大于入场绿柱面积 {entry_green_area:.5f}")
    buy_gap_threshold = max(abs(price) * strategy.buy_cross_gap_pct, 0.0005)
    if not (buy_gap > entry_buy_gap + buy_gap_threshold):
        failures.append(f"当前买入间距 {buy_gap:.5f} 没有明显大于入场间距 {entry_buy_gap:.5f}")
    evaluations.append(_sell_eval("gap_expand_sell", "DIF/DEA重新远离止损卖点", failures))

    failures = []
    short_red_bar_count = middle.end - middle.start + 1
    if not in_position:
        failures.append("该止损卖点要求当前这根K线前策略已经持仓")
    if not (first.sign == -1 and middle.sign == 1 and current.sign == -1):
        failures.append(f"当前柱体结构是 {pattern_text}，该卖点要求绿柱-红柱-绿柱")
    if first.start != second_green_start:
        failures.append("该卖点要求当前第一片绿柱正是买入所在的第二段绿柱")
    if not (1 <= short_red_bar_count <= 3):
        failures.append(f"中间短红柱根数为 {short_red_bar_count}，不在 1 到 3 根范围内")
    if current.start == second_green_start:
        failures.append("当前仍处于买入所在的同一片绿柱内，还没进入后续反扑绿柱")
    if not (current.area > entry_green_area):
        failures.append(f"新绿柱面积 {current.area:.5f} 还没有大于买点所在绿柱参考面积 {entry_green_area:.5f}")
    evaluations.append(_sell_eval("short_red_rebound_sell", "短红柱后新绿柱放大止损卖点", failures))

    failures = []
    if not in_position:
        failures.append("该止损卖点要求当前这根K线前策略已经持仓")
    if not (current.sign == -1):
        failures.append("当前不是绿柱区")
    if current.start != second_green_start:
        failures.append("该卖点只监控买入所在的第二段绿柱内部")
    if not (current.area * 2 > first_green_area):
        failures.append(f"当前第二段绿柱面积x2={current.area * 2:.5f} 还没有超过第一段绿柱面积 {first_green_area:.5f}")
    evaluations.append(_sell_eval("double_area_sell", "第二段绿柱面积翻倍止损卖点", failures))

    failures = []
    if not in_position:
        failures.append("该止损卖点要求当前这根K线前策略已经持仓")
    if not large_red_after_entry_seen:
        failures.append("前面还没有出现红柱放大的失效预警")
    if not (current.sign == -1):
        failures.append("当前不是新一轮绿柱")
    if current.start == second_green_start:
        failures.append("当前仍是买入所在的第二段绿柱，不属于后续反扑绿柱")
    if not (current.start > large_red_after_entry_start):
        failures.append("当前这片绿柱还没有出现在大红柱预警之后")
    if not (current.area > entry_green_area):
        failures.append(f"当前新绿柱面积 {current.area:.5f} 还没有大于买入区绿柱面积 {entry_green_area:.5f}")
    if not (price < entry_price):
        failures.append(f"当前价格 {price:.5f} 还没有低于买入价 {entry_price:.5f}")
    evaluations.append(_sell_eval("post_large_red_sell", "红柱放大后新绿柱反扑止损卖点", failures))

    failures = []
    stop_pct = strategy._first_green_break_stop_pct()
    if stop_pct is None:
        failures.append("当前策略没有启用跌破第一片绿柱低点止损规则")
    elif not in_position:
        failures.append("该止损卖点要求当前这根K线前策略已经持仓")
    else:
        trigger_price = first_green_low * (1 - stop_pct)
        if not (low_value < trigger_price):
            failures.append(f"当前最低价 {low_value:.5f} 还没有跌破止损位 {trigger_price:.5f}")
    evaluations.append(_sell_eval("first_green_break_sell", "跌破第一片绿柱低点止损卖点", failures))

    failures = []
    if not in_position:
        failures.append("试错退出卖点要求当前这根K线前策略已经持仓")
    if not (current.sign == -1):
        failures.append("当前不是绿柱区")
    if current.start != second_green_start:
        failures.append("该卖点只监控买入所在的第二段绿柱内部")
    if not (low_value < entry_reference_low):
        failures.append(f"当前最低价 {low_value:.5f} 还没有跌破入场参考低点 {entry_reference_low:.5f}")
    evaluations.append(_sell_eval("new_low_exit_sell", "再创新低试错退出卖点", failures))

    return evaluations


def _diagnose_macd_bar(strategy_name: str, df: pd.DataFrame, target_timestamp: int) -> list[dict]:
    strategy = get_backtest_strategy(strategy_name)
    if not isinstance(strategy, BaseMACDChanStrategy):
        return _describe_not_ready_macd(strategy_name, [], "当前策略不是MACD缠论类策略。")

    if df is None or len(df) < strategy.slow + strategy.signal + 20:
        return _describe_not_ready_macd(strategy_name, [], "当前区间K线数量不足，MACD结构还没有完成预热。")

    required_cols = {"close", "low", "high"}
    if not required_cols.issubset(df.columns):
        return _describe_not_ready_macd(strategy_name, [], "诊断所需的K线字段不完整。")

    work_df = df.copy()
    time_col = "datetime" if "datetime" in work_df.columns else "date"
    target_index = _find_target_index(work_df, time_col, target_timestamp)
    if target_index is None:
        return _describe_not_ready_macd(strategy_name, [], "当前K线不在本次可诊断的数据集中。")

    matched_signals = _signals_at_bar(strategy.generate_signals(work_df.copy()), target_timestamp)

    times = work_df[time_col].values
    close = pd.to_numeric(work_df["close"], errors="coerce")
    low = pd.to_numeric(work_df["low"], errors="coerce")
    high = pd.to_numeric(work_df["high"], errors="coerce")

    ema_fast = close.ewm(span=strategy.fast, adjust=False).mean()
    ema_slow = close.ewm(span=strategy.slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=strategy.signal, adjust=False).mean()
    hist = (dif - dea) * 2

    close_vals = close.values
    low_vals = low.values
    high_vals = high.values
    dif_vals = dif.values
    dea_vals = dea.values
    hist_vals = hist.values

    completed_segments: list[_MacdAreaSegment] = []
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

    warmup = strategy.slow + strategy.signal

    for i in range(len(work_df)):
        price = close_vals[i]
        if np.isnan(price) or np.isnan(dif_vals[i]) or np.isnan(dea_vals[i]) or np.isnan(hist_vals[i]):
            if i == target_index:
                return _describe_not_ready_macd(strategy_name, matched_signals, "当前K线的MACD指标仍存在空值，暂时无法细化诊断。")
            continue

        sign = strategy._sign(hist_vals[i], current_sign)
        if current_sign == 0:
            current_sign = sign
            current_start = i
            current_area = abs(hist_vals[i])
            current_low_min = low_vals[i]
            current_high_max = high_vals[i]
        elif sign != current_sign:
            strategy._append_completed_segment(
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
            if i == target_index:
                return _describe_not_ready_macd(strategy_name, matched_signals, "当前K线之前还没形成足够的三段MACD柱体结构，无法落到具体点型。")
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
        near_golden_cross = strategy._near_cross(dif_vals, dea_vals, i, price, "buy")
        near_dead_cross = strategy._near_cross(dif_vals, dea_vals, i, price, "sell")
        buy_lines_position_ok = strategy._buy_lines_position_ok(dif_vals[i], dea_vals[i])
        current_segment_turning_down = strategy._segment_hist_turning_down(hist_vals, current.start, i)
        buy_middle_pullback_to_zero_ok = strategy._segment_pullback_to_zero_ok(
            dif_vals, dea_vals, middle.start, middle.end, price, "buy"
        )
        sell_middle_pullback_to_zero_ok = strategy._segment_pullback_to_zero_ok(
            dif_vals, dea_vals, middle.start, middle.end, price, "sell"
        )
        first_green_below_zero = strategy._segment_lines_all_below_zero(
            dif_vals, dea_vals, first.start, first.end
        )
        buy_pullback_required = first_green_below_zero
        buy_pullback_ok = (not buy_pullback_required) or buy_middle_pullback_to_zero_ok
        structure_above_zero = strategy._segment_lines_all_above_zero(
            dif_vals, dea_vals, first.start, i
        )

        if reentry_watch is not None and current.sign not in (1, -1):
            reentry_watch = None

        if reentry_watch is not None and i - reentry_watch.get("sell_bar_index", i) > strategy._sell_reentry_max_bars():
            reentry_watch = None

        if buy_program is None or buy_program["second_green_start"] != current.start or buy_program["first_green_start"] != first.start:
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

        if i == target_index:
            return _build_macd_evaluations(
                strategy_name,
                strategy,
                matched_signals,
                price=float(price),
                low_value=float(low_vals[i]),
                dif_value=float(dif_vals[i]),
                dea_value=float(dea_vals[i]),
                hist_values=hist_vals,
                current_index=i,
                first=first,
                middle=middle,
                current=current,
                is_buy_pattern=is_buy_pattern,
                near_golden_cross=near_golden_cross,
                near_dead_cross=near_dead_cross,
                buy_lines_position_ok=buy_lines_position_ok,
                current_segment_turning_down=current_segment_turning_down,
                buy_middle_pullback_to_zero_ok=buy_middle_pullback_to_zero_ok,
                sell_middle_pullback_to_zero_ok=sell_middle_pullback_to_zero_ok,
                first_green_below_zero=first_green_below_zero,
                buy_pullback_required=buy_pullback_required,
                buy_pullback_ok=buy_pullback_ok,
                structure_above_zero=structure_above_zero,
                sell_pullback_required=(
                    strategy._segment_lines_all_above_zero(dif_vals, dea_vals, first.start, first.end)
                    and strategy._segment_lines_all_above_zero(dif_vals, dea_vals, middle.start, middle.end)
                ),
                sell_pullback_ok=(
                    (not (
                        strategy._segment_lines_all_above_zero(dif_vals, dea_vals, first.start, first.end)
                        and strategy._segment_lines_all_above_zero(dif_vals, dea_vals, middle.start, middle.end)
                    )) or sell_middle_pullback_to_zero_ok
                ),
                in_position=in_position,
                stop_reference=stop_reference,
                sell_segment_start=sell_segment_start,
                buy_program=buy_program,
                reentry_watch=reentry_watch,
                completed_segments=completed_segments,
                current_sign=current_sign,
            )

        if in_position and stop_reference is not None:
            first_green_area = stop_reference["first_green_area"]
            first_green_low = stop_reference["first_green_low"]
            second_green_start = stop_reference["second_green_start"]
            entry_reference_low = stop_reference["entry_reference_low"]
            entry_price = stop_reference["entry_price"]
            entry_green_area = stop_reference["entry_green_area"]
            entry_buy_gap = stop_reference.get("entry_buy_gap", 0.0)
            first_green_break_stop_pct = strategy._first_green_break_stop_pct()
            chase_red_low = stop_reference.get("post_second_green_first_red_low")
            hard_stop_loss_price = entry_price * (1 - strategy._hard_stop_loss_pct())
            adjacent_red_sell_enabled = stop_reference.get("adjacent_red_sell_enabled", False)
            adjacent_red_baseline_start = stop_reference.get("adjacent_red_baseline_start", -1)
            adjacent_red_baseline_area = stop_reference.get("adjacent_red_baseline_area", 0.0)

            if low_vals[i] <= hard_stop_loss_price:
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
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
                        "sell_gap": strategy._cross_gap(dif_vals[i], dea_vals[i], "sell"),
                        "sell_bar_index": i,
                    }
                    continue

            if chase_red_low is not None and low_vals[i] < chase_red_low:
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
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
                and strategy._hist_bar_expanding(hist_vals, i, -1)
                and current.area > entry_green_area * 1.15
                and strategy._cross_gap(dif_vals[i], dea_vals[i], "buy")
                > entry_buy_gap + max(abs(price) * strategy.buy_cross_gap_pct, 0.0005)
            ):
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
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
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
                    buy_program,
                    dif_vals[i],
                    dea_vals[i],
                    hist_vals[i],
                    allow_retry=(current.sign == -1),
                )
                sell_segment_start = None
                continue

            if current.sign == -1 and current.start == second_green_start and current.area * 2 > first_green_area:
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
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
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
                    buy_program,
                    dif_vals[i],
                    dea_vals[i],
                    hist_vals[i],
                    allow_retry=(current.sign == -1),
                )
                sell_segment_start = None
                continue

            if first_green_break_stop_pct is not None and low_vals[i] < first_green_low * (1 - first_green_break_stop_pct):
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
                    buy_program,
                    dif_vals[i],
                    dea_vals[i],
                    hist_vals[i],
                    allow_retry=(current.sign == -1),
                )
                sell_segment_start = None
                continue

            if current.sign == -1 and current.start == second_green_start and low_vals[i] < entry_reference_low:
                in_position = False
                stop_reference = None
                strategy._set_buy_retry_state(
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
                chase_buy_second_green = completed_segments[-1]
                second_green_bar_count = chase_buy_second_green.end - chase_buy_second_green.start + 1
                second_green_distance_pct = (
                    (price - chase_buy_second_green.low_min) / chase_buy_second_green.low_min
                    if chase_buy_second_green.low_min > 0
                    else np.inf
                )
                chase_buy_ready = (
                    chase_first.sign == -1
                    and chase_middle.sign == 1
                    and chase_buy_second_green.sign == -1
                    and i == current.start
                    and second_green_bar_count <= strategy._post_second_green_max_bars()
                    and dif_vals[i] > dea_vals[i]
                    and second_green_distance_pct <= strategy._post_second_green_chase_buy_distance_pct()
                )

            if chase_buy_ready and chase_buy_second_green is not None:
                in_position = True
                stop_reference = strategy._build_position_reference(
                    entry_price=float(price),
                    entry_reference_low=chase_buy_second_green.low_min,
                    first_green_area=chase_first.area,
                    first_green_low=chase_first.low_min,
                    second_green_start=chase_buy_second_green.start,
                    entry_green_area=chase_buy_second_green.area,
                    entry_buy_gap=strategy._cross_gap(dif_vals[i], dea_vals[i], "buy"),
                    post_second_green_first_red_low=float(low_vals[i]),
                    adjacent_red_sell_enabled=True,
                    adjacent_red_baseline_start=chase_middle.start,
                    adjacent_red_baseline_area=chase_middle.area,
                )
                sell_segment_start = None
                reentry_watch = None
                continue

            if (
                reentry_watch is not None
                and i - reentry_watch.get("sell_bar_index", i) <= strategy._sell_reentry_max_bars()
                and current.sign == 1
                and current.start == i
                and strategy._just_crossed(dif_vals, dea_vals, i, "buy")
            ):
                in_position = True
                stop_reference = strategy._build_position_reference(
                    entry_price=float(price),
                    entry_reference_low=current.low_min,
                    entry_buy_gap=strategy._cross_gap(dif_vals[i], dea_vals[i], "buy"),
                    adjacent_red_sell_enabled=True,
                    adjacent_red_baseline_start=first.start,
                    adjacent_red_baseline_area=first.area,
                )
                sell_segment_start = None
                reentry_watch = None
                continue

            retry_limit_reached = (
                buy_program is not None
                and buy_program["retry_pending"]
                and buy_program.get("retry_count", 0) >= strategy._max_retry_attempts()
            )
            if retry_limit_reached:
                buy_program["retry_pending"] = False
                buy_program["armed"] = False
                buy_program["invalidated"] = True

            allow_retry_buy = (
                buy_program is not None
                and buy_program["has_entry_attempt"]
                and buy_program["retry_pending"]
                and buy_program.get("retry_count", 0) < strategy._max_retry_attempts()
                and current.area < first.area
                and abs(hist_vals[i]) < buy_program.get("retry_reference_hist_abs", float("inf")) - strategy.min_hist
                and strategy._cross_gap(dif_vals[i], dea_vals[i], "buy")
                < buy_program.get("retry_reference_buy_gap", float("inf")) - strategy.min_hist
                and strategy._zero_axis_distance(dif_vals[i], dea_vals[i])
                < buy_program.get("first_entry_zero_axis_distance", float("inf")) - strategy.min_hist
            )
            allow_first_buy = current.area * 2 < first.area
            allow_golden_cross_buy = strategy._just_crossed(dif_vals, dea_vals, i, "buy") and current.area < first.area
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
                stop_reference = strategy._build_position_reference(
                    entry_price=float(price),
                    entry_reference_low=current.low_min,
                    first_green_area=first.area,
                    first_green_low=first.low_min,
                    second_green_start=current.start,
                    entry_green_area=current.area,
                    entry_buy_gap=strategy._cross_gap(dif_vals[i], dea_vals[i], "buy"),
                )
                if not buy_program["has_entry_attempt"]:
                    buy_program["first_entry_zero_axis_distance"] = strategy._zero_axis_distance(dif_vals[i], dea_vals[i])
                buy_program["armed"] = False
                buy_program["has_entry_attempt"] = True
                buy_program["retry_pending"] = False
                if allow_retry_buy:
                    buy_program["retry_count"] = buy_program.get("retry_count", 0) + 1
                reentry_watch = None
                continue

            is_sell_pattern = first.sign == 1 and middle.sign == -1 and current.sign == 1
            first_red_above_zero = strategy._segment_lines_all_above_zero(
                dif_vals, dea_vals, first.start, first.end
            )
            middle_green_above_zero = strategy._segment_lines_all_above_zero(
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
                    "sell_gap": strategy._cross_gap(dif_vals[i], dea_vals[i], "sell"),
                    "sell_bar_index": i,
                }

    return _describe_not_ready_macd(strategy_name, matched_signals, "未能在目标K线上还原完整的MACD诊断上下文。")


def _build_ma_evaluations(
    matched_signals: list,
    *,
    strategy: MABullPullbackBollCoreStrategy,
    i: int,
    price: float,
    low_value: float,
    close_value: float,
    ma5_value: float,
    previous_five_close_avg: Optional[float],
    ma_values: dict[int, pd.Series],
    open_value: float,
    high_value: float,
    in_position: bool,
    entry_price: Optional[float],
    entry_bar_low: Optional[float],
    consecutive_below_ma5: int,
    one_sell_danger_state: Optional[dict],
    reentry_buy_state: Optional[dict],
    active_setups: list[dict],
    macd_sell_filter_reason: Optional[str],
) -> list[dict]:
    evaluations: list[dict] = []

    def matched_or(point_key: str, direction: str, point_name: str, fallback_reason: str) -> dict:
        matched_reason = _first_matched_reason(matched_signals, direction, _ma_reason_matcher(point_key))
        return _make_eval(direction, point_key, point_name, "matched" if matched_reason else "not_matched", matched_reason or fallback_reason)

    def describe_big_bull_definition() -> str:
        if previous_five_close_avg is None or pd.isna(previous_five_close_avg) or previous_five_close_avg <= 0:
            return "当前还无法判断大阳线定义，因为前五根K线平均收盘价不可用。"

        gain_pct = close_value / previous_five_close_avg - 1
        body = close_value - open_value
        upper_shadow = high_value - max(open_value, close_value)
        candle_range = high_value - low_value
        failures: list[str] = []

        if strategy._is_one_price_limit_like_bull(
            open_value,
            high_value,
            low_value,
            close_value,
            previous_five_close_avg,
        ):
            return (
                "当前K线是一字涨停式强势K线，按大阳线触发定义处理："
                f"收盘相对前五根均价涨幅={(gain_pct * 100):.2f}% ，"
                f"前五根均价={previous_five_close_avg:.5f}"
            )

        if body <= 0:
            failures.append(
                f"当前K线不是阳线，开盘={open_value:.5f}，收盘={close_value:.5f}"
            )
        if gain_pct <= strategy.big_bull_vs_prev5_avg_pct:
            failures.append(
                "当前收盘涨幅未超过前五根均价要求，"
                f"当前涨幅={(gain_pct * 100):.2f}% ，"
                f"前五根均价={previous_five_close_avg:.5f}，"
                f"阈值={strategy.big_bull_vs_prev5_avg_pct * 100:.2f}%"
            )
        if candle_range <= strategy.eps:
            failures.append(
                f"当前K线振幅过小，最高={high_value:.5f}，最低={low_value:.5f}"
            )
        elif upper_shadow / candle_range > strategy.max_upper_shadow_range_ratio + strategy.eps:
            failures.append(
                "当前上影线过长，"
                f"上影线={upper_shadow:.5f}，"
                f"整根K线={candle_range:.5f}，"
                f"上影线占比={(upper_shadow / candle_range * 100):.2f}% ，"
                f"允许上限={strategy.max_upper_shadow_range_ratio * 100:.2f}%"
            )

        if failures:
            return "当前K线不属于大阳线触发定义：" + "；".join(failures)

        return (
            "当前K线本身满足大阳线触发定义："
            f"收盘相对前五根均价涨幅={(gain_pct * 100):.2f}% ，"
            f"前五根均价={previous_five_close_avg:.5f}，"
            f"上影线={upper_shadow:.5f}，整根K线={candle_range:.5f}，"
            f"上影线占比={(upper_shadow / candle_range * 100):.2f}%"
        )

    pullback_failures = []
    big_bull_definition_reason = describe_big_bull_definition()
    if in_position:
        pullback_failures.append("当前K线前策略仍处于持仓，观察买点要求空仓")
    eligible_active_setup = None
    for setup in active_setups:
        distance = i - int(setup["trigger_index"])
        if 1 <= distance <= strategy.pullback_max_bars:
            eligible_active_setup = setup
            break

    eligible_distance = None
    if eligible_active_setup is None:
        pullback_failures.append("前面没有处于有效的大阳线观察窗口")
    else:
        eligible_distance = i - int(eligible_active_setup["trigger_index"])
        if eligible_distance > strategy.pullback_max_bars:
            pullback_failures.append(f"距离触发大阳线已经过去 {eligible_distance} 根K线，超过允许的 {strategy.pullback_max_bars} 根")
        elif eligible_distance < strategy.pullback_max_bars:
            pullback_failures.append(f"当前是触发后的第 {eligible_distance} 根K线，买点只在第 {strategy.pullback_max_bars} 根确认")
    if previous_five_close_avg is None or pd.isna(previous_five_close_avg):
        pullback_failures.append("当前还无法计算触发大阳线所需的前五根均价")
    bull_aligned, bull_alignment_failures = strategy._evaluate_ma_bull_alignment(ma_values, i)
    if eligible_active_setup is None and not bull_aligned:
        pullback_failures.append(
            "当前均线没有形成MA多头趋势：" + "；".join(bull_alignment_failures)
        )
    if eligible_active_setup is None:
        pullback_failures.append(big_bull_definition_reason)
    if eligible_active_setup is not None and not strategy._is_bull_pullback_confirmation_bar(open_value, low_value, close_value, ma5_value):
        pullback_failures.append(f"当前K线没有站上MA5或实体轻触MA5，收盘={close_value:.5f}, MA5={ma5_value:.5f}")
    if (
        eligible_active_setup is not None
        and eligible_distance == strategy.pullback_max_bars
        and previous_five_close_avg is not None
        and not pd.isna(previous_five_close_avg)
        and strategy._is_one_price_limit_like_bull(
            open_value,
            high_value,
            low_value,
            close_value,
            previous_five_close_avg,
        )
    ):
        pullback_failures.append("当前确认K线是一字涨停式强势K线，可能无法成交，不作为买点")
    if macd_sell_filter_reason:
        pullback_failures.append(macd_sell_filter_reason)
    evaluations.append(matched_or("pullback_buy", "buy", "大阳回踩MA5确认买点", _join_failures("当前K线不满足大阳回踩MA5确认买点。", [item for item in pullback_failures if item])))

    reentry_failures = []
    if in_position:
        reentry_failures.append("当前K线前策略仍在持仓，追高再买要求先卖出")
    if reentry_buy_state is None:
        reentry_failures.append("前面没有进入卖出后的追高再买观察窗口")
    else:
        distance = i - int(reentry_buy_state["sell_index"])
        if distance > strategy.reentry_buy_window_bars:
            reentry_failures.append(f"距离卖点已过去 {distance} 根K线，超过允许的 {strategy.reentry_buy_window_bars} 根")
        if distance < 1:
            reentry_failures.append("追高再买至少要在卖点之后的下一根K线开始判断")
    if not (close_value > ma5_value + strategy.eps):
        reentry_failures.append(f"当前收盘 {close_value:.5f} 没有重新站上MA5 {ma5_value:.5f}")
    if macd_sell_filter_reason:
        reentry_failures.append(macd_sell_filter_reason)
    evaluations.append(matched_or("reentry_buy", "buy", "卖出后追高再买买点", _join_failures("当前K线不满足卖出后追高再买买点。", [item for item in reentry_failures if item])))

    hard_stop_failures = []
    if not in_position:
        hard_stop_failures.append("硬止损卖点要求当前这根K线前策略已经持仓")
    elif entry_price is not None and entry_bar_low is not None:
        hard_stop_price = entry_price * (1 - strategy.hard_stop_loss_pct)
        if not (low_value < entry_bar_low - strategy.eps):
            hard_stop_failures.append(f"当前最低价 {low_value:.5f} 还没有跌破买入K线低点 {entry_bar_low:.5f}")
        if not (close_value <= hard_stop_price + strategy.eps):
            hard_stop_failures.append(f"当前收盘 {close_value:.5f} 还没有收在统一止损线 {hard_stop_price:.5f} 下方")
    evaluations.append(matched_or("hard_stop_sell", "sell", "硬止损卖点", _join_failures("当前K线不满足硬止损卖点。", [item for item in hard_stop_failures if item])))

    one_sell_failures = []
    if not in_position:
        one_sell_failures.append("一卖确认卖点要求当前这根K线前策略已经持仓")
    if one_sell_danger_state is None:
        one_sell_failures.append("前面没有形成BOLL一卖危险位")
    if consecutive_below_ma5 < strategy.stop_loss_break_ma5_bars:
        one_sell_failures.append(f"当前连续跌破MA5仅有 {consecutive_below_ma5} 根，尚未达到 {strategy.stop_loss_break_ma5_bars} 根")
    evaluations.append(matched_or("one_sell_confirm_sell", "sell", "一卖确认卖点", _join_failures("当前K线不满足一卖确认卖点。", [item for item in one_sell_failures if item])))

    ma5_break_failures = []
    if not in_position:
        ma5_break_failures.append("连续跌破MA5止损卖点要求当前这根K线前策略已经持仓")
    if consecutive_below_ma5 < strategy.stop_loss_break_ma5_bars:
        ma5_break_failures.append(f"当前连续跌破MA5仅有 {consecutive_below_ma5} 根，尚未达到 {strategy.stop_loss_break_ma5_bars} 根")
    evaluations.append(matched_or("ma5_break_sell", "sell", "连续跌破MA5止损卖点", _join_failures("当前K线不满足连续跌破MA5止损卖点。", [item for item in ma5_break_failures if item])))

    return evaluations


def _diagnose_ma_bull_bar(df: pd.DataFrame, target_timestamp: int) -> list[dict]:
    strategy = MABullPullbackBollCoreStrategy()
    if df is None or len(df) < strategy.min_bars:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "当前区间K线数量不足，均线/BOLL结构还没有准备好。")
            for direction, point_key, point_name in MA_BULL_POINT_CATALOG
        ]

    work_df = df.copy()
    time_col = "datetime" if "datetime" in work_df.columns else "date"
    if time_col not in work_df.columns:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "诊断所需K线时间字段缺失。")
            for direction, point_key, point_name in MA_BULL_POINT_CATALOG
        ]

    for col in ("open", "high", "low", "close"):
        work_df[col] = pd.to_numeric(work_df[col], errors="coerce")
    work_df = work_df.dropna(subset=[time_col, "open", "high", "low", "close"]).reset_index(drop=True)
    target_index = _find_target_index(work_df, time_col, target_timestamp)
    if target_index is None:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "当前K线不在本次可诊断的数据集中。")
            for direction, point_key, point_name in MA_BULL_POINT_CATALOG
        ]

    matched_signals = _signals_at_bar(strategy.generate_signals(work_df.copy()), target_timestamp)

    times = work_df[time_col].values
    open_values = work_df["open"]
    high_values = work_df["high"]
    low_values = work_df["low"]
    close_values = work_df["close"]
    ma_values = {period: close_values.rolling(window=period).mean() for period in strategy.ma_periods}
    boll_mid = close_values.rolling(window=strategy.boll_period).mean()
    boll_std = close_values.rolling(window=strategy.boll_period).std(ddof=0)
    boll_upper = boll_mid + strategy.boll_nbdev * boll_std
    from backend.strategy_core import MACDChanClassicSignals
    macd_sell_filter_reasons = MACDChanClassicSignals().reasons_for_df(work_df)

    active_setups: list[dict] = []
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
        ma5_value = float(ma_values[5].iloc[i]) if not pd.isna(ma_values[5].iloc[i]) else float("nan")
        previous_five_close_avg = float(close_values.iloc[i - 5:i].mean()) if i >= 5 else None

        if i == target_index:
            return _build_ma_evaluations(
                matched_signals,
                strategy=strategy,
                i=i,
                price=close_value,
                low_value=low_value,
                close_value=close_value,
                ma5_value=ma5_value,
                previous_five_close_avg=previous_five_close_avg,
                ma_values=ma_values,
                open_value=open_value,
                high_value=high_value,
                in_position=in_position,
                entry_price=entry_price,
                entry_bar_low=entry_bar_low,
                consecutive_below_ma5=consecutive_below_ma5,
                one_sell_danger_state=one_sell_danger_state,
                reentry_buy_state=reentry_buy_state,
                active_setups=active_setups,
                macd_sell_filter_reason=(
                    macd_sell_filter_reasons[i]
                    if i < len(macd_sell_filter_reasons)
                    else None
                ),
            )

        if in_position:
            if entry_price is not None and entry_price > 0 and entry_bar_low is not None:
                hard_stop_price = entry_price * (1 - strategy.hard_stop_loss_pct)
                broke_entry_bar_low = low_value < entry_bar_low - strategy.eps
                close_below_hard_stop = close_value <= hard_stop_price + strategy.eps
                if broke_entry_bar_low and close_below_hard_stop:
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
                if one_sell_danger_state is not None and strategy._is_valid_number(upper_value) and close_value > upper_value + strategy.eps:
                    one_sell_danger_state = None
                    consecutive_below_ma5 = 0

                one_sell_signal = None
                if boll_sell_state is not None:
                    one_sell_signal = strategy._get_boll_one_sell_signal(
                        boll_sell_state,
                        high_value,
                        close_value,
                        upper_value,
                    )
                if one_sell_signal is not None:
                    one_sell_danger_state = strategy._create_one_sell_danger_state(
                        signal_time=strategy._format_time(times[i]),
                        previous_high=float(one_sell_signal["previous_high"]),
                        boll_upper=float(one_sell_signal["boll_upper"]),
                    )

            if strategy._is_valid_number(ma5_value) and close_value < ma5_value - strategy.eps:
                consecutive_below_ma5 += 1
            else:
                consecutive_below_ma5 = 0

            if consecutive_below_ma5 >= strategy.stop_loss_break_ma5_bars:
                sell_time = strategy._format_time(times[i])
                in_position = False
                entry_index = None
                entry_price = None
                entry_bar_low = None
                consecutive_below_ma5 = 0
                boll_sell_state = None
                reentry_buy_state = (
                    strategy._create_reentry_buy_state(i, sell_time)
                    if one_sell_danger_state is not None
                    else None
                )
                one_sell_danger_state = None
                active_setups = []
                continue
            continue

        if reentry_buy_state is not None:
            distance_from_sell = i - int(reentry_buy_state["sell_index"])
            if distance_from_sell > strategy.reentry_buy_window_bars:
                reentry_buy_state = None
            elif distance_from_sell >= 1:
                macd_filter_reason = (
                    macd_sell_filter_reasons[i]
                    if i < len(macd_sell_filter_reasons)
                    else None
                )
                if (
                    strategy._is_valid_number(ma5_value)
                    and close_value > ma5_value + strategy.eps
                    and not macd_filter_reason
                ):
                    in_position = True
                    entry_index = i
                    entry_price = close_value
                    entry_bar_low = low_value
                    consecutive_below_ma5 = 0
                    boll_sell_state = strategy._create_boll_sell_state()
                    one_sell_danger_state = None
                    reentry_buy_state = None
                    active_setups = []
                    continue

        if active_setups:
            next_active_setups: list[dict] = []
            pending_buy_setup = None
            for setup in active_setups:
                distance = i - int(setup["trigger_index"])
                if distance > strategy.pullback_max_bars:
                    continue
                if distance < 1:
                    next_active_setups.append(setup)
                    continue
                if not strategy._is_bull_pullback_confirmation_bar(open_value, low_value, close_value, ma5_value):
                    continue
                if distance < strategy.pullback_max_bars:
                    next_active_setups.append(setup)
                    continue
                previous_five_close_avg = float(close_values.iloc[i - 5:i].mean()) if i >= 5 else 0.0
                if strategy._is_one_price_limit_like_bull(
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
                in_position = True
                entry_index = i
                entry_price = close_value
                entry_bar_low = low_value
                consecutive_below_ma5 = 0
                boll_sell_state = strategy._create_boll_sell_state()
                one_sell_danger_state = None
                active_setups = []
                continue

            active_setups = next_active_setups

        if i < 5:
            continue
        previous_five_close_avg = float(close_values.iloc[i - 5:i].mean())
        if (
            strategy._is_valid_number(previous_five_close_avg)
            and strategy._is_ma_bull_aligned(ma_values, i)
            and strategy._is_big_bull_candle(open_value, high_value, low_value, close_value, previous_five_close_avg)
        ):
            active_setups.append({
                "trigger_index": i,
                "trigger_time": strategy._format_time(times[i]),
            })

    return [
        _make_eval(direction, point_key, point_name, "not_matched", "未能在目标K线上还原完整的均线/BOLL诊断上下文。")
        for direction, point_key, point_name in MA_BULL_POINT_CATALOG
    ]


def _build_ma_support_evaluations(
    strategy: MASupportPullbackCoreStrategy,
    matched_signals: list,
    *,
    in_position: bool,
    current_base_period: Optional[int],
    support_streaks: dict,
    establish_windows: dict,
    ma_values: dict,
    recent_high_max,
    i: int,
    close_value: float,
    low_value: float,
) -> list[dict]:
    evaluations: list[dict] = []

    # ---------- 买点：回踩基础均线 ----------
    buy_parts: list[str] = []
    buy_matched = _first_matched_reason(matched_signals, "buy", _ma_support_reason_matcher("pullback_buy"))
    if in_position:
        buy_parts.append("当前K线前策略处于持仓，回踩买点只能在空仓时触发")
    else:
        base = strategy._pick_active_base_period(
            support_streaks=support_streaks,
            establish_windows=establish_windows,
            ma_values=ma_values,
            close_value=close_value,
            index=i,
        )
        if base is None:
            buy_parts.append("当前没有任何均线同时满足：已确认、守住支撑、长周期多头排列、短周期不跌破基础")
        else:
            ma_value = float(ma_values[base].iloc[i])
            if not strategy._is_valid_number(ma_value) or ma_value <= 0:
                buy_parts.append(f"候选基础均线 MA{base} 当前数值无效，无法判定")
            else:
                buy_zone_upper = ma_value * (1 + strategy.pullback_buy_band)
                break_level = ma_value * (1 - strategy.support_buffer)
                recent_high = recent_high_max.iloc[i]
                extended = (
                    strategy._is_valid_number(recent_high)
                    and recent_high >= ma_value * (1 + strategy.entry_extension_ratio) - strategy.eps
                )
                pulled_back = low_value <= buy_zone_upper + strategy.eps
                held = close_value >= break_level - strategy.eps
                chain_text = ">".join(f"MA{p}" for p in strategy._alignment_chain(base))
                buy_parts.append(
                    f"当前唯一基础均线候选=MA{base}（已连续支撑 {support_streaks[base]} 根，确认窗口需 ≥ {establish_windows[base]} 根）"
                )
                if not extended:
                    rh_text = f"{recent_high:.5f}" if strategy._is_valid_number(recent_high) else "无数据"
                    buy_parts.append(
                        f"近 {strategy.entry_extension_lookback} 根高点 {rh_text} 未高出 MA{base} 达 "
                        f"{strategy._format_pct(strategy.entry_extension_ratio)}，未形成\"先离开均线上攻、再回踩\"的结构"
                        f"（MA{base}={ma_value:.5f}）"
                    )
                if not pulled_back:
                    buy_parts.append(
                        f"当前低点 {low_value:.5f} 未回踩到买入带（需 ≤ {buy_zone_upper:.5f}，"
                        f"即 MA{base}×(1+{strategy._format_pct(strategy.pullback_buy_band)})）"
                    )
                if not held:
                    buy_parts.append(f"当前收盘 {close_value:.5f} 跌破支撑缓冲线 {break_level:.5f}，未守住支撑")
                if not strategy._is_longer_bull_aligned(ma_values, base, i):
                    buy_parts.append(f"多头排列校验未通过，要求 {chain_text}")
                if not strategy._is_shorter_above_base(ma_values, base, i):
                    buy_parts.append("比基础均线更短的周期跌破了基础均线")
    evaluations.append(_make_eval(
        "buy", "pullback_buy", "回踩基础均线买点",
        "matched" if buy_matched else "not_matched",
        buy_matched or ("当前K线不满足回踩基础均线买点：" + "；".join(p for p in buy_parts if p)),
    ))

    # ---------- 卖点：跌破基础均线支撑（含卖出后回补切换） ----------
    sell_parts: list[str] = []
    sell_matched = _first_matched_reason(matched_signals, "sell", _ma_support_reason_matcher("support_break_sell"))
    if not in_position:
        sell_parts.append("跌破支撑卖点要求当前这根K线前策略已经持仓")
    else:
        base = current_base_period
        ma_value = float(ma_values[base].iloc[i])
        if not strategy._is_valid_number(ma_value) or ma_value <= 0:
            sell_parts.append(f"基础均线 MA{base} 当前数值无效，无法判定")
        else:
            break_level = ma_value * (1 - strategy.support_buffer)
            broke = close_value < break_level - strategy.eps
            sell_parts.append(
                f"当前基础均线=MA{base}（={ma_value:.5f}），支撑缓冲线={break_level:.5f}"
                f"（=MA{base}×(1-{strategy._format_pct(strategy.support_buffer)})）"
            )
            if not broke:
                short_stop_triggered, short_stop_text = strategy._short_base_stop_triggered(
                    ma_values, base, i
                )
                if short_stop_triggered:
                    sell_parts.append(short_stop_text)
                else:
                    sell_parts.append(f"当前收盘 {close_value:.5f} 仍在支撑缓冲线上方，未跌破支撑")
            else:
                sell_parts.append(
                    f"当前收盘 {close_value:.5f} 跌破 MA{base} 支撑缓冲线，立即按当前基础均线卖出；"
                    f"后续需等待新的正常买点出现后才会再次入场"
                )
    evaluations.append(_make_eval(
        "sell", "support_break_sell", "跌破基础均线支撑卖点",
        "matched" if sell_matched else "not_matched",
        sell_matched or ("当前K线不满足跌破基础均线支撑卖点：" + "；".join(p for p in sell_parts if p)),
    ))

    # ---------- 买点：基础切换回补（跌破旧基础后，按完整基础条件重新成立的新基础回补） ----------
    rebuy_parts: list[str] = []
    rebuy_matched = _first_matched_reason(matched_signals, "buy", _ma_support_reason_matcher("switch_rebuy"))
    if in_position:
        rebuy_parts.append("基础切换回补买点只在跌破旧基础、卖出后又有某条均线按完整基础条件重新成立时触发")
    else:
        rebuy_parts.append("基础切换回补买点要求当前K线先因旧基础跌破卖出，再由新的基础均线立即回补")
    evaluations.append(_make_eval(
        "buy", "switch_rebuy", "基础切换回补买点",
        "matched" if rebuy_matched else "not_matched",
        rebuy_matched or ("当前K线不满足基础切换回补买点：" + "；".join(p for p in rebuy_parts if p)),
    ))

    return evaluations


def _diagnose_ma_support_bar(df: pd.DataFrame, target_timestamp: int) -> list[dict]:
    strategy = MASupportPullbackCoreStrategy()
    if df is None or len(df) < strategy.min_bars:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "当前区间K线数量不足，均线支撑结构还没有准备好。")
            for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
        ]

    work_df = df.copy()
    time_col = "datetime" if "datetime" in work_df.columns else "date"
    if time_col not in work_df.columns:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "诊断所需K线时间字段缺失。")
            for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
        ]

    for col in ("open", "high", "low", "close"):
        work_df[col] = pd.to_numeric(work_df[col], errors="coerce")
    work_df = work_df.dropna(subset=[time_col, "open", "high", "low", "close"]).reset_index(drop=True)
    if len(work_df) < strategy.min_bars:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "清洗后K线数量不足，均线支撑结构还没有准备好。")
            for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
        ]

    target_index = _find_target_index(work_df, time_col, target_timestamp)
    if target_index is None:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "当前K线不在本次可诊断的数据集中。")
            for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
        ]

    matched_signals = _signals_at_bar(strategy.generate_signals(work_df.copy()), target_timestamp)

    high_values = work_df["high"]
    low_values = work_df["low"]
    close_values = work_df["close"]
    ma_values = {period: close_values.rolling(window=period).mean() for period in strategy.all_periods}
    recent_high_max = high_values.rolling(window=strategy.entry_extension_lookback).max().shift(1)
    establish_windows = {period: strategy._establish_window(period) for period in strategy.ma_periods}

    times = work_df[time_col].values
    support_streaks = {period: 0 for period in strategy.ma_periods}
    in_position = False
    current_base_period: Optional[int] = None

    for i in range(len(work_df)):
        high_value = float(high_values.iloc[i])
        low_value = float(low_values.iloc[i])
        close_value = float(close_values.iloc[i])

        if not all(strategy._is_valid_number(v) for v in (high_value, low_value, close_value)):
            for period in strategy.ma_periods:
                support_streaks[period] = 0
            if i == target_index:
                return [
                    _make_eval(direction, point_key, point_name, "not_matched", "当前K线数据异常，无法完成诊断。")
                    for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
                ]
            continue

        for period in strategy.ma_periods:
            ma_value = float(ma_values[period].iloc[i])
            if not strategy._is_valid_number(ma_value) or ma_value <= 0:
                support_streaks[period] = 0
                continue
            break_level = ma_value * (1 - strategy.support_buffer)
            support_streaks[period] = support_streaks[period] + 1 if close_value >= break_level - strategy.eps else 0

        if i == target_index:
            return _build_ma_support_evaluations(
                strategy,
                matched_signals,
                in_position=in_position,
                current_base_period=current_base_period,
                support_streaks=support_streaks,
                establish_windows=establish_windows,
                ma_values=ma_values,
                recent_high_max=recent_high_max,
                i=i,
                close_value=close_value,
                low_value=low_value,
            )

        if in_position and current_base_period is not None:
            # 持仓中：只在未跌破时允许切到更短基础；一旦跌破当前基础，立即卖出，等待下一次正常买点。
            ma_value = float(ma_values[current_base_period].iloc[i])
            if strategy._is_valid_number(ma_value) and ma_value > 0:
                break_level = ma_value * (1 - strategy.support_buffer)
                if close_value < break_level - strategy.eps:
                    in_position = False
                    current_base_period = None
                else:
                    next_base = strategy._pick_active_base_period(
                        support_streaks=support_streaks,
                        establish_windows=establish_windows,
                        ma_values=ma_values,
                        close_value=close_value,
                        index=i,
                    )
                    if next_base is not None and next_base < current_base_period:
                        current_base_period = next_base
            continue

        base_period = strategy._pick_active_base_period(
            support_streaks=support_streaks,
            establish_windows=establish_windows,
            ma_values=ma_values,
            close_value=close_value,
            index=i,
        )
        if base_period is None:
            continue
        ma_value = float(ma_values[base_period].iloc[i])
        if not strategy._is_valid_number(ma_value) or ma_value <= 0:
            continue
        buy_zone_upper = ma_value * (1 + strategy.pullback_buy_band)
        break_level = ma_value * (1 - strategy.support_buffer)
        recent_high = recent_high_max.iloc[i]
        extended_above_ma = (
            strategy._is_valid_number(recent_high)
            and recent_high >= ma_value * (1 + strategy.entry_extension_ratio) - strategy.eps
        )
        pulled_back_to_ma = low_value <= buy_zone_upper + strategy.eps
        held_support = close_value >= break_level - strategy.eps
        longer_aligned = strategy._is_longer_bull_aligned(ma_values, base_period, i)
        shorter_above = strategy._is_shorter_above_base(ma_values, base_period, i)
        if extended_above_ma and pulled_back_to_ma and held_support and longer_aligned and shorter_above:
            in_position = True
            current_base_period = base_period

    return [
        _make_eval(direction, point_key, point_name, "not_matched", "未能在目标K线上还原完整的均线支撑诊断上下文。")
        for direction, point_key, point_name in MA_SUPPORT_POINT_CATALOG
    ]


def build_out_of_range_evaluations(strategy_name: str, range_reason: str) -> list[dict]:
    if strategy_name in {"MACD_CHAN_DIVERGENCE", "MACD_CHAN_THIRD_BUY"}:
        return _build_macd_out_of_range_evaluations(strategy_name, range_reason)
    if strategy_name == "MA_BULL_PULLBACK_BOLL":
        return _build_ma_out_of_range_evaluations(range_reason)
    if strategy_name == "MA_SUPPORT_PULLBACK":
        return _build_ma_support_out_of_range_evaluations(range_reason)
    if strategy_name == "MACD_NON_DIVERGENCE_PULLBACK":
        return [
            _make_eval(direction, point_key, point_name, "out_of_range", range_reason)
            for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
        ]
    return []


def _build_non_divergence_out_of_range_evaluations(range_reason: str) -> list[dict]:
    return [
        _make_eval(direction, point_key, point_name, "out_of_range", range_reason)
        for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
    ]


def _match_non_divergence_reason_to_key(reason: str) -> Optional[str]:
    if reason.startswith("非背驰回抽0轴买点"):
        return "non_divergence_pullback_buy"
    if reason.startswith("止损卖出"):
        return "hard_stop_sell"
    if reason.startswith("零轴止损"):
        return "zero_axis_stop_sell"
    if reason.startswith("背驰卖点"):
        return "divergence_sell"
    return None


def _non_divergence_reason_matcher(point_key: str) -> Callable[[str], bool]:
    return lambda reason: _match_non_divergence_reason_to_key(reason) == point_key


def _diagnose_non_divergence_bar(strategy_name: str, df: pd.DataFrame, target_timestamp: int) -> list[dict]:
    from backend.backtest.strategies.macd_non_divergence_pullback import (
        MACDNonDivergencePullbackBacktestStrategy,
        _MacdSegment,
    )

    strategy = MACDNonDivergencePullbackBacktestStrategy()

    if df is None or len(df) < strategy.slow + strategy.signal + 20:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "当前区间K线数量不足，MACD结构还没有完成预热。")
            for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
        ]

    required_cols = {"close", "low", "high"}
    if not required_cols.issubset(df.columns):
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "诊断所需的K线字段不完整。")
            for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
        ]

    work_df = df.copy()
    time_col = "datetime" if "datetime" in work_df.columns else "date"
    target_index = _find_target_index(work_df, time_col, target_timestamp)
    if target_index is None:
        return [
            _make_eval(direction, point_key, point_name, "not_matched", "当前K线不在本次可诊断的数据集中。")
            for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
        ]

    matched_signals = _signals_at_bar(strategy.generate_signals(work_df.copy()), target_timestamp)

    close = pd.to_numeric(work_df["close"], errors="coerce")
    low = pd.to_numeric(work_df["low"], errors="coerce")
    high = pd.to_numeric(work_df["high"], errors="coerce")

    ema_fast = close.ewm(span=strategy.fast, adjust=False).mean()
    ema_slow = close.ewm(span=strategy.slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=strategy.signal, adjust=False).mean()
    hist = (dif - dea) * 2

    # 计算布林通道
    boll_mid = close.rolling(window=strategy.boll_period).mean()
    boll_std = close.rolling(window=strategy.boll_period).std(ddof=0)
    boll_upper = boll_mid + strategy.boll_nbdev * boll_std
    boll_lower = boll_mid - strategy.boll_nbdev * boll_std

    close_vals = close.values
    low_vals = low.values
    high_vals = high.values
    dif_vals = dif.values
    dea_vals = dea.values
    hist_vals = hist.values
    boll_upper_vals = boll_upper.values
    boll_lower_vals = boll_lower.values

    completed_segments: list[_MacdSegment] = []
    current_sign = 0
    current_start = -1
    current_area = 0.0
    current_low_min = np.inf
    current_high_max = -np.inf

    in_position = False
    stop_reference = None
    non_div_state = None
    sell_segment_start = None

    warmup = strategy.slow + strategy.signal

    for i in range(len(work_df)):
        price = close_vals[i]
        if np.isnan(price) or np.isnan(dif_vals[i]) or np.isnan(dea_vals[i]) or np.isnan(hist_vals[i]):
            if i == target_index:
                return [
                    _make_eval(direction, point_key, point_name, "not_matched", "当前K线的MACD指标仍存在空值，暂时无法细化诊断。")
                    for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
                ]
            continue

        sign = strategy._sign(hist_vals[i], current_sign)
        if current_sign == 0:
            current_sign = sign
            current_start = i
            current_area = abs(hist_vals[i])
            current_low_min = low_vals[i]
            current_high_max = high_vals[i]
        elif sign != current_sign:
            strategy._append_completed_segment(
                completed_segments, current_sign, current_start, i - 1,
                current_area, current_low_min, current_high_max,
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
            if i == target_index:
                return [
                    _make_eval(direction, point_key, point_name, "not_matched", "当前K线之前还没形成足够的MACD柱体结构，无法诊断。")
                    for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
                ]
            continue

        current = _MacdSegment(
            sign=current_sign, start=current_start, end=i,
            area=float(current_area), low_min=float(current_low_min), high_max=float(current_high_max),
        )

        # 到达目标K线时输出诊断
        if i == target_index:
            evaluations: list[dict] = []
            dif_value = float(dif_vals[i])
            dea_value = float(dea_vals[i])
            low_value = float(low_vals[i])

            def _matched_or(point_key: str, direction: str, point_name: str, fallback_reason: str) -> dict:
                matched_reason = _first_matched_reason(
                    matched_signals, direction, _non_divergence_reason_matcher(point_key)
                )
                return _make_eval(
                    direction, point_key, point_name,
                    "matched" if matched_reason else "not_matched",
                    matched_reason or fallback_reason,
                )

            # 买点诊断
            buy_failures: list[str] = []
            if in_position:
                buy_failures.append("当前K线前策略仍处于持仓，买点要求空仓")
            if non_div_state is None:
                buy_failures.append("当前还没有形成非背驰红柱模式（需要红柱1-绿柱-红柱2，且红柱2面积>红柱1面积+股价突破+黄白线在0轴上方）")
            else:
                second_red = non_div_state["second_red"]
                if current.sign != -1:
                    buy_failures.append(f"当前柱体为{'红柱' if current.sign == 1 else '零轴'}，买点要求在绿柱回调阶段触发")
                else:
                    if current.area >= second_red.area:
                        buy_failures.append(f"当前绿柱回调面积={current.area:.5f} >= 非背驰红柱面积={second_red.area:.5f}，回调面积过大")
                    if not strategy._lines_above_zero(dif_value, dea_value):
                        buy_failures.append(f"当前黄白线不在0轴上方，DIF={dif_value:.5f}, DEA={dea_value:.5f}")
                    pullback_start = non_div_state.get("pullback_start", -1)
                    dud_ok, _ = strategy._check_down_up_down(low_vals, high_vals, pullback_start, i)
                    if not dud_ok:
                        buy_failures.append("回调期间股价还未形成下上下结构（先跌-反弹-再跌）")
                    if not strategy._segment_hist_turning_down(hist_vals, current.start, i):
                        buy_failures.append("当前绿柱还没有过峰值并开始缩短")
                    if not strategy._boll_contraction(boll_upper_vals, boll_lower_vals, i):
                        buy_failures.append("布林通道未收口（最近几根K线上下轨未逐渐靠近）")
            evaluations.append(_matched_or(
                "non_divergence_pullback_buy", "buy", "非背驰回抽0轴买点",
                _join_failures("当前K线不满足非背驰回抽0轴买点。", [f for f in buy_failures if f]),
            ))

            # 零轴止损诊断
            zero_axis_sell_failures: list[str] = []
            if not in_position:
                zero_axis_sell_failures.append("零轴止损要求当前这根K线前策略已经持仓")
            else:
                if dif_value > 0 or dea_value > 0:
                    zero_axis_sell_failures.append(f"黄白线未全部跌破0轴，DIF={dif_value:.5f}, DEA={dea_value:.5f}")
            evaluations.append(_matched_or(
                "zero_axis_stop_sell", "sell", "零轴止损（黄白线跌破0轴）",
                _join_failures("当前K线不满足零轴止损条件。", [f for f in zero_axis_sell_failures if f]),
            ))

            # 背驰卖点诊断
            div_sell_failures: list[str] = []
            if not in_position:
                div_sell_failures.append("背驰卖点要求当前这根K线前策略已经持仓")
            else:
                if len(completed_segments) < 2:
                    div_sell_failures.append(f"已完成柱段不足（{len(completed_segments)}个），无法判断红柱背驰")
                else:
                    first_seg = completed_segments[-2]
                    middle_seg = completed_segments[-1]
                    # 输出柱段详情帮助调试
                    seg_info = f"柱段详情: 已完成段数={len(completed_segments)}, "
                    for idx, seg in enumerate(completed_segments[-4:] if len(completed_segments) >= 4 else completed_segments):
                        seg_info += f"seg[{idx}]={'红柱' if seg.sign==1 else '绿柱'}面积={seg.area:.5f}(start={seg.start},end={seg.end}), "
                    seg_info += f"当前段={'红柱' if current.sign==1 else '绿柱'}面积={current.area:.5f}(start={current.start},end={current.end})"
                    div_sell_failures.append(seg_info)

                    if not (first_seg.sign == 1 and middle_seg.sign == -1 and current.sign == 1):
                        div_sell_failures.append(f"当前柱体结构不是红-绿-红（first={'红柱' if first_seg.sign==1 else '绿柱'}, middle={'红柱' if middle_seg.sign==1 else '绿柱'}, current={'红柱' if current.sign==1 else '绿柱'}），无法判断背驰卖点")
                    else:
                        # 背驰卖点比较的是当前红柱 vs 非背驰红柱（second_red）
                        second_red_start = stop_reference.get("second_red_start", -1) if stop_reference else -1
                        second_red_area = stop_reference.get("second_red_area", 0.0) if stop_reference else 0.0
                        # 输出比较的柱段信息
                        div_sell_failures.append(f"比较柱段: 当前红柱start={current.start} vs 非背驰红柱start={second_red_start}, 当前红柱面积={current.area:.5f} vs 非背驰红柱面积={second_red_area:.5f}")
                        if current.start == second_red_start:
                            div_sell_failures.append("当前红柱就是非背驰红柱本身，不是买入后新出现的红柱")
                        if current.area >= second_red_area:
                            div_sell_failures.append(f"当前红柱面积={current.area:.5f} >= 非背驰红柱面积={second_red_area:.5f}，未形成背驰")
                        near_dead = strategy._near_dead_cross(dif_vals, dea_vals, i, price)
                        if not near_dead:
                            div_sell_failures.append(f"黄白线还没有接近死叉，DIF={dif_value:.5f}, DEA={dea_value:.5f}")
                        turning_down = strategy._segment_hist_turning_down(hist_vals, current.start, i)
                        if not turning_down:
                            div_sell_failures.append("当前红柱还没有开始缩小")
            evaluations.append(_matched_or(
                "divergence_sell", "sell", "红柱背驰卖点",
                _join_failures("当前K线不满足红柱背驰卖点。", [f for f in div_sell_failures if f]),
            ))

            return evaluations

        # 持仓止损逻辑（与策略保持一致）
        if in_position and stop_reference is not None:
            entry_price = stop_reference["entry_price"]

            # 止损1: 零轴止损（黄白线都跌破0轴）
            if dif_vals[i] <= 0 and dea_vals[i] <= 0:
                in_position = False
                stop_reference = None
                non_div_state = None
                sell_segment_start = None
                continue

            # 止损2: 红柱背驰卖点
            if len(completed_segments) >= 2:
                first = completed_segments[-2]
                middle = completed_segments[-1]
                second_red_start = stop_reference.get("second_red_start", -1)
                second_red_area = stop_reference.get("second_red_area", 0.0)
                if (
                    first.sign == 1 and middle.sign == -1 and current.sign == 1
                    and current.area < second_red_area
                    and current.start != second_red_start
                    and sell_segment_start != current.start
                ):
                    near_dead = strategy._near_dead_cross(dif_vals, dea_vals, i, price)
                    turning_down = strategy._segment_hist_turning_down(hist_vals, current.start, i)
                    if near_dead and turning_down:
                        sell_segment_start = current.start
                        in_position = False
                        stop_reference = None
                        non_div_state = None
                        continue

            continue

        # 红柱阶段：检测非背驰模式
        if current.sign == 1:
            if len(completed_segments) >= 2:
                seg_1 = completed_segments[-2]
                seg_2 = completed_segments[-1]
                seg_3 = current
                if (
                    seg_1.sign == 1 and seg_2.sign == -1 and seg_3.sign == 1
                    and seg_3.area > seg_1.area
                    and seg_3.high_max > seg_1.high_max
                ):
                    # 只检查股价最高点处黄白线是否在0轴上方
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
                    if not lines_above_zero_at_peak:
                        continue
                    peak_price = -np.inf
                    for idx in range(seg_3.start, seg_3.end + 1):
                        if not np.isnan(high_vals[idx]) and high_vals[idx] > peak_price:
                            peak_price = high_vals[idx]
                    non_div_state = {
                        "first_red": seg_1,
                        "second_red": seg_3,
                        "peak_price": peak_price,
                        "green_pullback_area": 0.0,
                        "green_pullback_start": -1,
                        "buy_triggered": False,
                        "pullback_start": -1,
                    }

            if non_div_state is not None and not non_div_state["buy_triggered"]:
                last_red = non_div_state["second_red"]
                if current.start == last_red.start:
                    if not np.isnan(high_vals[i]) and high_vals[i] > non_div_state["peak_price"]:
                        non_div_state["peak_price"] = high_vals[i]
                    non_div_state["second_red"] = current
            continue

        # 绿柱阶段：买点检测
        if non_div_state is not None and not non_div_state["buy_triggered"]:
            second_red = non_div_state["second_red"]

            if non_div_state["pullback_start"] < 0:
                non_div_state["pullback_start"] = current.start

            if current.area >= second_red.area:
                non_div_state = None
                continue

            if not strategy._lines_above_zero(dif_vals[i], dea_vals[i]):
                non_div_state = None
                continue

            pullback_start = non_div_state["pullback_start"]
            dud_ok, _ = strategy._check_down_up_down(low_vals, high_vals, pullback_start, i)
            if not dud_ok:
                continue

            # 买点条件：下上下结构形成 + 黄白线在0轴之上 + 绿柱开始缩短 + 布林收口
            if strategy._segment_hist_turning_down(hist_vals, current.start, i):
                if strategy._boll_contraction(boll_upper_vals, boll_lower_vals, i):
                    in_position = True
                    stop_reference = {
                        "entry_price": float(price),
                        "first_red_area": non_div_state["first_red"].area,
                        "second_red_area": second_red.area,
                        "first_red_start": non_div_state["first_red"].start,
                        "second_red_start": second_red.start,
                    }
                    non_div_state["buy_triggered"] = True
                    sell_segment_start = None
            continue

    return [
        _make_eval(direction, point_key, point_name, "not_matched", "未能在目标K线上还原完整的诊断上下文。")
        for direction, point_key, point_name in NON_DIVERGENCE_POINT_CATALOG
    ]


def diagnose_strategy_bar(
    strategy_name: str,
    df: pd.DataFrame,
    target_timestamp: int,
    *,
    code: str = "",
    name: str = "",
) -> list[dict]:
    if strategy_name in {"MACD_CHAN_DIVERGENCE", "MACD_CHAN_THIRD_BUY"}:
        return _diagnose_macd_bar(strategy_name, df, target_timestamp)
    if strategy_name == "MA_BULL_PULLBACK_BOLL":
        return _diagnose_ma_bull_bar(df, target_timestamp)
    if strategy_name == "MA_SUPPORT_PULLBACK":
        return _diagnose_ma_support_bar(df, target_timestamp)
    if strategy_name == "MACD_NON_DIVERGENCE_PULLBACK":
        return _diagnose_non_divergence_bar(strategy_name, df, target_timestamp)
    return []
