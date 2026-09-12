from typing import Dict, List

from backend.config import LIVE_SCAN_STRATEGY_OPTIONS

from .base import BacktestSignal, BaseBacktestStrategy
from .etf_t0_ma_rsi import ETFT0MARSIBacktestStrategy
from .ma_bull_pullback_boll import MABullPullbackBollBacktestStrategy
from .ma_support_pullback import MASupportPullbackBacktestStrategy
from .macd_chan_divergence import MACDChanDivergenceBacktestStrategy
from .macd_chan_third_buy import MACDChanThirdBuyBacktestStrategy
from .macd_cross import MACDCrossBacktestStrategy
from .macd_non_divergence_pullback import MACDNonDivergencePullbackBacktestStrategy


BACKTEST_STRATEGY_MAP: Dict[str, type[BaseBacktestStrategy]] = {
    MACDCrossBacktestStrategy.name: MACDCrossBacktestStrategy,
    ETFT0MARSIBacktestStrategy.name: ETFT0MARSIBacktestStrategy,
    MABullPullbackBollBacktestStrategy.name: MABullPullbackBollBacktestStrategy,
    MASupportPullbackBacktestStrategy.name: MASupportPullbackBacktestStrategy,
    MACDChanDivergenceBacktestStrategy.name: MACDChanDivergenceBacktestStrategy,
    MACDChanThirdBuyBacktestStrategy.name: MACDChanThirdBuyBacktestStrategy,
    MACDNonDivergencePullbackBacktestStrategy.name: MACDNonDivergencePullbackBacktestStrategy,
}


def get_backtest_strategy(name: str) -> BaseBacktestStrategy:
    strategy_cls = BACKTEST_STRATEGY_MAP.get(name)
    if strategy_cls is None:
        raise ValueError(f"未知回测策略: {name}")
    return strategy_cls()


def get_backtest_strategy_min_bars(name: str) -> int:
    return get_backtest_strategy(name).min_bars


def list_backtest_strategies() -> List[dict]:
    configured: list[dict] = []
    seen: set[str] = set()
    for item in LIVE_SCAN_STRATEGY_OPTIONS:
        name = str(item.get("name") or "").strip()
        strategy_cls = BACKTEST_STRATEGY_MAP.get(name)
        if not name or name in seen or strategy_cls is None:
            continue
        seen.add(name)
        configured.append(
            {
                "name": name,
                "description": str(item.get("description") or strategy_cls.description or name),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return configured


__all__ = [
    "BacktestSignal",
    "BaseBacktestStrategy",
    "ETFT0MARSIBacktestStrategy",
    "MACDCrossBacktestStrategy",
    "MABullPullbackBollBacktestStrategy",
    "MASupportPullbackBacktestStrategy",
    "MACDChanDivergenceBacktestStrategy",
    "MACDChanThirdBuyBacktestStrategy",
    "MACDNonDivergencePullbackBacktestStrategy",
    "get_backtest_strategy",
    "get_backtest_strategy_min_bars",
    "list_backtest_strategies",
]
