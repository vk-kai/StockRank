import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal


class MACDStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("MACD_Cross")
        self.fast = 12
        self.slow = 26
        self.signal = 9

    def generate_signals(self, df: pd.DataFrame, code: str, name: str) -> list[Signal]:
        if df is None or len(df) < self.slow + self.signal:
            return []

        signals = []
        close = pd.Series(df["close"].values)

        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal, adjust=False).mean()
        macd = (dif - dea) * 2

        dif_vals = dif.values
        dea_vals = dea.values
        close_vals = df["close"].values

        time_col = "datetime" if "datetime" in df.columns else "date"
        times = df[time_col].values

        for i in range(self.slow + 1, len(df)):
            if np.isnan(dif_vals[i]) or np.isnan(dea_vals[i]):
                continue

            signal_time = (
                pd.Timestamp(times[i]).strftime("%Y-%m-%d %H:%M")
                if not isinstance(times[i], str)
                else times[i]
            )

            if dif_vals[i - 1] <= dea_vals[i - 1] and dif_vals[i] > dea_vals[i]:
                signals.append(
                    self._create_signal(
                        code=code,
                        name=name,
                        direction="buy",
                        price=round(float(close_vals[i]), 3),
                        time=signal_time,
                        reason=f"DIF上穿DEA, MACD={macd.iloc[i]:.3f}",
                    )
                )
            elif dif_vals[i - 1] >= dea_vals[i - 1] and dif_vals[i] < dea_vals[i]:
                signals.append(
                    self._create_signal(
                        code=code,
                        name=name,
                        direction="sell",
                        price=round(float(close_vals[i]), 3),
                        time=signal_time,
                        reason=f"DIF下穿DEA, MACD={macd.iloc[i]:.3f}",
                    )
                )

        return signals
