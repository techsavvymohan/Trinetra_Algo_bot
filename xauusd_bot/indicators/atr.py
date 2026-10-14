from typing import List, Optional


def true_range(high: List[float], low: List[float], close: List[float]) -> List[float]:
    if not high or not low or not close:
        return []
    n = min(len(high), len(low), len(close))
    if n == 0:
        return []
    tr = [abs(high[0] - low[0])]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr.append(max(hl, hc, lc))
    return tr


def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> Optional[float]:
    if period <= 0 or len(close) < period + 1 or len(high) < period + 1 or len(low) < period + 1:
        return None
    tr = true_range(high, low, close)
    if len(tr) < period + 1:
        return None
    atr_value = sum(tr[1:period + 1]) / period
    for i in range(period + 1, len(tr)):
        atr_value = (atr_value * (period - 1) + tr[i]) / period
    return atr_value


def atr_series(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[float]:
    if period <= 0 or len(close) < period + 1 or len(high) < period + 1 or len(low) < period + 1:
        return []
    tr = true_range(high, low, close)
    if len(tr) < period + 1:
        return []
    result = [sum(tr[1:period + 1]) / period]
    for i in range(period + 1, len(tr)):
        result.append((result[-1] * (period - 1) + tr[i]) / period)
    return result
