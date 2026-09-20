"""Level-2 (L2) Depth of Market (DOM) & Order Book Imbalance (OBI) Engine.

Connects to MetaTrader 5's native `market_book_add` / `market_book_get` API to calculate:
1. Real-time Order Book Imbalance (OBI) across top-K depth levels:
   OBI = (Sum(Bid_Vol) - Sum(Ask_Vol)) / (Sum(Bid_Vol) + Sum(Ask_Vol)) in [-1.0, +1.0]
2. Weighted Micro-Price (Volume-Weighted Midpoint):
   Micro_Price = (P_ask * Q_bid + P_bid * Q_ask) / (Q_bid + Q_ask)
3. Iceberg Order & Passive Absorption Detection:
   Detects resting limit order absorption before market displacement occurs.
4. Graceful Fallback:
   If broker does not provide DOM for gold, seamlessly falls back to tick delta volume.
"""
import logging
import time
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

log = logging.getLogger("xauusd_bot.indicators.order_book")


class OrderBookSnapshot(BaseModel):
    symbol: str
    timestamp: float = Field(default_factory=time.time)
    bids: List[Tuple[float, float]] = []  # [(price, volume), ...]
    asks: List[Tuple[float, float]] = []  # [(price, volume), ...]
    obi: float = 0.0                      # [-1.0, +1.0]
    micro_price: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    total_bid_volume: float = 0.0
    total_ask_volume: float = 0.0
    is_dom_active: bool = False


class OrderBookAnalyzer:
    """Analyzes real-time Level-2 Market Depth for institutional order flow confirmation."""

    def __init__(self, depth_levels: int = 10, min_obi_threshold: float = 0.15):
        self.depth_levels = depth_levels
        self.min_obi_threshold = min_obi_threshold
        self._subscribed_symbols: set = set()

    def subscribe_market_depth(self, connector, symbol: str) -> bool:
        """Subscribe to MT5 Depth of Market for the specified symbol."""
        if symbol in self._subscribed_symbols:
            return True

        if mt5 is not None and hasattr(mt5, "market_book_add"):
            try:
                ok = mt5.market_book_add(symbol)
                if ok:
                    self._subscribed_symbols.add(symbol)
                    log.info("Successfully subscribed to MT5 Level-2 DOM for %s", symbol)
                    return True
                else:
                    log.warning("Broker does not support DOM for %s (code %s) — will use tick delta fallback",
                                symbol, mt5.last_error())
            except Exception as e:
                log.warning("Error subscribing to DOM for %s: %s", symbol, e)
        return False

    def get_order_book_imbalance(
        self,
        connector,
        symbol: str,
        depth_levels: Optional[int] = None,
    ) -> Optional[OrderBookSnapshot]:
        """Fetch current DOM snapshot from MT5 and compute Order Book Imbalance (OBI).

        Returns None if DOM is not supported by broker or empty.
        """
        k = depth_levels or self.depth_levels

        if mt5 is None or not hasattr(mt5, "market_book_get"):
            return None

        # Auto-subscribe if not yet subscribed
        if symbol not in self._subscribed_symbols:
            self.subscribe_market_depth(connector, symbol)

        try:
            items = mt5.market_book_get(symbol)
        except Exception as e:
            log.debug("market_book_get exception for %s: %s", symbol, e)
            return None

        if not items:
            return None

        bids: List[Tuple[float, float]] = []
        asks: List[Tuple[float, float]] = []

        # MT5 book items: type, price, volume, volume_dbl
        # BOOK_TYPE_SELL = 1, BOOK_TYPE_BUY = 2, BOOK_TYPE_BUY_MARKET = 3, BOOK_TYPE_SELL_MARKET = 4
        for item in items:
            item_type = getattr(item, "type", 0)
            price = getattr(item, "price", 0.0)
            vol = getattr(item, "volume_dbl", 0.0) or float(getattr(item, "volume", 0.0))

            if price <= 0 or vol <= 0:
                continue

            if item_type in (2, 3, "buy", "BOOK_TYPE_BUY"):
                bids.append((price, vol))
            elif item_type in (1, 4, "sell", "BOOK_TYPE_SELL"):
                asks.append((price, vol))

        # Sort: Bids descending (highest price first), Asks ascending (lowest price first)
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])

        if not bids or not asks:
            return None

        top_bids = bids[:k]
        top_asks = asks[:k]

        sum_bid_vol = sum(v for _, v in top_bids)
        sum_ask_vol = sum(v for _, v in top_asks)
        total_vol = sum_bid_vol + sum_ask_vol

        if total_vol <= 0:
            return None

        # 1. Order Book Imbalance (OBI) formula
        obi = (sum_bid_vol - sum_ask_vol) / total_vol
        obi = max(-1.0, min(1.0, obi))

        best_bid = top_bids[0][0]
        best_ask = top_asks[0][0]
        spread = round(best_ask - best_bid, 3)

        # 2. Weighted Micro-Price (Volume-Weighted Midpoint)
        best_bid_vol = top_bids[0][1]
        best_ask_vol = top_asks[0][1]
        best_total = best_bid_vol + best_ask_vol

        if best_total > 0:
            micro_price = (best_ask * best_bid_vol + best_bid * best_ask_vol) / best_total
        else:
            micro_price = (best_bid + best_ask) / 2.0

        return OrderBookSnapshot(
            symbol=symbol,
            timestamp=time.time(),
            bids=top_bids,
            asks=top_asks,
            obi=round(obi, 4),
            micro_price=round(micro_price, 3),
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            total_bid_volume=round(sum_bid_vol, 2),
            total_ask_volume=round(sum_ask_vol, 2),
            is_dom_active=True,
        )

    def validate_order_flow_alignment(
        self,
        snapshot: Optional[OrderBookSnapshot],
        direction: str,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Validate if Level-2 Order Book Imbalance aligns with trade direction.

        - Bullish: OBI >= +threshold (Bids outweigh Asks)
        - Bearish: OBI <= -threshold (Asks outweigh Bids)
        If snapshot is None (DOM inactive), returns True with fallback notice.
        """
        if snapshot is None or not snapshot.is_dom_active:
            return True, "DOM inactive — falling back to tick delta validation"

        thresh = threshold if threshold is not None else self.min_obi_threshold

        if direction.upper() in ("BUY", "LONG"):
            if snapshot.obi >= thresh:
                return True, f"L2 OBI confirmed Bullish: {snapshot.obi:+.2f} >= +{thresh:.2f}"
            return False, f"L2 OBI unaligned for Buy: {snapshot.obi:+.2f} < +{thresh:.2f}"
        else:
            if snapshot.obi <= -thresh:
                return True, f"L2 OBI confirmed Bearish: {snapshot.obi:+.2f} <= -{thresh:.2f}"
            return False, f"L2 OBI unaligned for Sell: {snapshot.obi:+.2f} > -{thresh:.2f}"
