from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Signal:
    code: str
    name: str
    direction: str
    price: float
    time: str
    strategy: str
    reason: str
    strength: float = 1.0


class BaseStrategy(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def generate_signals(self, df, code: str, name: str) -> List[Signal]:
        raise NotImplementedError

    def _create_signal(
        self,
        code: str,
        name: str,
        direction: str,
        price: float,
        time: str,
        reason: str,
        strength: float = 1.0,
    ) -> Signal:
        return Signal(
            code=code,
            name=name,
            direction=direction,
            price=price,
            time=time,
            strategy=self.name,
            reason=reason,
            strength=strength,
        )
