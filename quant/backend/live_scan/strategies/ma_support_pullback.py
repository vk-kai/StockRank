import pandas as pd

from backend.strategy_core import MASupportPullbackCoreStrategy

from .base import BaseStrategy, Signal


class MASupportPullbackStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("MA_SUPPORT_PULLBACK")
        self._core = MASupportPullbackCoreStrategy()

    def generate_signals(self, df: pd.DataFrame, code: str, name: str) -> list[Signal]:
        return [
            self._create_signal(
                code=code,
                name=name,
                direction=item.direction,
                price=item.price,
                time=item.time,
                reason=item.reason,
            )
            for item in self._core.generate_signals(df)
        ]
