import numpy as np
import pandas as pd

from .base import BacktestSignal, BaseBacktestStrategy


class ETFT0MARSIBacktestStrategy(BaseBacktestStrategy):
    name = "ETF_T0_MA_RSI"
    description = "ETF T0 均线 RSI 策略"
    min_bars = 35

    def __init__(self):
        self.ma_fast = 5
        self.ma_slow = 20
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70

    def generate_signals(self, df: pd.DataFrame) -> list[BacktestSignal]:
        if df is None or len(df) < self.min_bars:
            return []

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
        signals: list[BacktestSignal] = []

        for i in range(self.ma_slow, len(df)):
            if np.isnan(ma_fast[i]) or np.isnan(ma_slow[i]) or np.isnan(rsi[i]):
                continue
            signal_time = (
                pd.Timestamp(times[i]).strftime("%Y-%m-%d %H:%M:%S")
                if not isinstance(times[i], str)
                else times[i]
            )
            if ma_fast[i - 1] <= ma_slow[i - 1] and ma_fast[i] > ma_slow[i] and rsi[i] < self.rsi_overbought:
                signals.append(
                    self._create_signal(
                        "buy",
                        float(close[i]),
                        signal_time,
                        f"MA{self.ma_fast}上穿MA{self.ma_slow}, RSI={rsi[i]:.1f}",
                    )
                )
            elif ma_fast[i - 1] >= ma_slow[i - 1] and ma_fast[i] < ma_slow[i] and rsi[i] > self.rsi_oversold:
                signals.append(
                    self._create_signal(
                        "sell",
                        float(close[i]),
                        signal_time,
                        f"MA{self.ma_fast}下穿MA{self.ma_slow}, RSI={rsi[i]:.1f}",
                    )
                )

        return signals
