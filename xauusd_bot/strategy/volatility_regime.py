"""
Dynamic Volatility-Regime Engine
=================================
Stateless, data-driven regime classifier that adapts trade parameters
(TP target, breakeven trigger, displacement threshold) to the *current*
market regime detected purely from price structure.

Design principles
-----------------
* **Zero date/month hardcoding** - works identically in backtest, forward
  test, paper trading, and live execution.
* **Stateless per-bar API** - call ``classify(m15_data, m1_data)`` on every
  bar; returns a ``RegimeState`` dataclass with all derived parameters.
* **Three-tier regime** - TRENDING / NEUTRAL / COMPRESSED, mapped from a
  composite score built from ATR-ratio, ADX proxy, and body-ratio.
* **Configurable thresholds** - all magic numbers exposed as dataclass fields
  so they can be overridden via environment variables or config JSON.

Usage (engine.py / main.py)
----------------------------
    from ..strategy.volatility_regime import VolatilityRegimeEngine, RegimeState

    vr_engine = VolatilityRegimeEngine()            # once at startup
    regime = vr_engine.classify(m15_data, m1_data)  # every bar

    target_r      = regime.target_r       # pass to detect_xau_scalp_sequence
    be_trigger_r  = regime.be_trigger_r   # override default breakeven trigger
    min_atr_mult  = regime.min_atr_mult   # stricter displacement gate when choppy
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("xauusd_bot.strategy.volatility_regime")


# ---------------------------------------------------------------------------
# Exported result type
# ---------------------------------------------------------------------------

@dataclass
class RegimeState:
    """Per-bar regime snapshot - all parameters the engine should use."""

    # Classification
    regime: str = "NEUTRAL"          # "TRENDING" | "NEUTRAL" | "COMPRESSED"
    score: float = 0.0               # composite score in [-1, +1]

    # Adapted trade parameters
    target_r: float = 2.0            # TP in R-multiples
    be_trigger_r: float = 1.50       # move SL to BE when price hits this R
    be_buffer_r: float = 0.10        # small profit buffer above entry at BE
    min_atr_mult: float = 0.60       # displacement minimum ATR multiplier
    min_body_ratio: float = 0.60     # displacement minimum body ratio

    # Diagnostics
    atr_ratio: float = 1.0           # current_atr / ema(atr, lookback)
    adx_proxy: float = 25.0          # directional momentum proxy
    body_ratio: float = 0.60         # recent bar body quality


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass
class VolatilityRegimeEngine:
    """
    Classify current market regime from M15 + M1 bar data.

    All thresholds are exposed as fields so they can be overridden
    from environment variables or a JSON config without subclassing.
    """

    # ATR-ratio thresholds
    atr_ema_lookback: int = 50         # EMA period for normalising ATR
    atr_ratio_trending: float = 1.12   # above this -> TRENDING
    atr_ratio_compressed: float = 0.88 # below this -> COMPRESSED (raised from 0.82 — more sensitive)

    # ADX proxy thresholds
    adx_proxy_period: int = 14
    adx_proxy_trending: float = 26.0
    adx_proxy_compressed: float = 22.0   # raised from 18 — choppy summer ADX ~18-22

    # Bar body-quality thresholds
    body_quality_period: int = 10      # bars to average body ratios
    body_quality_trending: float = 0.56
    body_quality_compressed: float = 0.44  # raised from 0.42 — more sensitive

    # Output parameters per regime
    # TRENDING (composite >= 0.25): high-expansion breakout months
    trending_target_r: float = 2.0
    trending_be_trigger_r: float = 1.50
    trending_be_buffer_r: float = 0.10
    trending_min_atr_mult: float = 0.60
    trending_min_body_ratio: float = 0.60

    # NEUTRAL (composite -0.20 to +0.25): optimal baseline standard
    neutral_target_r: float = 2.0
    neutral_be_trigger_r: float = 1.50
    neutral_be_buffer_r: float = 0.10
    neutral_min_atr_mult: float = 0.60
    neutral_min_body_ratio: float = 0.60

    # COMPRESSED (composite <= -0.20): optimal baseline standard
    compressed_target_r: float = 2.0
    compressed_be_trigger_r: float = 1.50
    compressed_be_buffer_r: float = 0.10
    compressed_min_atr_mult: float = 0.60
    compressed_min_body_ratio: float = 0.60


    def classify(self, m15_data, m1_data=None) -> RegimeState:
        """
        Classify the current regime and return adapted trade parameters.

        Parameters
        ----------
        m15_data : TimeframeData  (xauusd_bot.models)
        m1_data  : TimeframeData  (xauusd_bot.models), optional fallback
        """
        atr_ratio = self._atr_ratio(m15_data)
        adx_proxy = self._adx_proxy(m15_data)
        body_ratio = self._body_ratio(m15_data if m15_data else m1_data)

        # Composite score [-1 -> +1]
        # +1 = strongly trending, -1 = strongly compressed
        score_atr = self._normalise(
            atr_ratio,
            self.atr_ratio_compressed, self.atr_ratio_trending,
        )
        score_adx = self._normalise(
            adx_proxy,
            self.adx_proxy_compressed, self.adx_proxy_trending,
        )
        score_body = self._normalise(
            body_ratio,
            self.body_quality_compressed, self.body_quality_trending,
        )
        # Weights: ATR-ratio 50%, ADX 30%, body-quality 20%
        composite = 0.50 * score_atr + 0.30 * score_adx + 0.20 * score_body

        # Regime decision
        if composite >= 0.30:
            regime = "TRENDING"
        elif composite <= -0.25:
            regime = "COMPRESSED"
        else:
            regime = "NEUTRAL"

        target_r, be_trigger, be_buf, min_atr, min_body = self._params(regime)

        state = RegimeState(
            regime=regime,
            score=round(composite, 3),
            target_r=target_r,
            be_trigger_r=be_trigger,
            be_buffer_r=be_buf,
            min_atr_mult=min_atr,
            min_body_ratio=min_body,
            atr_ratio=round(atr_ratio, 3),
            adx_proxy=round(adx_proxy, 2),
            body_ratio=round(body_ratio, 3),
        )
        log.debug(
            "[VolatilityRegime] %s | score=%.3f | atr_ratio=%.3f | adx=%.1f | body=%.3f | "
            "target_r=%.2f | be_trig=%.2f | min_atr=%.2f",
            regime, composite, atr_ratio, adx_proxy, body_ratio,
            target_r, be_trigger, min_atr,
        )
        return state

    # Internal helpers

    def _atr_ratio(self, data) -> float:
        """current_atr / slow_ema(atr, lookback) - measures ATR expansion/contraction."""
        try:
            lb = self.atr_ema_lookback
            need = lb + 20
            closes = data.close[-need:]
            highs  = data.high[-need:]
            lows   = data.low[-need:]
            n = len(closes)
            if n < lb + 5:
                return 1.0

            # True Range series
            tr = []
            for k in range(1, n):
                h, l, pc = highs[k], lows[k], closes[k - 1]
                tr.append(max(h - l, abs(h - pc), abs(l - pc)))

            if len(tr) < lb:
                return 1.0

            # Simple ATR (current - last 14 bars)
            atr_period = min(14, len(tr))
            current_atr = sum(tr[-atr_period:]) / atr_period

            # EMA of TR for the lookback window
            k_ema = 2.0 / (lb + 1)
            ema_val = sum(tr[:lb]) / lb
            for v in tr[lb:]:
                ema_val = v * k_ema + ema_val * (1 - k_ema)

            if ema_val <= 0:
                return 1.0
            return current_atr / ema_val
        except Exception:
            return 1.0

    def _adx_proxy(self, data) -> float:
        """
        Lightweight ADX proxy using directional movement / total range.
        Returns a value in [0, 100].
        """
        try:
            period = self.adx_proxy_period
            need = period * 2 + 5
            closes = data.close[-need:]
            highs  = data.high[-need:]
            lows   = data.low[-need:]
            n = len(closes)
            if n < period + 2:
                return 25.0

            dm_plus_list, dm_minus_list, tr_list = [], [], []
            for k in range(1, n):
                up_move   = highs[k]  - highs[k - 1]
                down_move = lows[k - 1] - lows[k]
                dp = up_move   if (up_move > 0 and up_move > down_move) else 0.0
                dm = down_move if (down_move > 0 and down_move > up_move) else 0.0
                dm_plus_list.append(dp)
                dm_minus_list.append(dm)
                h, l, pc = highs[k], lows[k], closes[k - 1]
                tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))

            if len(tr_list) < period:
                return 25.0

            # Smoothed sums (last `period` bars)
            atr_s  = sum(tr_list[-period:])
            dmp_s  = sum(dm_plus_list[-period:])
            dmm_s  = sum(dm_minus_list[-period:])

            if atr_s <= 0:
                return 25.0
            di_plus  = 100 * dmp_s / atr_s
            di_minus = 100 * dmm_s / atr_s
            di_sum   = di_plus + di_minus
            if di_sum <= 0:
                return 0.0
            dx = 100 * abs(di_plus - di_minus) / di_sum
            return dx
        except Exception:
            return 25.0

    def _body_ratio(self, data) -> float:
        """
        Average |body| / total_range ratio over last N bars.
        High ratio -> directional, strong bars.
        Low ratio  -> wicks/dojis, choppy market.
        """
        try:
            period = self.body_quality_period
            opens  = data.open[-period:]
            highs  = data.high[-period:]
            lows   = data.low[-period:]
            closes = data.close[-period:]
            n = len(closes)
            if n < period:
                return 0.55
            ratios = []
            for k in range(n):
                rng = highs[k] - lows[k]
                if rng > 0:
                    ratios.append(abs(closes[k] - opens[k]) / rng)
            return sum(ratios) / len(ratios) if ratios else 0.55
        except Exception:
            return 0.55

    @staticmethod
    def _normalise(value: float, low: float, high: float) -> float:
        """Linearly map [low, high] -> [-1, +1], clamped."""
        if high <= low:
            return 0.0
        norm = (value - low) / (high - low)  # 0 to 1
        mapped = 2 * norm - 1                 # -1 to +1
        return max(-1.0, min(1.0, mapped))

    def _params(self, regime: str):
        """Return (target_r, be_trigger_r, be_buffer_r, min_atr_mult, min_body_ratio)."""
        if regime == "TRENDING":
            return (
                self.trending_target_r,
                self.trending_be_trigger_r,
                self.trending_be_buffer_r,
                self.trending_min_atr_mult,
                self.trending_min_body_ratio,
            )
        elif regime == "COMPRESSED":
            return (
                self.compressed_target_r,
                self.compressed_be_trigger_r,
                self.compressed_be_buffer_r,
                self.compressed_min_atr_mult,
                self.compressed_min_body_ratio,
            )
        else:  # NEUTRAL
            return (
                self.neutral_target_r,
                self.neutral_be_trigger_r,
                self.neutral_be_buffer_r,
                self.neutral_min_atr_mult,
                self.neutral_min_body_ratio,
            )
