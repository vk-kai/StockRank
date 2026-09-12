import numpy as np
import pandas as pd

from .base import BacktestSignal, BaseBacktestStrategy


class MACDCrossBacktestStrategy(BaseBacktestStrategy):
    name = "MACD_Cross"
    description = "MACD 金叉死叉策略"
    min_bars = 36

    def __init__(self):
        self.fast = 12
        self.slow = 26
        self.signal = 9

    def generate_signals(self, df: pd.DataFrame) -> list[BacktestSignal]:
        if df is None or len(df) < self.min_bars:
            return []

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
        signals: list[BacktestSignal] = []

        for i in range(self.slow + 1, len(df)):
            if np.isnan(dif_vals[i]) or np.isnan(dea_vals[i]):
                continue
            signal_time = (
                pd.Timestamp(times[i]).strftime("%Y-%m-%d %H:%M:%S")
                if not isinstance(times[i], str)
                else times[i]
            )
            if dif_vals[i - 1] <= dea_vals[i - 1] and dif_vals[i] > dea_vals[i]:
                signals.append(
                    self._create_signal(
                        "buy",
                        float(close_vals[i]),
                        signal_time,
                        f"DIF上穿DEA, MACD={macd.iloc[i]:.3f}",
                    )
                )
            elif dif_vals[i - 1] >= dea_vals[i - 1] and dif_vals[i] < dea_vals[i]:
                signals.append(
                    self._create_signal(
                        "sell",
                        float(close_vals[i]),
                        signal_time,
                        f"DIF下穿DEA, MACD={macd.iloc[i]:.3f}",
                    )
                )

        return signals
