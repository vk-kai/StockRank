import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal


class ETFT0Strategy(BaseStrategy):
    def __init__(self):
        super().__init__("ETF_T0_MA_RSI")
        self.ma_fast = 5
        self.ma_slow = 20
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70

    def generate_signals(self, df: pd.DataFrame, code: str, name: str) -> list[Signal]:
        if df is None or len(df) < self.ma_slow + 1:
            return []

        signals = []
        close = df["close"].values
        ma_fast = pd.Series(close).rolling(window=self.ma_fast).mean().values
        ma_slow = pd.Series(close).rolling(window=self.ma_slow).mean().values

        delta = pd.Series(close).diff()
        gain = delta.where(delta > 0, 0).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).values

        time_col = "datetime" if "datetime" in df.columns else "date"
        times = df[time_col].values

        for i in range(self.ma_slow, len(df)):
            if np.isnan(ma_fast[i]) or np.isnan(ma_slow[i]) or np.isnan(rsi[i]):
                continue

            if ma_fast[i - 1] <= ma_slow[i - 1] and ma_fast[i] > ma_slow[i]:
                if rsi[i] < self.rsi_overbought:
                    strength = (self.rsi_overbought - rsi[i]) / self.rsi_overbought
                    signal_time = (
                        pd.Timestamp(times[i]).strftime("%Y-%m-%d %H:%M")
                        if not isinstance(times[i], str)
                        else times[i]
                    )
                    signals.append(
                        self._create_signal(
                            code=code,
                            name=name,
                            direction="buy",
                            price=round(float(close[i]), 3),
                            time=signal_time,
                            reason=f"MA{self.ma_fast}上穿MA{self.ma_slow}, RSI={rsi[i]:.1f}",
                            strength=min(strength, 1.0),
                        )
                    )

            elif ma_fast[i - 1] >= ma_slow[i - 1] and ma_fast[i] < ma_slow[i]:
                if rsi[i] > self.rsi_oversold:
                    strength = (rsi[i] - self.rsi_oversold) / (100 - self.rsi_oversold)
                    signal_time = (
                        pd.Timestamp(times[i]).strftime("%Y-%m-%d %H:%M")
                        if not isinstance(times[i], str)
                        else times[i]
                    )
                    signals.append(
                        self._create_signal(
                            code=code,
                            name=name,
                            direction="sell",
                            price=round(float(close[i]), 3),
                            time=signal_time,
                            reason=f"MA{self.ma_fast}下穿MA{self.ma_slow}, RSI={rsi[i]:.1f}",
                            strength=min(strength, 1.0),
                        )
                    )

        return signals
