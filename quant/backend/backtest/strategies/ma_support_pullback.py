from __future__ import annotations

from typing import List

import pandas as pd

from backend.strategy_core import MASupportPullbackCoreStrategy

from .base import BacktestSignal, BaseBacktestStrategy


class MASupportPullbackBacktestStrategy(BaseBacktestStrategy):
    name = "MA_SUPPORT_PULLBACK"
    description = "MA均线支撑回踩做多"
    min_bars = MASupportPullbackCoreStrategy.min_bars

    def __init__(self):
        self._core = MASupportPullbackCoreStrategy()

    def generate_signals(self, df: pd.DataFrame) -> List[BacktestSignal]:
        return [
            self._create_signal(
                direction=item.direction,
                price=item.price,
                time=item.time,
                reason=item.reason,
            )
            for item in self._core.generate_signals(df)
        ]
