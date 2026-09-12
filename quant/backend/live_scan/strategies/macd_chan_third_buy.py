import pandas as pd

from backend.backtest.strategies.macd_chan_third_buy import (
    MACDChanThirdBuyBacktestStrategy,
)

from .base import BaseStrategy, Signal


class MACDChanThirdBuyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("MACD_CHAN_THIRD_BUY")
        self._strategy = MACDChanThirdBuyBacktestStrategy()

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
