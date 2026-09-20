import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    # pyrefly: ignore [missing-import]
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(): pass


def _env_bool(k: str, default: bool = False) -> bool:
    v = os.getenv(k, str(default)).strip().lower()
    return v in ("1", "true", "yes", "on")


def _env_float(k: str, default: float) -> float:
    return float(os.getenv(k, str(default)))


def _env_int(k: str, default: int) -> int:
    return int(os.getenv(k, str(default)))


log = logging.getLogger("xauusd_bot.config")


@dataclass
class MT5Config:
    login: int = 0
    password: str = ""
    server: str = ""
    path: str = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    timeout_ms: int = 20000

    @classmethod
    def from_env(cls) -> "MT5Config":
        pwd = os.getenv("MT5_PASSWORD", "")
        if pwd:
            log.warning("MT5 password found in plaintext environment variable — consider using encrypted storage")
        return cls(
            login=_env_int("MT5_LOGIN", 0),
            password=pwd,
            server=os.getenv("MT5_SERVER", ""),
            path=os.getenv("MT5_PATH", cls.path),
            timeout_ms=_env_int("MT5_TIMEOUT_MS", 20000),
        )


@dataclass
class TradingConfig:
    symbol: str = "XAUUSD"
    symbols: List[str] = field(default_factory=lambda: ["XAUUSD", "USTECH100M"])
    magic_number: int = 20260601
    comment: str = "XAUUSD_Digger"

    enable_session_filter: bool = False
    enable_sideways_filter: bool = True
    sideways_chop_threshold: float = 61.8
    sideways_adx_threshold: float = 22.0
    sideways_bandwidth_squeeze_pct: float = 25.0

    enable_ao_saucer: bool = True
    enable_ha_filter: bool = True
    enable_psar_trailing: bool = True

    enable_tradingview: bool = False
    tradingview_timeframe: str = "M15"
    tradingview_cache_ttl: float = 45.0

    max_spread_multiplier: float = 1.5
    spread_lookback_bars: int = 50

    daily_loss_limit_pct: float = 3.0
    max_dd_limit_pct: float = 10.0
    daily_loss_buffer_pct: float = 0.3
    max_dd_buffer_pct: float = 2.0

    max_pyramid_entries: int = 3
    pyramid_add_trigger_r: float = 0.5
    pyramid_initial_risk_pct: float = 0.85

    partial_take_profit_r: float = 1.0
    partial_close_pct: float = 25.0
    partial_tp_tranche1_r: float = 1.0
    partial_tp_tranche1_pct: float = 25.0
    partial_tp_tranche2_r: float = 2.2
    partial_tp_tranche2_pct: float = 35.0

    # Dynamic Conviction-Weighted Bet Sizing (Institutional Kelly Factor)
    enable_conviction_sizing: bool = True
    conviction_scale_a_plus: float = 2.60
    conviction_scale_a: float = 1.00
    conviction_scale_b: float = 1.00
    conviction_scale_c: float = 0.60

    # Grade A+ (Unicorn) Criteria Configuration
    xau_a_plus_ny_core_only: bool = True       # Grade A+ requires NY Core session (13:00 - 15:00 UTC)
    xau_a_plus_block_h1_bullish: bool = True   # Filter out H1 bullish fatigue traps from A+
    xau_a_plus_min_sl_dist: float = 0.0        # Optional minimum SL distance for A+

    # Tuesday Compression Microstructure Guard (Blueprint Chapter 5.1)
    tuesday_reduced_risk: bool = True
    tuesday_risk_scale: float = 0.43
    tuesday_breakeven_trigger_r: float = 1.40

    # Universal Capital Adapter & Whale Iceberg Slicing
    enable_universal_capital_adapter: bool = True
    is_cent_account: bool = False
    whale_slice_threshold_lots: float = 10.0
    whale_max_child_slice_lots: float = 5.0

    # Level-2 (L2) Depth of Market & Order Book Imbalance (OBI)
    enable_l2_depth: bool = True
    l2_depth_levels: int = 10
    l2_min_obi_threshold: float = 0.15

    time_based_exit_minutes: int = 240
    max_r_multiple: float = 3.0

    news_block_before_minutes: int = 30
    news_block_after_minutes: int = 30
    high_impact_news_only: bool = True

    atr_period: int = 14
    atr_multiplier_m1: float = 1.2
    atr_multiplier_m5: float = 1.5
    atr_multiplier_m15: float = 2.0
    atr_multiplier_m30: float = 2.5
    atr_multiplier_h1: float = 3.0

    ema_fast: int = 9
    ema_medium: int = 21
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    rsi_mid_upper: float = 60.0
    rsi_mid_lower: float = 40.0

    # Strategy Trigger Configuration (xau_liquidity_sweep_fvg_m1 is the authoritative production engine)
    strategy_trigger_type: str = "xau_liquidity_sweep_fvg_m1"
    tbh_lookback: int = 2
    tbh_fib_0: float = 0.382
    tbh_fib_1: float = 0.618
    tbh_rsi_length: int = 14
    tbh_rsi_oversold: float = 30.0
    tbh_rsi_overbought: float = 70.0
    tbh_atr_sl_mult: float = 2.0
    tbh_rr_ratio: float = 1.5
    tbh_use_trend_filter: bool = False
    tbh_trend_sma_len: int = 200

    # XAU_LIQUIDITY_SWEEP_FVG_M1 Scalping Parameters (Professional Setup)
    xau_fvg_strategy_enabled: bool = True
    xau_context_timeframe: str = "M15"
    xau_execution_timeframe: str = "M1"
    xau_session_timezone: str = "America/New_York"
    xau_session_start: str = "02:00"   # NY time — covers Asian + London + NY
    xau_session_end: str = "20:00"    # NY time — full trading day open
    xau_atr_period: int = 14
    xau_displacement_atr_mult: float = 0.60
    xau_displacement_body_ratio: float = 0.60
    xau_max_holding_bars: int = 0  # 0 = disabled for Gold runners (full 2.0R TP target)
    xau_require_retest: bool = True  # Confirmed rejection bounce required before filling FVG order
    xau_retest_max_bars: int = 8  # Maximum M1 bars to wait for confirmed retest
    xau_strict_killzones: bool = True  # London (07-09 UTC) & NY Core (13:30-16:30 UTC)
    xau_session_cutoff_hour: int = 24  # Cutoff hour (UTC) for XAU signals (24 = disabled / Full-Day Flagship; 13 = London only)
    xau_target_r: float = 2.0
    xau_risk_per_trade: float = 0.0085
    xau_max_trades_per_session: int = 2  # Option A: 2 trades per session
    max_daily_trades: int = 4            # Option A: up to 4 trades per day across portfolio
    max_concurrent_pending_orders: int = 2 # Option A: allow up to 2 concurrent pending limit orders
    xau_fvg_expiry_bars: int = 8         # Option A: 8 M1 bars limit order patience for Gold
    nas_fvg_expiry_bars: int = 15        # 15 M1 bars limit order patience for Nasdaq 100 (antifragile retest window)
    xau_cooldown_minutes: int = 5
    xau_swing_lookback_m15: int = 20
    xau_mss_lookback_m1: int = 5
    xau_liquidity_source: str = "m15_swings"  # "m15_swings" (authoritative winner)

    # Multi-Strategy Institutional Ecosystem & Advanced Loss-Mitigation
    xau_ecosystem_mode: bool = True
    xau_enable_london_asian_sweep: bool = True
    xau_enable_overlap_pullback: bool = False
    xau_early_invalidation_exit: bool = False
    xau_enable_pre_fill_guard: bool = True
    xau_breakeven_ratchet_enabled: bool = True
    xau_breakeven_trigger_r: float = 1.50
    xau_breakeven_buffer_r: float = 0.10
    xau_stagnation_exit_enabled: bool = True
    xau_stagnation_bars: int = 20
    xau_stagnation_min_r: float = 0.30
    xau_partial_close_enabled: bool = False
    xau_london_displacement_atr_mult: float = 0.75
    xau_london_displacement_body_ratio: float = 0.65
    xau_london_risk_per_trade: float = 0.0085
    xau_overlap_risk_per_trade: float = 0.0065

    # Nasdaq 100 (USTECH100M / NAS100) Dedicated Parameters (Antifragile Plateau)
    nas_risk_per_trade: float = 0.025
    nas_target_r: float = 2.0
    nas_breakeven_trigger_r: float = 1.25  # Centered on 1.20R - 1.30R robust plateau
    nas_breakeven_buffer_r: float = 0.10
    nas_max_holding_bars: int = 0
    nas_session_start_hour: int = 15   # 15:45 UTC (US Afternoon Continuation Killzone)
    nas_session_start_minute: int = 45
    nas_killzone_morning_start_min: int = 45
    nas_london_close_pause_start_hour: int = 24  # No pause needed after 15:45
    nas_london_close_pause_end_min: int = 45
    nas_session_end_hour: int = 20    # 20:00 UTC (US Cash Close)
    nas_require_retest: bool = True
    nas_retest_max_bars: int = 15     # 15 M1 bars limit order patience for Nasdaq
    nas_require_h1_trend: bool = True
    nas_stagnation_bars: int = 40     # Centered on 35 - 45 bar plateau
    nas_max_consecutive_losses_day: int = 2  # Circuit breaker against FOMC/whipsaw days
    conviction_scale_nas_a_plus: float = 2.40
    xau_min_sl_distance: float = 5.0  # Minimum $5.00 SL breathing room floor for Gold
    nas_min_sl_distance: float = 10.0  # Minimum 10.0 pts SL breathing room floor for Nasdaq 100


    # ── El Professor Hidden Guards ──────────────────────────────────────────────
    # Guard 1 (XAU only): London Close / NY Cutoff — no new entries after 14:45 UTC
    # Backtested: Filters out late-day low-liquidity chop and false breakouts
    xau_london_close_guard: bool = True
    xau_london_close_cutoff_hour: int = 14
    xau_london_close_cutoff_min: int = 45
    xau_london_start_hour: int = 8
    xau_london_start_minute: int = 0
    xau_friday_trade_enabled: bool = True   # Enabled for NY session (with London NFP skip)
    xau_friday_skip_london: bool = True     # Skip 07:45 - 09:30 UTC on Friday (NFP / pre-weekend wicks)
    xau_friday_risk_scale: float = 0.50     # Half-risk sizing on Friday afternoon
    friday_skip_ny_session: bool = False    # Allow Friday NY session until 14:45 UTC

    enable_profit_compounding: bool = True
    initial_account_balance: float = 10000.0
    compounding_cap_mult: float = 5.0
    enable_net_beta_gate: bool = True
    correlated_usd_risk_scale: float = 0.60

    # ── Dynamic Profit Maximization Engine ───────────────────────────────────────
    delta_absorption_mode: str = "soft"  # "soft" (additive scoring / telemetry) or "hard" (strict setup veto)
    enable_split_tranche_runner: bool = False  # Full 2.0R runner with 1.0R BE protection
    runner_tranche_pct: float = 0.50
    runner_trail_atr_mult: float = 3.0
    fvg_adaptive_retest_tolerance_pct: float = 0.25
    enable_fvg_pyramiding: bool = True

    # ── XAU Dynamic Breakeven & Multi-Order Risk Engine ──────────────────────────
    xau_breakeven_enabled: bool = True
    xau_breakeven_r: float = 1.00  # Move to BE at 1.0R profit for early risk-free status
    xau_breakeven_buffer: float = 0.10
    xau_prevent_duplicate_pending: bool = True
    xau_h4_bias_guard: bool = False
    xau_h4_ema_fast: int = 9
    xau_h4_ema_slow: int = 50
    friday_weekend_guard: bool = True
    friday_close_cutoff_hour: int = 20
    friday_close_cutoff_min: int = 45

    # Day-of-Week Risk & Session Optimizations
    friday_skip_ny_session: bool = True
    tuesday_reduced_risk: bool = True
    tuesday_risk_scale: float = 0.43
    tuesday_trade_enabled: bool = True

    # Guard 5 (XAU): Intra-Session Consecutive-Loss Cooldown
    # After xau_consec_loss_max consecutive SL hits in the same day,
    # pause XAU entries for the rest of that trading day.
    # Guard 5b: after 1 SL hit during London session (07:45-10:30 UTC),
    # block further London entries that day (NY unaffected).
    xau_consec_loss_guard: bool = True
    xau_consec_loss_max: int = 2   # pause entire day after 2 consecutive SL hits

    # Guard 5 (NAS): Intra-Session Consecutive-Loss Cooldown for Nasdaq 100
    # After nas_consec_loss_max consecutive SL hits, pause NAS entries for rest of day.
    nas_consec_loss_guard: bool = True
    nas_consec_loss_max: int = 2   # pause entire day after 2 consecutive NAS100 SL hits

    # London Session Structural Optimization & Profit Protection
    xau_london_require_h1_trend: bool = True
    xau_london_protect_profits: bool = True


    def is_in_nas_session(self, current_time) -> bool:
        """Evaluate whether current UTC time is within Nasdaq 100 active US cash session.
        Focuses on pristine US afternoon continuation (15:45 - 20:00 UTC).
        """
        if current_time is None:
            return True
        h_utc = current_time.hour if hasattr(current_time, "hour") else 0
        m_utc = current_time.minute if hasattr(current_time, "minute") else 0
        start_h = getattr(self, "nas_session_start_hour", 15)
        start_m = getattr(self, "nas_killzone_morning_start_min", 45)
        end_h = getattr(self, "nas_session_end_hour", 20)
        if h_utc < start_h or h_utc >= end_h:
            return False
        if h_utc == start_h and m_utc < start_m:
            return False
        return True

    def get_risk_per_trade(self, symbol: str = "XAUUSD") -> float:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol)
        if spec["is_index"]:
            return getattr(self, "nas_risk_per_trade", 0.025)
        return getattr(self, "xau_risk_per_trade", getattr(self, "pyramid_initial_risk_pct", 3.5) / 100.0)

    def get_conviction_scale(self, signal_or_grade, is_tuesday: bool = False, is_friday: bool = False) -> float:
        """Calculate dynamic bet sizing factor (Fractional Kelly) without dropping trades."""
        if not getattr(self, "enable_conviction_sizing", True):
            scale = 1.0
        else:
            from .models import SignalGrade
            sym = getattr(signal_or_grade, "symbol", "XAUUSD")
            from .utils.asset_specs import get_asset_spec
            spec = get_asset_spec(sym)

            if hasattr(signal_or_grade, "grade"):
                grade = signal_or_grade.grade
            elif isinstance(signal_or_grade, SignalGrade):
                grade = signal_or_grade
            elif isinstance(signal_or_grade, int):
                grade = SignalGrade.A if signal_or_grade >= self.signal_score_a_min else (
                    SignalGrade.B if signal_or_grade >= self.signal_score_b_min else SignalGrade.C
                )
            else:
                grade = SignalGrade.B

            if spec["is_index"]:
                if grade == SignalGrade.A_PLUS:
                    scale = getattr(self, "conviction_scale_nas_a_plus", 2.40)
                elif grade == SignalGrade.A:
                    scale = getattr(self, "conviction_scale_a", 1.00)
                elif grade == SignalGrade.B:
                    scale = getattr(self, "conviction_scale_b", 1.00)
                else:
                    scale = getattr(self, "conviction_scale_c", 0.60)
            else:
                if grade == SignalGrade.A_PLUS:
                    scale = getattr(self, "conviction_scale_a_plus", 2.60)
                elif grade == SignalGrade.A:
                    scale = getattr(self, "conviction_scale_a", 1.00)
                elif grade == SignalGrade.B:
                    scale = getattr(self, "conviction_scale_b", 1.00)
                else:
                    scale = getattr(self, "conviction_scale_c", 0.60)

        if is_tuesday:
            scale *= getattr(self, "tuesday_risk_scale", 0.43)
        if is_friday and not spec.get("is_index", False):
            scale *= getattr(self, "xau_friday_risk_scale", 0.50)
        return scale

    def get_target_r(self, symbol: str = "XAUUSD") -> float:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol)
        if spec["is_index"]:
            return getattr(self, "nas_target_r", 2.0)
        return self.xau_target_r

    def get_breakeven_trigger_r(self, symbol: str = "XAUUSD") -> float:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol)
        if spec["is_index"]:
            return getattr(self, "nas_breakeven_trigger_r", 1.25)
        return getattr(self, "xau_breakeven_trigger_r", 1.50)

    def get_breakeven_buffer_r(self, symbol: str = "XAUUSD") -> float:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol)
        if spec["is_index"]:
            return getattr(self, "nas_breakeven_buffer_r", 0.10)
        return getattr(self, "xau_breakeven_buffer_r", 0.10)

    def get_max_holding_bars(self, symbol: str = "XAUUSD") -> int:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol)
        if spec["is_index"]:
            return getattr(self, "nas_max_holding_bars", 0)
        return self.xau_max_holding_bars

    def get_commission_per_lot(self, symbol: str = "XAUUSD") -> float:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol)
        if spec["is_index"]:
            return getattr(self, "backtest_index_commission_per_lot", 0.0)
        return getattr(self, "backtest_commission_per_lot", 6.0)


    xau_london_start_hour: int = 7
    xau_london_start_minute: int = 45
    xau_london_end_hour: int = 10
    xau_london_end_minute: int = 0

    def is_in_xau_london_killzone(self, dt) -> bool:
        """London killzone aligned to authentic London cash liquidity (07:45 - London cash peak UTC)."""
        if dt is None:
            return False
        if getattr(self, "xau_friday_skip_london", True) and hasattr(dt, "weekday") and dt.weekday() == 4:
            return False
        h = dt.hour if hasattr(dt, "hour") else 0
        m = dt.minute if hasattr(dt, "minute") else 0
        end_h = getattr(self, "xau_london_end_hour", 10)
        end_m = getattr(self, "xau_london_end_minute", 0)
        return (h == 7 and m >= 45) or (8 <= h < end_h) or (h == end_h and m <= end_m)

    def get_min_sl_distance(self, symbol: str = "XAUUSD", current_price: float = 0.0, m1_atr: float = 0.0) -> float:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol, current_price)
        if spec["is_index"]:
            dyn_nas = getattr(self, "nas_min_sl_distance", 5.0)
            return max(dyn_nas, m1_atr * 1.5) if m1_atr > 0 else dyn_nas
        dyn_floor = getattr(self, "xau_min_sl_distance", 5.0)
        if m1_atr > 0:
            dyn_floor = max(dyn_floor, m1_atr * 2.0)
        return dyn_floor

    def get_fvg_expiry_bars(self, symbol: str = "XAUUSD") -> int:
        from .utils.asset_specs import get_asset_spec
        spec = get_asset_spec(symbol)
        if spec["is_index"]:
            return getattr(self, "nas_fvg_expiry_bars", 8)
        return self.xau_fvg_expiry_bars

    deviation_points: int = 20

    vwap_period: int = 20
    enable_vwap_bands: bool = False
    vwap_band_mult_1: float = 1.0
    vwap_band_mult_2: float = 2.0

    # Auction Market Theory (AMT) Volume Profile
    enable_amt_filter: bool = False
    amt_value_area_pct: float = 0.70
    amt_profile_lookback: int = 50
    amt_profile_bins: int = 50

    # Prop-Desk Order Flow & Microstructure Delta
    enable_delta_absorption: bool = True
    enable_delta_divergence: bool = False
    enable_hvn_tp_calibration: bool = True


    min_structure_swing_bars: int = 5
    max_structure_swing_bars: int = 20

    signal_score_a_min: int = 8
    signal_score_b_min: int = 5

    session_london_open: str = "02:00"   # UTC — includes Asian pre-market
    session_london_close: str = "22:00"  # UTC — includes full NY session
    session_ny_open: str = "02:00"       # UTC — open from Asian session
    session_ny_close: str = "23:00"      # UTC — full day coverage

    broker_daily_reset_hour: int = 0
    broker_daily_reset_tz: str = "UTC"

    logging_level: str = "INFO"
    log_file: str = "logs/xauusd_bot.log"
    telegram_token: str = ""
    telegram_chat_id: str = ""

    state_db_path: str = "data/bot_state.db"
    trade_log_path: str = "data/trade_log.csv"

    enable_research_team: bool = True
    research_report_dir: str = "logs/research"
    ai_provider: str = "none"
    ai_api_key: str = ""

    poll_interval_ms: int = 500

    # London Strategic Edge (LSE) Live WebSocket & Vault API
    # BUG-10 FIX: API key must NOT be hardcoded — load from .env via LSE_API_KEY
    lse_api_key: str = ""  # Set LSE_API_KEY in your .env file
    lse_ws_url: str = "wss://data-ws.londonstrategicedge.com"
    lse_http_url: str = "https://api.londonstrategicedge.com/vault"
    enable_lse_feed: bool = True

    backtest_initial_balance: float = 100000.0
    backtest_commission_pct: float = 0.0
    backtest_commission_per_lot: float = 6.0
    # BUG-11 FIX: NAS100 commission was 0.0 (unrealistically optimistic).
    # Typical CFD NAS100 spread cost ~1.0 per lot per side. Set via BACKTEST_INDEX_COMMISSION_PER_LOT.
    backtest_index_commission_per_lot: float = 1.0
    backtest_apply_friction: bool = True
    backtest_slippage_points: float = 0.5
    backtest_spread_points: float = 20.0

    def atr_multiplier_for_tf(self, tf: str) -> float:
        return {
            "M1": self.atr_multiplier_m1,
            "M5": self.atr_multiplier_m5,
            "M15": self.atr_multiplier_m15,
            "M30": self.atr_multiplier_m30,
            "H1": self.atr_multiplier_h1,
        }.get(tf, 1.5)

    @classmethod
    def from_env(cls) -> "TradingConfig":
        raw_symbols = os.getenv("SYMBOLS", "")
        if raw_symbols:
            symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
        else:
            env_sym = os.getenv("SYMBOL", "")
            if env_sym and env_sym != "XAUUSD":
                symbols = [env_sym]
            else:
                symbols = ["XAUUSD", "USTECH100M"]

        return cls(
            symbol=os.getenv("SYMBOL", cls.symbol),
            symbols=symbols,
            magic_number=_env_int("MAGIC_NUMBER", cls.magic_number),
            enable_session_filter=_env_bool("ENABLE_SESSION_FILTER", cls.enable_session_filter),
            enable_sideways_filter=_env_bool("ENABLE_SIDEWAYS_FILTER", cls.enable_sideways_filter),
            sideways_chop_threshold=_env_float("SIDEWAYS_CHOP_THRESHOLD", cls.sideways_chop_threshold),
            sideways_adx_threshold=_env_float("SIDEWAYS_ADX_THRESHOLD", cls.sideways_adx_threshold),
            sideways_bandwidth_squeeze_pct=_env_float("SIDEWAYS_BANDWIDTH_SQUEEZE_PCT", cls.sideways_bandwidth_squeeze_pct),
            enable_ao_saucer=_env_bool("ENABLE_AO_SAUCER", cls.enable_ao_saucer),
            enable_ha_filter=_env_bool("ENABLE_HA_FILTER", cls.enable_ha_filter),
            enable_psar_trailing=_env_bool("ENABLE_PSAR_TRAILING", cls.enable_psar_trailing),
            enable_tradingview=_env_bool("ENABLE_TRADINGVIEW", cls.enable_tradingview),
            tradingview_timeframe=os.getenv("TRADINGVIEW_TIMEFRAME", cls.tradingview_timeframe),
            tradingview_cache_ttl=_env_float("TRADINGVIEW_CACHE_TTL", cls.tradingview_cache_ttl),
            max_spread_multiplier=_env_float("MAX_SPREAD_MULTIPLIER", cls.max_spread_multiplier),
            spread_lookback_bars=_env_int("SPREAD_LOOKBACK_BARS", cls.spread_lookback_bars),
            daily_loss_limit_pct=_env_float("DAILY_LOSS_LIMIT_PCT", cls.daily_loss_limit_pct),
            max_dd_limit_pct=_env_float("MAX_DD_LIMIT_PCT", cls.max_dd_limit_pct),
            daily_loss_buffer_pct=_env_float("DAILY_LOSS_BUFFER_PCT", cls.daily_loss_buffer_pct),
            max_dd_buffer_pct=_env_float("MAX_DD_BUFFER_PCT", cls.max_dd_buffer_pct),
            max_pyramid_entries=_env_int("MAX_PYRAMID_ENTRIES", cls.max_pyramid_entries),
            pyramid_add_trigger_r=_env_float("PYRAMID_ADD_TRIGGER_R", cls.pyramid_add_trigger_r),
            pyramid_initial_risk_pct=_env_float("PYRAMID_INITIAL_RISK_PCT", cls.pyramid_initial_risk_pct),
            partial_take_profit_r=_env_float("PARTIAL_TAKE_PROFIT_R", cls.partial_take_profit_r),
            partial_close_pct=_env_float("PARTIAL_CLOSE_PCT", cls.partial_close_pct),
            time_based_exit_minutes=_env_int("TIME_BASED_EXIT_MINUTES", cls.time_based_exit_minutes),
            max_r_multiple=_env_float("MAX_R_MULTIPLE", cls.max_r_multiple),
            news_block_before_minutes=_env_int("NEWS_BLOCK_BEFORE_MINUTES", cls.news_block_before_minutes),
            news_block_after_minutes=_env_int("NEWS_BLOCK_AFTER_MINUTES", cls.news_block_after_minutes),
            high_impact_news_only=_env_bool("HIGH_IMPACT_NEWS_ONLY", cls.high_impact_news_only),
            atr_period=_env_int("ATR_PERIOD", cls.atr_period),
            atr_multiplier_m1=_env_float("ATR_MULTIPLIER_M1", cls.atr_multiplier_m1),
            atr_multiplier_m5=_env_float("ATR_MULTIPLIER_M5", cls.atr_multiplier_m5),
            atr_multiplier_m15=_env_float("ATR_MULTIPLIER_M15", cls.atr_multiplier_m15),
            atr_multiplier_m30=_env_float("ATR_MULTIPLIER_M30", cls.atr_multiplier_m30),
            atr_multiplier_h1=_env_float("ATR_MULTIPLIER_H1", cls.atr_multiplier_h1),
            ema_fast=_env_int("EMA_FAST", cls.ema_fast),
            ema_medium=_env_int("EMA_MEDIUM", cls.ema_medium),
            ema_slow=_env_int("EMA_SLOW", cls.ema_slow),
            rsi_period=_env_int("RSI_PERIOD", cls.rsi_period),
            rsi_overbought=_env_float("RSI_OVERBOUGHT", cls.rsi_overbought),
            rsi_oversold=_env_float("RSI_OVERSOLD", cls.rsi_oversold),
            rsi_mid_upper=_env_float("RSI_MID_UPPER", cls.rsi_mid_upper),
            rsi_mid_lower=_env_float("RSI_MID_LOWER", cls.rsi_mid_lower),
            deviation_points=_env_int("DEVIATION_POINTS", cls.deviation_points),
            vwap_period=_env_int("VWAP_PERIOD", cls.vwap_period),
            min_structure_swing_bars=_env_int("MIN_STRUCTURE_SWING_BARS", cls.min_structure_swing_bars),
            max_structure_swing_bars=_env_int("MAX_STRUCTURE_SWING_BARS", cls.max_structure_swing_bars),
            signal_score_a_min=_env_int("SIGNAL_SCORE_A_MIN", cls.signal_score_a_min),
            signal_score_b_min=_env_int("SIGNAL_SCORE_B_MIN", cls.signal_score_b_min),
            session_london_open=os.getenv("SESSION_LONDON_OPEN", cls.session_london_open),
            session_london_close=os.getenv("SESSION_LONDON_CLOSE", cls.session_london_close),
            session_ny_open=os.getenv("SESSION_NY_OPEN", cls.session_ny_open),
            session_ny_close=os.getenv("SESSION_NY_CLOSE", cls.session_ny_close),
            broker_daily_reset_hour=_env_int("BROKER_DAILY_RESET_HOUR", cls.broker_daily_reset_hour),
            broker_daily_reset_tz=os.getenv("BROKER_DAILY_RESET_TZ", cls.broker_daily_reset_tz),
            logging_level=os.getenv("LOGGING_LEVEL", cls.logging_level),
            log_file=os.getenv("LOG_FILE", cls.log_file),
            telegram_token=os.getenv("TELEGRAM_TOKEN", cls.telegram_token),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", cls.telegram_chat_id),
            state_db_path=os.getenv("STATE_DB_PATH", cls.state_db_path),
            trade_log_path=os.getenv("TRADE_LOG_PATH", cls.trade_log_path),
            enable_research_team=_env_bool("ENABLE_RESEARCH_TEAM", cls.enable_research_team),
            research_report_dir=os.getenv("RESEARCH_REPORT_DIR", cls.research_report_dir),
            ai_provider=os.getenv("AI_PROVIDER", cls.ai_provider),
            ai_api_key=os.getenv("AI_API_KEY", cls.ai_api_key),
            poll_interval_ms=_env_int("POLL_INTERVAL_MS", cls.poll_interval_ms),
            lse_api_key=os.getenv("LSE_API_KEY", cls.lse_api_key),
            lse_ws_url=os.getenv("LSE_WS_URL", cls.lse_ws_url),
            lse_http_url=os.getenv("LSE_HTTP_URL", cls.lse_http_url),
            enable_lse_feed=_env_bool("ENABLE_LSE_FEED", cls.enable_lse_feed),
            backtest_initial_balance=_env_float("BACKTEST_INITIAL_BALANCE", cls.backtest_initial_balance),
            backtest_commission_pct=_env_float("BACKTEST_COMMISSION_PCT", cls.backtest_commission_pct),
            backtest_commission_per_lot=_env_float("BACKTEST_COMMISSION_PER_LOT", cls.backtest_commission_per_lot),
            backtest_apply_friction=_env_bool("BACKTEST_APPLY_FRICTION", cls.backtest_apply_friction),
            backtest_slippage_points=_env_float("BACKTEST_SLIPPAGE_POINTS", cls.backtest_slippage_points),
            backtest_spread_points=_env_float("BACKTEST_SPREAD_POINTS", cls.backtest_spread_points),
            strategy_trigger_type=os.getenv("STRATEGY_TRIGGER_TYPE", cls.strategy_trigger_type),
            tbh_lookback=_env_int("TBH_LOOKBACK", cls.tbh_lookback),
            tbh_fib_0=_env_float("TBH_FIB_0", cls.tbh_fib_0),
            tbh_fib_1=_env_float("TBH_FIB_1", cls.tbh_fib_1),
            tbh_rsi_length=_env_int("TBH_RSI_LENGTH", cls.tbh_rsi_length),
            tbh_rsi_oversold=_env_float("TBH_RSI_OVERSOLD", cls.tbh_rsi_oversold),
            tbh_rsi_overbought=_env_float("TBH_RSI_OVERBOUGHT", cls.tbh_rsi_overbought),
            tbh_atr_sl_mult=_env_float("TBH_ATR_SL_MULT", cls.tbh_atr_sl_mult),
            tbh_rr_ratio=_env_float("TBH_RR_RATIO", cls.tbh_rr_ratio),
            tbh_use_trend_filter=_env_bool("TBH_USE_TREND_FILTER", cls.tbh_use_trend_filter),
            tbh_trend_sma_len=_env_int("TBH_TREND_SMA_LEN", cls.tbh_trend_sma_len),
            xau_fvg_strategy_enabled=_env_bool("XAU_FVG_STRATEGY_ENABLED", cls.xau_fvg_strategy_enabled),
            xau_context_timeframe=os.getenv("XAU_CONTEXT_TIMEFRAME", cls.xau_context_timeframe),
            xau_execution_timeframe=os.getenv("XAU_EXECUTION_TIMEFRAME", cls.xau_execution_timeframe),
            xau_session_timezone=os.getenv("XAU_SESSION_TIMEZONE", cls.xau_session_timezone),
            xau_session_start=os.getenv("XAU_SESSION_START", cls.xau_session_start),
            xau_session_end=os.getenv("XAU_SESSION_END", cls.xau_session_end),
            xau_atr_period=_env_int("XAU_ATR_PERIOD", cls.xau_atr_period),
            xau_displacement_atr_mult=_env_float("XAU_DISPLACEMENT_ATR_MULT", cls.xau_displacement_atr_mult),
            xau_displacement_body_ratio=_env_float("XAU_DISPLACEMENT_BODY_RATIO", cls.xau_displacement_body_ratio),
            xau_fvg_expiry_bars=_env_int("XAU_FVG_EXPIRY_BARS", cls.xau_fvg_expiry_bars),
            xau_max_holding_bars=_env_int("XAU_MAX_HOLDING_BARS", cls.xau_max_holding_bars),
            xau_target_r=_env_float("XAU_TARGET_R", cls.xau_target_r),
            xau_risk_per_trade=_env_float("XAU_RISK_PER_TRADE", cls.xau_risk_per_trade),
            xau_max_trades_per_session=_env_int("XAU_MAX_TRADES_PER_SESSION", cls.xau_max_trades_per_session),
            xau_cooldown_minutes=_env_int("XAU_COOLDOWN_MINUTES", cls.xau_cooldown_minutes),
            xau_swing_lookback_m15=_env_int("XAU_SWING_LOOKBACK_M15", cls.xau_swing_lookback_m15),
            xau_mss_lookback_m1=_env_int("XAU_MSS_LOOKBACK_M1", cls.xau_mss_lookback_m1),
            enable_vwap_bands=_env_bool("ENABLE_VWAP_BANDS", cls.enable_vwap_bands),
            vwap_band_mult_1=_env_float("VWAP_BAND_MULT_1", cls.vwap_band_mult_1),
            vwap_band_mult_2=_env_float("VWAP_BAND_MULT_2", cls.vwap_band_mult_2),
            enable_amt_filter=_env_bool("ENABLE_AMT_FILTER", cls.enable_amt_filter),
            amt_value_area_pct=_env_float("AMT_VALUE_AREA_PCT", cls.amt_value_area_pct),
            amt_profile_lookback=_env_int("AMT_PROFILE_LOOKBACK", cls.amt_profile_lookback),
            amt_profile_bins=_env_int("AMT_PROFILE_BINS", cls.amt_profile_bins),
            enable_delta_absorption=_env_bool("ENABLE_DELTA_ABSORPTION", cls.enable_delta_absorption),
            enable_delta_divergence=_env_bool("ENABLE_DELTA_DIVERGENCE", cls.enable_delta_divergence),
            enable_hvn_tp_calibration=_env_bool("ENABLE_HVN_TP_CALIBRATION", cls.enable_hvn_tp_calibration),
            xau_ecosystem_mode=_env_bool("XAU_ECOSYSTEM_MODE", cls.xau_ecosystem_mode),
            xau_enable_london_asian_sweep=_env_bool("XAU_ENABLE_LONDON_ASIAN_SWEEP", cls.xau_enable_london_asian_sweep),
            xau_enable_overlap_pullback=_env_bool("XAU_ENABLE_OVERLAP_PULLBACK", cls.xau_enable_overlap_pullback),
            xau_early_invalidation_exit=_env_bool("XAU_EARLY_INVALIDATION_EXIT", cls.xau_early_invalidation_exit),
            xau_enable_pre_fill_guard=_env_bool("XAU_ENABLE_PRE_FILL_GUARD", cls.xau_enable_pre_fill_guard),
            xau_breakeven_ratchet_enabled=_env_bool("XAU_BREAKEVEN_RATCHET_ENABLED", cls.xau_breakeven_ratchet_enabled),
            xau_breakeven_trigger_r=_env_float("XAU_BREAKEVEN_TRIGGER_R", cls.xau_breakeven_trigger_r),
            xau_breakeven_buffer_r=_env_float("XAU_BREAKEVEN_BUFFER_R", cls.xau_breakeven_buffer_r),
            xau_stagnation_exit_enabled=_env_bool("XAU_STAGNATION_EXIT_ENABLED", cls.xau_stagnation_exit_enabled),
            xau_stagnation_bars=_env_int("XAU_STAGNATION_BARS", cls.xau_stagnation_bars),
            xau_stagnation_min_r=_env_float("XAU_STAGNATION_MIN_R", cls.xau_stagnation_min_r),
            xau_partial_close_enabled=_env_bool("XAU_PARTIAL_CLOSE_ENABLED", cls.xau_partial_close_enabled),
            xau_london_displacement_atr_mult=_env_float("XAU_LONDON_DISPLACEMENT_ATR_MULT", cls.xau_london_displacement_atr_mult),
            xau_london_displacement_body_ratio=_env_float("XAU_LONDON_DISPLACEMENT_BODY_RATIO", cls.xau_london_displacement_body_ratio),
            xau_london_risk_per_trade=_env_float("XAU_LONDON_RISK_PER_TRADE", cls.xau_london_risk_per_trade),
            xau_overlap_risk_per_trade=_env_float("XAU_OVERLAP_RISK_PER_TRADE", cls.xau_overlap_risk_per_trade),
            nas_risk_per_trade=_env_float("NAS_RISK_PER_TRADE", cls.nas_risk_per_trade),
            nas_target_r=_env_float("NAS_TARGET_R", cls.nas_target_r),
            nas_breakeven_trigger_r=_env_float("NAS_BREAKEVEN_TRIGGER_R", cls.nas_breakeven_trigger_r),
            nas_breakeven_buffer_r=_env_float("NAS_BREAKEVEN_BUFFER_R", cls.nas_breakeven_buffer_r),
            nas_max_holding_bars=_env_int("NAS_MAX_HOLDING_BARS", cls.nas_max_holding_bars),
            nas_session_start_hour=_env_int("NAS_SESSION_START_HOUR", cls.nas_session_start_hour),
            nas_session_start_minute=_env_int("NAS_SESSION_START_MINUTE", cls.nas_session_start_minute),
            nas_session_end_hour=_env_int("NAS_SESSION_END_HOUR", cls.nas_session_end_hour),
            nas_require_retest=_env_bool("NAS_REQUIRE_RETEST", cls.nas_require_retest),
            nas_retest_max_bars=_env_int("NAS_RETEST_MAX_BARS", cls.nas_retest_max_bars),
            xau_require_retest=_env_bool("XAU_REQUIRE_RETEST", cls.xau_require_retest),
            xau_retest_max_bars=_env_int("XAU_RETEST_MAX_BARS", cls.xau_retest_max_bars),
            xau_strict_killzones=_env_bool("XAU_STRICT_KILLZONES", cls.xau_strict_killzones),
            xau_session_cutoff_hour=_env_int("XAU_SESSION_CUTOFF_HOUR", cls.xau_session_cutoff_hour),
            xau_min_sl_distance=_env_float("XAU_MIN_SL_DISTANCE", cls.xau_min_sl_distance),
            nas_min_sl_distance=_env_float("NAS_MIN_SL_DISTANCE", cls.nas_min_sl_distance),
            # El Professor Hidden Guards
            xau_london_close_guard=_env_bool("XAU_LONDON_CLOSE_GUARD", cls.xau_london_close_guard),
            xau_london_close_cutoff_hour=_env_int("XAU_LONDON_CLOSE_CUTOFF_HOUR", cls.xau_london_close_cutoff_hour),
            xau_london_close_cutoff_min=_env_int("XAU_LONDON_CLOSE_CUTOFF_MIN", cls.xau_london_close_cutoff_min),
            # Option A Scaling Parameters
            max_daily_trades=_env_int("MAX_DAILY_TRADES", cls.max_daily_trades),
            max_concurrent_pending_orders=_env_int("MAX_CONCURRENT_PENDING_ORDERS", cls.max_concurrent_pending_orders),
            nas_fvg_expiry_bars=_env_int("NAS_FVG_EXPIRY_BARS", cls.nas_fvg_expiry_bars),
            # Dynamic Profit Compounding & Net Dollar Beta Gate
            enable_profit_compounding=_env_bool("ENABLE_PROFIT_COMPOUNDING", cls.enable_profit_compounding),
            initial_account_balance=_env_float("INITIAL_ACCOUNT_BALANCE", cls.initial_account_balance),
            compounding_cap_mult=_env_float("COMPOUNDING_CAP_MULT", cls.compounding_cap_mult),
            enable_net_beta_gate=_env_bool("ENABLE_NET_BETA_GATE", cls.enable_net_beta_gate),
            correlated_usd_risk_scale=_env_float("CORRELATED_USD_RISK_SCALE", cls.correlated_usd_risk_scale),
            # Dynamic Profit Maximization Engine
            delta_absorption_mode=os.getenv("DELTA_ABSORPTION_MODE", cls.delta_absorption_mode),
            enable_split_tranche_runner=_env_bool("ENABLE_SPLIT_TRANCHE_RUNNER", cls.enable_split_tranche_runner),
            runner_tranche_pct=_env_float("RUNNER_TRANCHE_PCT", cls.runner_tranche_pct),
            runner_trail_atr_mult=_env_float("RUNNER_TRAIL_ATR_MULT", cls.runner_trail_atr_mult),
            fvg_adaptive_retest_tolerance_pct=_env_float("FVG_ADAPTIVE_RETEST_TOLERANCE_PCT", cls.fvg_adaptive_retest_tolerance_pct),
            enable_fvg_pyramiding=_env_bool("ENABLE_FVG_PYRAMIDING", cls.enable_fvg_pyramiding),
            # Day-of-Week Risk & Session Optimizations
            friday_skip_ny_session=_env_bool("FRIDAY_SKIP_NY_SESSION", cls.friday_skip_ny_session),
            tuesday_reduced_risk=_env_bool("TUESDAY_REDUCED_RISK", cls.tuesday_reduced_risk),
            tuesday_risk_scale=_env_float("TUESDAY_RISK_SCALE", cls.tuesday_risk_scale),
            tuesday_trade_enabled=_env_bool("TUESDAY_TRADE_ENABLED", cls.tuesday_trade_enabled),
            # London Session Structural Optimization & Profit Protection
            xau_london_require_h1_trend=_env_bool("XAU_LONDON_REQUIRE_H1_TREND", cls.xau_london_require_h1_trend),
            xau_london_protect_profits=_env_bool("XAU_LONDON_PROTECT_PROFITS", cls.xau_london_protect_profits),
            xau_london_end_hour=_env_int("XAU_LONDON_END_HOUR", cls.xau_london_end_hour),
            xau_london_end_minute=_env_int("XAU_LONDON_END_MINUTE", cls.xau_london_end_minute),
            # Guard 5 (XAU) env overrides
            xau_consec_loss_guard=_env_bool("XAU_CONSEC_LOSS_GUARD", cls.xau_consec_loss_guard),
            xau_consec_loss_max=_env_int("XAU_CONSEC_LOSS_MAX", cls.xau_consec_loss_max),
            # Guard 5 (NAS) env overrides — BUG-17 FIX: these were missing from from_env()
            nas_consec_loss_guard=_env_bool("NAS_CONSEC_LOSS_GUARD", cls.nas_consec_loss_guard),
            nas_consec_loss_max=_env_int("NAS_CONSEC_LOSS_MAX", cls.nas_consec_loss_max),
            # Backtest commission overrides
            backtest_index_commission_per_lot=_env_float("BACKTEST_INDEX_COMMISSION_PER_LOT", cls.backtest_index_commission_per_lot),
            # Institutional Conviction Sizing & Multi-Tranche Parameters
            enable_conviction_sizing=_env_bool("ENABLE_CONVICTION_SIZING", cls.enable_conviction_sizing),
            conviction_scale_a_plus=_env_float("CONVICTION_SCALE_A_PLUS", cls.conviction_scale_a_plus),
            conviction_scale_a=_env_float("CONVICTION_SCALE_A", cls.conviction_scale_a),
            conviction_scale_b=_env_float("CONVICTION_SCALE_B", cls.conviction_scale_b),
            conviction_scale_c=_env_float("CONVICTION_SCALE_C", cls.conviction_scale_c),
            xau_a_plus_ny_core_only=_env_bool("XAU_A_PLUS_NY_CORE_ONLY", cls.xau_a_plus_ny_core_only),
            xau_a_plus_block_h1_bullish=_env_bool("XAU_A_PLUS_BLOCK_H1_BULLISH", cls.xau_a_plus_block_h1_bullish),
            xau_a_plus_min_sl_dist=_env_float("XAU_A_PLUS_MIN_SL_DIST", cls.xau_a_plus_min_sl_dist),
            tuesday_breakeven_trigger_r=_env_float("TUESDAY_BREAKEVEN_TRIGGER_R", cls.tuesday_breakeven_trigger_r),
            partial_tp_tranche1_r=_env_float("PARTIAL_TP_TRANCHE1_R", cls.partial_tp_tranche1_r),
            partial_tp_tranche1_pct=_env_float("PARTIAL_TP_TRANCHE1_PCT", cls.partial_tp_tranche1_pct),
            partial_tp_tranche2_r=_env_float("PARTIAL_TP_TRANCHE2_R", cls.partial_tp_tranche2_r),
            partial_tp_tranche2_pct=_env_float("PARTIAL_TP_TRANCHE2_PCT", cls.partial_tp_tranche2_pct),
            nas_killzone_morning_start_min=_env_int("NAS_KILLZONE_MORNING_START_MIN", cls.nas_killzone_morning_start_min),
            nas_london_close_pause_start_hour=_env_int("NAS_LONDON_CLOSE_PAUSE_START_HOUR", cls.nas_london_close_pause_start_hour),
            nas_london_close_pause_end_min=_env_int("NAS_LONDON_CLOSE_PAUSE_END_MIN", cls.nas_london_close_pause_end_min),
            nas_require_h1_trend=_env_bool("NAS_REQUIRE_H1_TREND", cls.nas_require_h1_trend),
            nas_stagnation_bars=_env_int("NAS_STAGNATION_BARS", cls.nas_stagnation_bars),
            conviction_scale_nas_a_plus=_env_float("CONVICTION_SCALE_NAS_A_PLUS", cls.conviction_scale_nas_a_plus),
            enable_universal_capital_adapter=_env_bool("ENABLE_UNIVERSAL_CAPITAL_ADAPTER", cls.enable_universal_capital_adapter),
            is_cent_account=_env_bool("IS_CENT_ACCOUNT", cls.is_cent_account),
            whale_slice_threshold_lots=_env_float("WHALE_SLICE_THRESHOLD_LOTS", cls.whale_slice_threshold_lots),
            whale_max_child_slice_lots=_env_float("WHALE_MAX_CHILD_SLICE_LOTS", cls.whale_max_child_slice_lots),
            enable_l2_depth=_env_bool("ENABLE_L2_DEPTH", cls.enable_l2_depth),
            l2_depth_levels=_env_int("L2_DEPTH_LEVELS", cls.l2_depth_levels),
            l2_min_obi_threshold=_env_float("L2_MIN_OBI_THRESHOLD", cls.l2_min_obi_threshold),
        )



@dataclass
class Config:
    mt5: MT5Config = field(default_factory=MT5Config)
    trading: TradingConfig = field(default_factory=TradingConfig)

    @classmethod
    def load(cls, env_path: Optional[str] = None, config_path: Optional[str] = None) -> "Config":
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()
        cfg = cls(mt5=MT5Config.from_env(), trading=TradingConfig.from_env())
        if config_path:
            resolved = Path(config_path).resolve()
            if not resolved.exists():
                log.warning("Config file not found: %s", config_path)
            else:
                with open(resolved) as f:
                    overrides = json.load(f)
                mt5_overrides = overrides.get("mt5", {})
                for k, v in mt5_overrides.items():
                    if hasattr(cfg.mt5, k):
                        setattr(cfg.mt5, k, v)
                trading_overrides = overrides.get("trading", {})
                for k, v in trading_overrides.items():
                    if hasattr(cfg.trading, k):
                        setattr(cfg.trading, k, v)
        # Validate file paths to prevent injection
        for attr in ("state_db_path", "trade_log_path", "log_file", "research_report_dir"):
            p = Path(getattr(cfg.trading, attr))
            if ".." in p.parts:
                log.warning("Path traversal detected in %s: %s — using default", attr, p)
                setattr(cfg.trading, attr, getattr(TradingConfig, attr))
        return cfg
