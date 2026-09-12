import pandas as pd

from backend.backtest.strategies.macd_chan_divergence import (
    MACDChanDivergenceBacktestStrategy,
)

from .base import BaseStrategy, Signal


class MACDChanDivergenceStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("MACD_CHAN_DIVERGENCE")
        self._strategy = MACDChanDivergenceBacktestStrategy()

    def generate_signals(self, df: pd.DataFrame, code: str, name: str) -> list[Signal]:
        backtest_signals = self._strategy.generate_signals(df)
        return [
            self._create_signal(
                code=code,
                name=name,
                direction=item.direction,
                price=item.price,
                time=item.time,
                reason=item.reason,
            )
            for item in backtest_signals
        ]
