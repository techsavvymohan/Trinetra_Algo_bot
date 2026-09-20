"""TradingView Technical Analysis Feed.

Uses the official tradingview-ta library to query live TradingView
recommendations, oscillators, moving averages, and indicator metrics
for XAUUSD, USTECH100M, and index symbols.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import threading
import requests

try:
    from tradingview_ta import Interval, TA_Handler
    TV_AVAILABLE = True
except ImportError:
    TV_AVAILABLE = False
    Interval = None
    TA_Handler = None

try:
    from lse import LSE
    LSE_AVAILABLE = True
except ImportError:
    LSE_AVAILABLE = False
    LSE = None


from ..models import Bias

log = logging.getLogger("xauusd_bot.data.tradingview")

# Symbol routing to TradingView screener and exchange
DEFAULT_EXCHANGE_MAP = {
    "XAUUSD": ("OANDA", "cfd"),
    "GOLD": ("OANDA", "cfd"),
    "USTECH100M": ("GLOBALPRIME", "cfd"),
    "NAS100": ("GLOBALPRIME", "cfd"),
    "US100": ("GLOBALPRIME", "cfd"),
}


class TradingViewFeed:
    def __init__(self, cache_ttl_seconds: float = 45.0, enabled: bool = True):
        self.cache_ttl = cache_ttl_seconds
        self.enabled = enabled and TV_AVAILABLE
        self._cache: Dict[str, Tuple[float, Any]] = {}

        if not TV_AVAILABLE:
            log.warning("tradingview-ta library not installed. TradingView feed disabled.")

    @staticmethod
    def map_tf_to_interval(tf: str) -> str:
        if not TV_AVAILABLE:
            return "15m"
        mapping = {
            "M1": Interval.INTERVAL_1_MINUTE,
            "M5": Interval.INTERVAL_5_MINUTES,
            "M15": Interval.INTERVAL_15_MINUTES,
            "M30": Interval.INTERVAL_30_MINUTES,
            "H1": Interval.INTERVAL_1_HOUR,
            "H4": Interval.INTERVAL_4_HOURS,
            "D1": Interval.INTERVAL_1_DAY,
        }
        return mapping.get(tf.upper(), Interval.INTERVAL_15_MINUTES)

    def _get_exchange_screener(self, symbol: str) -> Tuple[str, str]:
        sym = symbol.upper()
        return DEFAULT_EXCHANGE_MAP.get(sym, ("OANDA", "cfd"))

    def get_analysis(self, symbol: str = "XAUUSD", tf: str = "M15") -> Optional[Any]:
        """Fetch analysis object from TradingView with caching."""
        if not self.enabled:
            return None

        cache_key = f"{symbol.upper()}_{tf.upper()}"
        now = time.time()
        if cache_key in self._cache:
            ts, cached_res = self._cache[cache_key]
            if now - ts < self.cache_ttl:
                return cached_res

        exchange, screener = self._get_exchange_screener(symbol)
        interval = self.map_tf_to_interval(tf)

        try:
            handler = TA_Handler(
                symbol=symbol.upper(),
                exchange=exchange,
                screener=screener,
                interval=interval,
                timeout=5.0,
            )
            analysis = handler.get_analysis()
            self._cache[cache_key] = (now, analysis)
            return analysis
        except Exception as exc:
            log.warning("TradingView fetch failed for %s (%s): %s", symbol, tf, exc)
            return None

    def get_recommendation(self, symbol: str = "XAUUSD", tf: str = "M15") -> str:
        """Get summary recommendation: STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL."""
        analysis = self.get_analysis(symbol, tf)
        if not analysis or not hasattr(analysis, "summary"):
            return ""
        return analysis.summary.get("RECOMMENDATION", "")

    def get_bias(self, symbol: str = "XAUUSD", tf: str = "M15") -> Bias:
        """Convert TradingView consensus into Bias enum."""
        rec = self.get_recommendation(symbol, tf)
        if "BUY" in rec:
            return Bias.BULLISH
        elif "SELL" in rec:
            return Bias.BEARISH
        return Bias.NEUTRAL

    def is_sideways(self, symbol: str = "XAUUSD", tf: str = "M15") -> Tuple[bool, str]:
        """Check if TradingView signals sideways / consolidation.

        Returns (True, reason) if TradingView rates market as NEUTRAL or
        neutral indicators dominate.
        """
        analysis = self.get_analysis(symbol, tf)
        if not analysis or not hasattr(analysis, "summary"):
            return False, "no tradingview data"

        summary = analysis.summary
        rec = summary.get("RECOMMENDATION", "")
        neutral_votes = summary.get("NEUTRAL", 0)
        buy_votes = summary.get("BUY", 0)
        sell_votes = summary.get("SELL", 0)
        total_votes = neutral_votes + buy_votes + sell_votes

        if rec == "NEUTRAL" and neutral_votes >= max(buy_votes, sell_votes):
            return True, f"TradingView {tf} Neutral ({neutral_votes}/{total_votes} indicators neutral)"

        return False, f"TradingView trend {rec}"

    def get_indicators(self, symbol: str = "XAUUSD", tf: str = "M15") -> Dict[str, Any]:
        """Retrieve full dictionary of TradingView technical indicators."""
        analysis = self.get_analysis(symbol, tf)
        if not analysis or not hasattr(analysis, "indicators"):
            return {}
        return analysis.indicators or {}


class LSEFeed:
    """London Strategic Edge (LSE) Data Feed & WebSocket Streaming Client.

    Streams live market ticks (bid, ask, price, volume) over WebSockets and
    provides REST API access to institutional historical candles and macro series
    (e.g., US10Y bond yields) via the London Strategic Edge vault.
    """
    def __init__(
        self,
        # FIX: hardcoded default removed — API key MUST come from config (loaded via LSE_API_KEY in .env)
        api_key: str = "",
        ws_url: str = "wss://data-ws.londonstrategicedge.com",
        http_url: str = "https://api.londonstrategicedge.com/vault",
        enabled: bool = True,
    ):
        self.api_key = api_key
        self.ws_url = ws_url
        self.http_url = http_url
        self.enabled = enabled
        self._latest_ticks: Dict[str, dict] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Convert standard symbol notation to LSE catalog format (e.g. XAUUSD -> XAU/USD)."""
        sym = symbol.upper().replace("/", "")
        if sym in ("XAUUSD", "GOLD"):
            return "XAU/USD"
        elif any(n in sym for n in ("USTECH", "NAS", "US100")):
            return "NAS100"
        elif "/" in symbol:
            return symbol
        return symbol

    def start_stream(self, symbols: Optional[List[str]] = None, warmup_hours: float = 0.0):
        """Start background daemon thread streaming live ticks over WebSocket.

        If warmup_hours > 0, replays historical ticks before continuing live.
        """
        if not self.enabled or self._running:
            return
        if not self.api_key:
            log.warning("LSE API key not configured (LSE_API_KEY). Stream disabled.")
            return
        if not LSE_AVAILABLE:
            log.warning("lse-data package not installed. LSE live stream disabled.")
            return

        if symbols is None:
            symbols = ["XAU/USD", "NAS100"]
        else:
            symbols = [self.normalize_symbol(s) for s in symbols]

        start_time = None
        if warmup_hours > 0:
            start_time = (datetime.now(timezone.utc) - timedelta(hours=min(warmup_hours, 24.0))).isoformat()

        self._running = True
        self._thread = threading.Thread(target=self._stream_loop, args=(symbols, start_time), daemon=True)
        self._thread.start()
        log.info("LSE WebSocket streaming thread started for %s (warmup: %s)", symbols, start_time or "live")

    def _stream_loop(self, symbols: List[str], start_time: Optional[str] = None):
        """Internal worker looping over client.stream ticks with auto-reconnect."""
        while self._running:
            try:
                client = LSE(api_key=self.api_key)
                kwargs = {"start": start_time} if start_time else {}
                for tick in client.stream(symbols, **kwargs):
                    if not self._running:
                        break
                    sym = getattr(tick, "symbol", "")
                    with self._lock:
                        self._latest_ticks[sym] = {
                            "symbol": sym,
                            "price": getattr(tick, "price", 0.0),
                            "bid": getattr(tick, "bid", getattr(tick, "price", 0.0)),
                            "ask": getattr(tick, "ask", getattr(tick, "price", 0.0)),
                            "volume": getattr(tick, "volume", 0.0),
                            "timestamp": str(getattr(tick, "timestamp", "")),
                            "replay": getattr(tick, "replay", False),
                            "received_at": time.time(),
                        }
            except Exception as exc:
                if not self._running:
                    break
                log.warning("LSE WebSocket stream disconnected (%s); reconnecting in 5s...", exc)
                # Brief sleep before reconnect — avoids hammering server on repeated failures
                time.sleep(5.0)

    def get_tick(self, symbol: str) -> Optional[dict]:
        """Get latest cached live tick for symbol."""
        norm_sym = self.normalize_symbol(symbol)
        with self._lock:
            return self._latest_ticks.get(norm_sym)

    def get_spread(self, symbol: str) -> Optional[float]:
        """Get current live spread (ask - bid) from LSE tick."""
        tick = self.get_tick(symbol)
        if tick and tick.get("ask") is not None and tick.get("bid") is not None:
            return round(tick["ask"] - tick["bid"], 5)
        return None

    def fetch_candles(self, symbol: str, timeframe: str = "1m", start: str = "") -> List[dict]:
        """Fetch historical candles from LSE HTTP vault."""
        if not self.api_key:
            return []
        norm_sym = self.normalize_symbol(symbol)
        tf_map = {
            "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
            "H1": "1h", "H4": "4h", "D1": "1d",
        }
        lse_tf = tf_map.get(timeframe.upper(), timeframe.lower())
        url = f"{self.http_url}/candles"
        params = {"symbol": norm_sym, "timeframe": lse_tf}
        if start:
            params["start"] = start
        headers = {"x-api-key": self.api_key}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            if resp.status_code == 200:
                return resp.json()
            log.warning("LSE candles HTTP error %d: %s", resp.status_code, resp.text[:100])
        except Exception as exc:
            log.error("LSE candles fetch failed: %s", exc)
        return []

    def fetch_series(self, symbol: str = "US10Y", start: str = "") -> List[dict]:
        """Fetch macro economic/yield series (e.g. US10Y) from LSE HTTP vault."""
        if not self.api_key:
            return []
        url = f"{self.http_url}/series"
        params = {"symbol": symbol.upper()}
        if start:
            params["start"] = start
        headers = {"x-api-key": self.api_key}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            if resp.status_code == 200:
                return resp.json()
            log.warning("LSE series HTTP error %d: %s", resp.status_code, resp.text[:100])
        except Exception as exc:
            log.error("LSE series fetch failed: %s", exc)
        return []

    def get_us10y_yield(self) -> Optional[float]:
        """Return the latest US 10-year Treasury yield value.

        Uses a rolling 90-day lookback to ensure fresh data regardless of
        current year — avoids the hardcoded 2026-01-01 date bug.
        """
        # FIX: was hardcoded to 2026-01-01 — now a rolling 90-day window
        start_dt = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        series = self.fetch_series("US10Y", start=start_dt)
        if series:
            last = series[-1]
            return float(last.get("value", 0.0))
        return None

    def fetch_cot(self, symbol: str = "GC") -> List[dict]:
        """Fetch Commitments of Traders (COT) records from LSE vault."""
        if not self.api_key:
            return []
        url = f"{self.http_url}/ref/cot"
        params = {"symbol": symbol.upper(), "limit": 20}
        headers = {"x-api-key": self.api_key}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            if resp.status_code == 200:
                return resp.json()
            log.warning("LSE COT HTTP error %d: %s", resp.status_code, resp.text[:100])
        except Exception as exc:
            log.error("LSE COT fetch failed: %s", exc)
        return []

    def get_cot_bias(self, symbol: str = "GC") -> str:
        """Analyze non-commercial institutional positioning from COT data.

        Returns 'BULLISH', 'BEARISH', or 'NEUTRAL'.
        """
        records = self.fetch_cot(symbol)
        if not records:
            return "NEUTRAL"
        latest = records[0]
        long_pct = float(latest.get("pct_noncomm_long", 50.0))
        short_pct = float(latest.get("pct_noncomm_short", 50.0))
        if long_pct > short_pct + 10.0:
            return "BULLISH"
        elif short_pct > long_pct + 10.0:
            return "BEARISH"
        return "NEUTRAL"

    def stop(self):
        """Stop background WebSocket stream."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)  # slightly longer join — 1s was too tight on slow teardowns
        log.info("LSE WebSocket feed stopped.")
