from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class BacktestSignal:
    direction: str
    price: float
    time: str
    reason: str
    # 结构化附加信息(如 MACD 买点的趋势质量报告),回测引擎会透传进 trade_records
    extra: Optional[dict] = None


class BaseBacktestStrategy(ABC):
    name = ""
    description = ""
    min_bars = 35

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> List[BacktestSignal]:
        raise NotImplementedError

    def _create_signal(self, direction: str, price: float, time: str, reason: str) -> BacktestSignal:
        return BacktestSignal(
            direction=direction,
            price=round(float(price), 5),
            time=time,
            reason=reason,
        )
