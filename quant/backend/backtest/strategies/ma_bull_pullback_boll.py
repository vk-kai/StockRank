from __future__ import annotations

from typing import List

import pandas as pd

from backend.strategy_core import MABullPullbackBollCoreStrategy

from .base import BacktestSignal, BaseBacktestStrategy


class MABullPullbackBollBacktestStrategy(BaseBacktestStrategy):
    name = "MA_BULL_PULLBACK_BOLL"
    description = "MA多头放量阳线"
    min_bars = MABullPullbackBollCoreStrategy.min_bars

    def __init__(self):
        self._core = MABullPullbackBollCoreStrategy()

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
