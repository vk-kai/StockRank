import pandas as pd

from backend.backtest.strategies.macd_non_divergence_pullback import (
    MACDNonDivergencePullbackBacktestStrategy,
)

from .base import BaseStrategy, Signal


class MACDNonDivergencePullbackStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("MACD_NON_DIVERGENCE_PULLBACK")
        self._strategy = MACDNonDivergencePullbackBacktestStrategy()

    def generate_signals(self, df: pd.DataFrame, code: str, name: str) -> list[Signal]:
        backtest_signals = self._strategy.generate_signals(df)
        signals = []
        for item in backtest_signals:
            # 买点的趋势质量分(0-100)映射到 strength(0-1),供排序/后续过滤使用;
            # 质量摘要已由策略追加进 reason,扫描卡片hover即可见
            strength = 1.0
            if item.direction == "buy" and isinstance(item.extra, dict):
                quality = item.extra.get("quality") or {}
                score = quality.get("score")
                if isinstance(score, (int, float)):
                    strength = round(max(0.0, min(1.0, float(score) / 100.0)), 3)
            signals.append(
                self._create_signal(
                    code=code,
                    name=name,
                    direction=item.direction,
                    price=item.price,
                    time=item.time,
                    reason=item.reason,
                    strength=strength,
                )
            )
        return signals
