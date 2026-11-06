import numpy as np
import pandas as pd

from backend.backtest.strategies.base import macd_sma_seeded

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
        # SMA种子MACD,与回测侧(backend.backtest.strategies.macd_cross)同口径:
        # 实时扫描若用旧ewm(首值种子+从slow+1判交叉),同一标的同一K线的
        # 金叉/死叉会与回测信号对不上(口径分裂,用户对比两端结果时困惑)
        dif_vals, dea_vals, macd_vals = macd_sma_seeded(
            pd.to_numeric(df["close"], errors="coerce").values.astype(float),
            self.fast, self.slow, self.signal
        )
        close_vals = df["close"].values

        time_col = "datetime" if "datetime" in df.columns else "date"
        times = df[time_col].values

        # 与回测侧同起点:slow+signal 起,DIF/DEA 均已收敛
        for i in range(self.slow + self.signal, len(df)):
            if np.isnan(dif_vals[i]) or np.isnan(dea_vals[i]) \
                    or np.isnan(dif_vals[i - 1]) or np.isnan(dea_vals[i - 1]):
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
                        reason=f"DIF上穿DEA, MACD={macd_vals[i]:.3f}",
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
                        reason=f"DIF下穿DEA, MACD={macd_vals[i]:.3f}",
                    )
                )

        return signals
