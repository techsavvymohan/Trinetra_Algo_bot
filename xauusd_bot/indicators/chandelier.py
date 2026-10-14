from typing import List, Optional


def chandelier_exit_long(
    high: List[float], low: List[float], close: List[float],
    period: int = 22, multiplier: float = 3.0,
) -> Optional[float]:
    if not high or not low or not close or len(high) < period or len(low) < period or len(close) < period:
        return None
    from .atr import atr
    a = atr(high, low, close, period)
    if a is None:
        return None
    max_high = max(high[-period:])
    return max_high - a * multiplier


def chandelier_exit_short(
    high: List[float], low: List[float], close: List[float],
    period: int = 22, multiplier: float = 3.0,
) -> Optional[float]:
    if not high or not low or not close or len(high) < period or len(low) < period or len(close) < period:
        return None
    from .atr import atr
    a = atr(high, low, close, period)
    if a is None:
        return None
    min_low = min(low[-period:])
    return min_low + a * multiplier
