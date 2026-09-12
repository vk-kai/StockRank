from typing import Optional

from .macd_chan_base import BaseMACDChanStrategy


class MACDChanThirdBuyBacktestStrategy(BaseMACDChanStrategy):
    name = "MACD_CHAN_THIRD_BUY"
    description = "MACD 缠论三买策略"

    def _require_buy_lines_above_zero(self) -> bool:
        return True

    def _first_green_break_stop_pct(self) -> Optional[float]:
        return 0.01
