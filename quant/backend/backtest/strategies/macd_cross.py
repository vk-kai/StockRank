import numpy as np
import pandas as pd

from .base import BacktestSignal, BaseBacktestStrategy, macd_sma_seeded


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

        close_vals = pd.to_numeric(df["close"], errors="coerce").values
        # SMA种子EMA:ewm(adjust=False) 的首值种子在短窗口会残留两位数百分比的偏差
        dif_vals, dea_vals, hist_vals = macd_sma_seeded(
            close_vals, self.fast, self.slow, self.signal
        )

        time_col = "datetime" if "datetime" in df.columns else "date"
        times = df[time_col].values
        signals: list[BacktestSignal] = []

        # DIF 自 i>=slow-1、DEA 自 i>=slow+signal-2 起才收敛,从 slow+signal 起判交叉;
        # 旧实现从 slow+1 起判,前几十根信号被 EMA 种子偏差污染(假金叉/假死叉)
        for i in range(self.slow + self.signal, len(df)):
            if (
                np.isnan(dif_vals[i])
                or np.isnan(dea_vals[i])
                or np.isnan(dif_vals[i - 1])
                or np.isnan(dea_vals[i - 1])
            ):
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
                        f"DIF上穿DEA, MACD={hist_vals[i]:.3f}",
                    )
                )
            elif dif_vals[i - 1] >= dea_vals[i - 1] and dif_vals[i] < dea_vals[i]:
                signals.append(
                    self._create_signal(
                        "sell",
                        float(close_vals[i]),
                        signal_time,
                        f"DIF下穿DEA, MACD={hist_vals[i]:.3f}",
                    )
                )

        return signals
