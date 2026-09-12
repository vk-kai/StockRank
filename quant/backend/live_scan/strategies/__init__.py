from typing import Dict

from backend.config import LIVE_SCAN_STRATEGY_OPTIONS

from .base import BaseStrategy, Signal
from .etf_t0_ma_rsi import ETFT0Strategy
from .ma_bull_pullback_boll import MABullPullbackBollStrategy
from .ma_support_pullback import MASupportPullbackStrategy
from .macd_cross import MACDStrategy
from .macd_chan_divergence import MACDChanDivergenceStrategy
from .macd_chan_third_buy import MACDChanThirdBuyStrategy
from .macd_non_divergence_pullback import MACDNonDivergencePullbackStrategy


STRATEGY_MAP: Dict[str, type[BaseStrategy]] = {
    ETFT0Strategy().name: ETFT0Strategy,
    MABullPullbackBollStrategy().name: MABullPullbackBollStrategy,
    MASupportPullbackStrategy().name: MASupportPullbackStrategy,
    MACDStrategy().name: MACDStrategy,
    MACDChanDivergenceStrategy().name: MACDChanDivergenceStrategy,
    MACDChanThirdBuyStrategy().name: MACDChanThirdBuyStrategy,
    MACDNonDivergencePullbackStrategy().name: MACDNonDivergencePullbackStrategy,
}


def get_strategy(name: str) -> BaseStrategy:
    strategy_cls = STRATEGY_MAP.get(name)
    if strategy_cls is None:
        raise ValueError(f"未知扫描策略: {name}")
    return strategy_cls()


def list_strategies() -> list[dict]:
    configured: list[dict] = []
    seen: set[str] = set()
    for item in LIVE_SCAN_STRATEGY_OPTIONS:
        name = str(item.get("name") or "").strip()
        if not name or name in seen or name not in STRATEGY_MAP:
            continue
        seen.add(name)
        configured.append(
            {
                "name": name,
                "description": str(item.get("description") or name),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return configured


__all__ = [
    "BaseStrategy",
    "Signal",
    "ETFT0Strategy",
    "MABullPullbackBollStrategy",
    "MASupportPullbackStrategy",
    "MACDStrategy",
    "MACDChanDivergenceStrategy",
    "MACDChanThirdBuyStrategy",
    "MACDNonDivergencePullbackStrategy",
    "STRATEGY_MAP",
    "get_strategy",
    "list_strategies",
]
