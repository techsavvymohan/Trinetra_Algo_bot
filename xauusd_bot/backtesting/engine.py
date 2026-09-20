import copy
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..indicators.atr import atr
from ..indicators.moving_averages import ema
from ..indicators.rsi import rsi
from ..models import (
    AccountInfo, Bias, DailyState, ExitReason, PyraCluster, Regime, Session,
    Signal, SignalGrade, TimeframeData, TradeDirection, TradeLeg, TradeStatus,
)
from ..risk.daily_loss import DailyLossTracker
from ..risk.max_dd import MaxDDTracker
from ..risk.position_sizer import PositionSizer
from ..risk.pyramid_manager import PyramidManager
from ..order.exit import ExitManager
from ..order.partial_close import PartialCloseManager
from ..strategy.bias_detector import BiasDetector
from ..strategy.signal_scorer import SignalScorer
from ..strategy.timeframe_hierarchy import TimeframeHierarchy
from ..strategy.trigger import TriggerDetector
from ..strategy.zone_detector import ZoneDetector
from ..filters.session_filter import SessionFilter
from ..utils.time_utils import current_session, minutes_since
from ..strategy.volatility_regime import VolatilityRegimeEngine, RegimeState
from ..utils.asset_specs import get_asset_spec

log = logging.getLogger("xauusd_bot.backtest")


class BacktestEngine:
    def __init__(self, config: Config, initial_balance: Optional[float] = None, symbol: Optional[str] = None,
                 start_date: Optional[datetime] = None, end_date: Optional[datetime] = None):
        self.cfg = config
        self.start_date = start_date
        self.end_date = end_date
        if initial_balance is not None:
            self.cfg.trading.backtest_initial_balance = initial_balance
            self.cfg.trading.initial_account_balance = initial_balance
        self.symbol = symbol or getattr(self.cfg.trading, "symbol", "XAUUSD")
        if symbol is not None:
            self.cfg.trading.symbol = symbol
        self.bias = BiasDetector(
            config.trading.ema_fast, config.trading.ema_medium, config.trading.ema_slow,
            config.trading.rsi_period, config.trading.rsi_mid_upper, config.trading.rsi_mid_lower,
        )
        self.zone = ZoneDetector(config.trading.vwap_period, config.trading.min_structure_swing_bars,
                                 config.trading.max_structure_swing_bars)
        from ..strategy.sideways_detector import SidewaysDetector
        self.sideways = SidewaysDetector(
            chop_threshold=config.trading.sideways_chop_threshold,
            adx_threshold=config.trading.sideways_adx_threshold,
            bandwidth_squeeze_pct=config.trading.sideways_bandwidth_squeeze_pct,
        ) if getattr(config.trading, "enable_sideways_filter", True) else None
        self.hierarchy = TimeframeHierarchy(
            self.bias,
            self.zone,
            sideways_detector=self.sideways,
            session_agnostic=not getattr(config.trading, "enable_session_filter", False),
        )
        self.scorer = SignalScorer(config.trading.signal_score_a_min, config.trading.signal_score_b_min)
        self.trigger = TriggerDetector(config.trading.ema_fast, config.trading.rsi_period,
                                       config.trading.rsi_mid_upper, config.trading.rsi_mid_lower)
        self.exit_mgr = ExitManager(config.trading)
        init_bal = initial_balance if initial_balance is not None else getattr(self.cfg.trading, "initial_account_balance", self.cfg.trading.backtest_initial_balance)
        self.cfg.trading.backtest_initial_balance = init_bal
        if hasattr(config.trading, "get_risk_per_trade"):
            initial_risk = config.trading.get_risk_per_trade(self.symbol) * 100.0
        else:
            initial_risk = config.trading.pyramid_initial_risk_pct
        self.sizer = PositionSizer(
            initial_risk,
            config.trading.max_pyramid_entries,
            enable_profit_compounding=getattr(config.trading, "enable_profit_compounding", True),
            initial_balance=init_bal,
            compounding_cap_mult=getattr(config.trading, "compounding_cap_mult", 5.0),
        )
        self.partial_close = PartialCloseManager(
            take_profit_r=getattr(config.trading, "partial_tp_tranche1_r", config.trading.partial_take_profit_r),
            close_pct=getattr(config.trading, "partial_tp_tranche1_pct", getattr(config.trading, "partial_close_pct", 25.0)),
            tranche2_r=getattr(config.trading, "partial_tp_tranche2_r", 2.2),
            tranche2_pct=getattr(config.trading, "partial_tp_tranche2_pct", 35.0),
        )
        self.daily_loss = DailyLossTracker(
            config.trading.daily_loss_limit_pct, config.trading.daily_loss_buffer_pct,
            config.trading.broker_daily_reset_hour, config.trading.broker_daily_reset_tz,
        )
        self.max_dd = MaxDDTracker(config.trading.max_dd_limit_pct, config.trading.max_dd_buffer_pct)
        self.pyramid_mgr = PyramidManager(config.trading.max_pyramid_entries, config.trading.pyramid_add_trigger_r)
        self.session_filter = SessionFilter(
            config.trading.session_london_open, config.trading.session_london_close,
            config.trading.session_ny_open, config.trading.session_ny_close,
        )
        self.trades: List[dict] = []
        self._clusters: List[PyraCluster] = []
        self._pending_fvg_orders: List[dict] = []
        self._session_trades_count: int = 0
        self._london_trades_today: int = 0
        self._ny_trades_today: int = 0
        self._current_session_date: Optional[object] = None
        self._last_exit_time: Optional[datetime] = None
        self._ablation_counters: Dict[str, int] = defaultdict(
            int,
            sweeps_detected=0,
            reclaims_confirmed=0,
            displacement_confirmed=0,
            mss_confirmed=0,
            fvg_created=0,
            orders_placed=0,
            orders_filled=0,
            orders_expired=0,
        )
        # Dynamic Volatility-Regime Engine (zero date/month hardcoding)
        self._vr_engine = VolatilityRegimeEngine()
        self._current_regime: RegimeState = RegimeState()  # default NEUTRAL
        # Guard 5 (XAU): Intra-Session Consecutive-Loss Cooldown
        self._xau_g5_consec_losses: int = 0
        self._xau_g5_last_day: Optional[object] = None
        self._xau_g5_paused_today: bool = False
        # Guard 5b (XAU): London-session specific SL pause
        # After 1 SL hit during London (07:45-10:30 UTC), block further London entries that day
        self._xau_london_paused_today: bool = False
        # London Profit Protect: after 1 winning trade in London, session goal achieved -> protect profit
        self._xau_london_won_today: bool = False
        # Guard 5 (NAS): Intra-Session Consecutive-Loss Cooldown for Nasdaq 100
        self._nas_g5_consec_losses: int = 0
        self._nas_g5_last_day: Optional[object] = None
        self._nas_g5_paused_today: bool = False


    def run(self, data: Dict) -> dict:
        if data and isinstance(next(iter(data.values())), dict):
            data = self._convert_dicts(data)
        if "M1" not in data:
            log.error("M1 data required for backtest")
            return {}

        # Auto-resample M1 into M15 if M15 is missing
        if "M15" not in data or not data["M15"]:
            data["M15"] = self._resample_m1_to_m15(data["M1"])
            log.info("🎯 Auto-Resampled M1 into M15 for backtest (%d M15 bars created)", len(data["M15"].close))

        m1 = data["M1"]
        account = AccountInfo(
            balance=self.cfg.trading.backtest_initial_balance,
            equity=self.cfg.trading.backtest_initial_balance,
        )
        self.daily_loss.update(account)
        self.max_dd.reset(account.equity)
        hierarchy_result = None
        data_all = None

        for i in range(100, len(m1.close)):
            current_time = m1.time[i]
            current_price = m1.close[i]
            account.server_time = current_time

            if self.start_date is not None:
                t_chk = current_time.replace(tzinfo=None) if getattr(current_time, "tzinfo", None) else current_time
                s_chk = self.start_date.replace(tzinfo=None) if getattr(self.start_date, "tzinfo", None) else self.start_date
                if t_chk < s_chk:
                    continue

            if self.end_date is not None:
                t_chk = current_time.replace(tzinfo=None) if getattr(current_time, "tzinfo", None) else current_time
                e_chk = self.end_date.replace(tzinfo=None) if getattr(self.end_date, "tzinfo", None) else self.end_date
                if t_chk > e_chk:
                    break

            account.equity = self._compute_equity(account.balance, current_price, i)
            self.daily_loss.update(account)
            self.max_dd.update(account.equity)

            if self.daily_loss.kill_switch_engaged() or self.max_dd.kill_switch_engaged():
                self._close_all(current_price)
                continue

            is_fvg_strat = getattr(self.cfg.trading, "strategy_trigger_type", "momentum") in (
                "xau_liquidity_sweep_fvg_m1", "liquidity_sweep_fvg"
            )

            # Check and track session window & daily session reset
            ecosystem_mode = getattr(self.cfg.trading, "xau_ecosystem_mode", True)
            s_start = getattr(self.cfg.trading, "xau_session_start", "10:00")
            s_end = getattr(self.cfg.trading, "xau_session_end", "11:00")
            s_tz = getattr(self.cfg.trading, "xau_session_timezone", "America/New_York")
            from ..utils.time_utils import is_in_ny_session, to_ny_time
            if ecosystem_mode and current_time is not None:
                if current_time.weekday() == 1 and not getattr(self.cfg.trading, "tuesday_trade_enabled", True):
                    continue

                h_utc = current_time.hour if hasattr(current_time, "hour") else 0
                m_utc = current_time.minute if hasattr(current_time, "minute") else 0
                spec_sym = get_asset_spec(self.symbol)
                is_gold = spec_sym["is_gold"]
                is_index = spec_sym["is_index"]

                if getattr(self.cfg.trading, "xau_strict_killzones", True) and is_gold:
                    # Friday filter: Skip entire day if Friday trading disabled for Gold
                    if not getattr(self.cfg.trading, "xau_friday_trade_enabled", False) and current_time.weekday() == 4:
                        continue

                    # London Cash Open (08:00 - 10:30 UTC)
                    lon_start_h = getattr(self.cfg.trading, "xau_london_start_hour", 8)
                    lon_start_m = getattr(self.cfg.trading, "xau_london_start_minute", 0)
                    in_london = (h_utc > lon_start_h or (h_utc == lon_start_h and m_utc >= lon_start_m)) and (h_utc < 10 or (h_utc == 10 and m_utc <= 30))
                    if getattr(self.cfg.trading, "xau_friday_skip_london", True) and current_time.weekday() == 4:
                        in_london = False

                    # NY Core Session (13:30 - 14:45 UTC cutoff)
                    ny_end_h = getattr(self.cfg.trading, "xau_london_close_cutoff_hour", 14)
                    ny_end_m = getattr(self.cfg.trading, "xau_london_close_cutoff_min", 45)
                    in_ny_core = (13 < h_utc < ny_end_h) or (h_utc == 13 and m_utc >= 30) or (h_utc == ny_end_h and m_utc <= ny_end_m)

                    if getattr(self.cfg.trading, "friday_skip_ny_session", False) and current_time.weekday() == 4:
                        in_ny_core = False
                    cutoff_h = getattr(self.cfg.trading, "xau_session_cutoff_hour", 24)
                    if cutoff_h < 24 and h_utc >= cutoff_h:
                        in_ny_core = False
                    in_session = in_london or in_ny_core
                elif is_index:
                    in_ny_core = self.cfg.trading.is_in_nas_session(current_time) if hasattr(self.cfg.trading, "is_in_nas_session") else ((13 < h_utc < 20) or (h_utc == 13 and m_utc >= 30))
                    in_session = in_ny_core
                else:
                    in_ny_core = is_in_ny_session(current_time, s_start, s_end, s_tz)
                    in_london = (7 <= h_utc < 9) if getattr(self.cfg.trading, "xau_enable_london_asian_sweep", True) else False
                    in_session = in_ny_core or in_london
            else:
                in_session = is_in_ny_session(current_time, s_start, s_end, s_tz) if current_time else True

            if current_time:
                ny_date = to_ny_time(current_time, s_tz).date()
                if self._current_session_date != ny_date:
                    self._current_session_date = ny_date
                    self._session_trades_count = 0
                    self._london_trades_today = 0
                    self._ny_trades_today = 0
                    # Guard 5 (XAU): reset intra-session consecutive loss tracker daily
                    if self._xau_g5_last_day != ny_date:
                        self._xau_g5_last_day = ny_date
                        self._xau_g5_consec_losses = 0
                        self._xau_g5_paused_today = False
                        self._xau_london_paused_today = False
                        self._xau_london_won_today = False
                    # Guard 5 (NAS): reset Nasdaq consecutive loss tracker daily
                    if self._nas_g5_last_day != ny_date:
                        self._nas_g5_last_day = ny_date
                        self._nas_g5_consec_losses = 0
                        self._nas_g5_paused_today = False

            # Expire pending orders if outside active session
            if is_fvg_strat and self._pending_fvg_orders and not in_session:
                for po in list(self._pending_fvg_orders):
                    self._pending_fvg_orders.remove(po)
                    self._ablation_counters["orders_expired"] += 1

            if i % 5 == 0 or hierarchy_result is None or data_all is None:
                m15 = self._slice_data(data, "M15", i, current_time)
                if not m15:
                    continue

                if is_fvg_strat:
                    m5 = None
                    h1 = self._slice_data(data, "H1", i, current_time) if ((getattr(self.cfg.trading, "xau_london_require_h1_trend", False) and is_gold) or (getattr(self.cfg.trading, "nas_require_h1_trend", True) and is_index)) else None
                    h4 = self._slice_data(data, "H4", i, current_time) if getattr(self.cfg.trading, "xau_h4_bias_guard", False) and is_gold else None
                else:
                    m5 = self._slice_data(data, "M5", i, current_time)
                    h1 = self._slice_data(data, "H1", i, current_time)
                    h4 = self._slice_data(data, "H4", i, current_time)
                    if not all([m5, m15, h1, h4]):
                        continue

                m1_start = max(0, i + 1 - 100)
                m1_slice = TimeframeData(
                    tf="M1",
                    time=m1.time[m1_start:i+1],
                    open=m1.open[m1_start:i+1],
                    high=m1.high[m1_start:i+1],
                    low=m1.low[m1_start:i+1],
                    close=m1.close[m1_start:i+1],
                    tick_volume=m1.tick_volume[m1_start:i+1],
                    spread=m1.spread[m1_start:i+1],
                )
                data_all = {"M1": m1_slice, "M5": m5, "M15": m15, "H1": h1, "H4": h4}
                hierarchy_result = self.hierarchy.evaluate(data_all, Session.LONDON)
                # Dynamic Volatility-Regime classification (M15 driven, updated every 5 bars)
                if m15 and len(m15.close) >= 20:
                    self._current_regime = self._vr_engine.classify(m15, m1_slice)

            if not data_all or not hierarchy_result:
                continue

            # Ensure M1 in data_all is always updated to the current bar i
            m1_start = max(0, i + 1 - 100)
            data_all["M1"] = TimeframeData(
                tf="M1",
                time=m1.time[m1_start:i+1],
                open=m1.open[m1_start:i+1],
                high=m1.high[m1_start:i+1],
                low=m1.low[m1_start:i+1],
                close=m1.close[m1_start:i+1],
                tick_volume=m1.tick_volume[m1_start:i+1],
                spread=m1.spread[m1_start:i+1],
            )

            # Friday Weekend Guard: Expire all pending limit orders when cutoff reached
            if getattr(self.cfg.trading, "friday_weekend_guard", True) and current_time is not None:
                from ..filters.session_filter import is_friday_weekend_close
                fw_h = getattr(self.cfg.trading, "friday_close_cutoff_hour", 20)
                fw_m = getattr(self.cfg.trading, "friday_close_cutoff_min", 45)
                if is_friday_weekend_close(current_time, fw_h, fw_m):
                    if self._pending_fvg_orders:
                        self._pending_fvg_orders.clear()

            # Check and advance pending FVG limit orders
            if is_fvg_strat and self._pending_fvg_orders:
                for po in list(self._pending_fvg_orders):
                    # BUG-07 FIX: only age pending orders while the market session is active
                    if in_session:
                        po["bars_active"] += 1
                    filled = False
                    sig = po["signal"]
                    fvg_high = getattr(sig, "fvg_high", 0.0)
                    fvg_low = getattr(sig, "fvg_low", 0.0)
                    o_bar = m1.open[i]
                    h_bar = m1.high[i]
                    l_bar = m1.low[i]
                    c_bar = m1.close[i]

                    fvg_tol_pct = getattr(self.cfg.trading, "fvg_adaptive_retest_tolerance_pct", 0.25)
                    fvg_span = abs(fvg_high - fvg_low) if (fvg_high > 0 and fvg_low > 0) else 0.0
                    spec_tol = get_asset_spec(self.symbol)
                    min_tol = 0.25 if spec_tol["is_gold"] else 1.0
                    tol = max(min_tol, fvg_span * fvg_tol_pct)

                    require_retest = getattr(self.cfg.trading, "nas_require_retest" if spec_tol["is_index"] else "xau_require_retest", True)
                    if require_retest:
                        touched = po.get("retest_touched", False)
                        if po["direction"] == TradeDirection.BUY:
                            if l_bar <= (po["limit_price"] + tol):
                                touched = True
                                po["retest_touched"] = True
                        else:
                            if h_bar >= (po["limit_price"] - tol):
                                touched = True
                                po["retest_touched"] = True

                        if touched:
                            inv_buf = 0.5 * tol
                            if po["direction"] == TradeDirection.BUY:
                                if fvg_low > 0 and c_bar < (fvg_low - inv_buf):
                                    self._pending_fvg_orders.remove(po)
                                    self._ablation_counters["orders_expired"] += 1
                                    continue
                                lower_wick = min(o_bar, c_bar) - l_bar
                                body = abs(c_bar - o_bar)
                                bar_range = h_bar - l_bar
                                if (c_bar > o_bar or lower_wick >= 0.4 * body or (bar_range > 0 and (c_bar - l_bar) / bar_range >= 0.5)) and c_bar >= (fvg_low - inv_buf):
                                    filled = True
                            else:
                                if fvg_high > 0 and c_bar > (fvg_high + inv_buf):
                                    self._pending_fvg_orders.remove(po)
                                    self._ablation_counters["orders_expired"] += 1
                                    continue
                                upper_wick = h_bar - max(o_bar, c_bar)
                                body = abs(c_bar - o_bar)
                                bar_range = h_bar - l_bar
                                if (c_bar < o_bar or upper_wick >= 0.4 * body or (bar_range > 0 and (h_bar - c_bar) / bar_range >= 0.5)) and c_bar <= (fvg_high + inv_buf):
                                    filled = True
                    elif getattr(self.cfg.trading, "xau_enable_pre_fill_guard", True) and (fvg_high > 0 or fvg_low > 0):
                        if po["direction"] == TradeDirection.SELL:
                            if m1.high[i] >= po["limit_price"]:
                                if fvg_high > 0 and m1.close[i] > fvg_high:
                                    # Runaway green bar blew straight through FVG resistance -> cancel!
                                    self._pending_fvg_orders.remove(po)
                                    self._ablation_counters["orders_expired"] += 1
                                    continue
                                else:
                                    filled = True
                        else:
                            if m1.low[i] <= po["limit_price"]:
                                if fvg_low > 0 and m1.close[i] < fvg_low:
                                    # Runaway red bar blew straight through FVG support -> cancel!
                                    self._pending_fvg_orders.remove(po)
                                    self._ablation_counters["orders_expired"] += 1
                                    continue
                                else:
                                    filled = True
                    else:
                        if po["direction"] == TradeDirection.BUY:
                            if m1.low[i] <= po["limit_price"]:
                                filled = True
                        else:
                            if m1.high[i] >= po["limit_price"]:
                                filled = True

                    if filled:
                        sig = po["signal"]
                        actual_entry_price = po["limit_price"]
                        if require_retest:
                            spec_sig = get_asset_spec(sig.symbol, c_bar)
                            point_sz = spec_sig["tick_sz"]
                            slip_pts = getattr(self.cfg.trading, "backtest_slippage_points", 0.5) if getattr(self.cfg.trading, "backtest_apply_friction", True) else 0.0
                            slip_dist = slip_pts * point_sz
                            if sig.direction == TradeDirection.BUY:
                                cand_entry = c_bar + slip_dist
                                if cand_entry < po["tp_price"] and cand_entry > po["sl_price"]:
                                    actual_entry_price = round(cand_entry, spec_sig["digits"])
                            else:
                                cand_entry = c_bar - slip_dist
                                if cand_entry > po["tp_price"] and cand_entry < po["sl_price"]:
                                    actual_entry_price = round(cand_entry, spec_sig["digits"])

                        pyra_target = po.get("pyramid_cluster")
                        if pyra_target and pyra_target.status == TradeStatus.OPEN:
                            # Add as compound pyramid scale-in leg to existing runner cluster
                            leg = TradeLeg(
                                direction=sig.direction, entry_price=actual_entry_price, lot_size=po["lot_size"],
                                symbol=sig.symbol, sl_price=pyra_target.collective_sl, tp_price=po["tp_price"],
                                open_time=current_time, status=TradeStatus.OPEN,
                            )
                            pyra_target.legs.append(leg)
                            self._ablation_counters["pyramid_legs_added"] = self._ablation_counters.get("pyramid_legs_added", 0) + 1
                        else:
                            cluster = PyraCluster(
                                signal_id=sig.id, direction=sig.direction, entry_tf="M1",
                                symbol=sig.symbol, collective_sl=po["sl_price"],
                                open_time=current_time, status=TradeStatus.OPEN,
                                signal=sig,
                            )
                            leg = TradeLeg(
                                direction=sig.direction, entry_price=actual_entry_price, lot_size=po["lot_size"],
                                symbol=sig.symbol, sl_price=po["sl_price"], tp_price=po["tp_price"],
                                open_time=current_time, status=TradeStatus.OPEN,
                            )
                            leg._signal_grade = sig.grade
                            cluster.legs.append(leg)
                            self._clusters.append(cluster)
                        self._session_trades_count += 1
                        if ecosystem_mode and current_time is not None:
                            h_utc = current_time.hour if hasattr(current_time, "hour") else 0
                            lon_cutoff = getattr(self.cfg.trading, "xau_london_end_hour", 10)
                            if 7 <= h_utc < lon_cutoff:
                                self._london_trades_today += 1
                            else:
                                self._ny_trades_today += 1
                        self._ablation_counters["orders_filled"] += 1
                        self.daily_loss.register_trade()
                        self._pending_fvg_orders.remove(po)
                    elif po["bars_active"] >= po["max_bars"]:
                        self._pending_fvg_orders.remove(po)
                        self._ablation_counters["orders_expired"] += 1

            signal = self._generate_signal(hierarchy_result, data_all, current_price, current_time=current_time)
            if signal and signal.is_tradeable():
                if is_fvg_strat:
                    enable_pyra = getattr(self.cfg.trading, "enable_fvg_pyramiding", True)
                    open_cluster = next((c for c in self._clusters if c.status == TradeStatus.OPEN and c.direction == signal.direction and getattr(c, "symbol", "") == signal.symbol), None)
                    can_pyramid = False
                    if enable_pyra and open_cluster and getattr(open_cluster, "breakeven_activated", False) and len(open_cluster.legs) < getattr(self.cfg.trading, "max_pyramid_entries", 3):
                        can_pyramid = True

                    has_open = any(c.status == TradeStatus.OPEN for c in self._clusters)
                    allow_entry = (not has_open) or can_pyramid
                    max_pending = getattr(self.cfg.trading, "max_concurrent_pending_orders", 2)
                    prevent_dup = getattr(self.cfg.trading, "xau_prevent_duplicate_pending", True)
                    has_same_dir_pending = prevent_dup and any(po["direction"] == signal.direction for po in self._pending_fvg_orders)
                    has_pending = (len(self._pending_fvg_orders) >= max_pending) or has_same_dir_pending
                    max_sess_trades = getattr(self.cfg.trading, "xau_max_trades_per_session", 2)
                    max_daily_trades = getattr(self.cfg.trading, "max_daily_trades", 4)
                    cooldown = getattr(self.cfg.trading, "xau_cooldown_minutes", 5)

                    in_cooldown = False
                    if self._last_exit_time:
                        t_diff = (current_time - self._last_exit_time).total_seconds() / 60.0
                        if t_diff < cooldown:
                            in_cooldown = True

                    same_dir_cooldown = False
                    if getattr(self, "_last_sl_time", None) and getattr(self, "_last_sl_direction", None) == signal.direction:
                        t_sl_diff = (current_time - self._last_sl_time).total_seconds() / 60.0
                        if t_sl_diff < cooldown:
                            same_dir_cooldown = True

                    session_limit_reached = False
                    if ecosystem_mode and current_time is not None:
                        h_utc = current_time.hour if hasattr(current_time, "hour") else 0
                        lon_cutoff = getattr(self.cfg.trading, "xau_london_end_hour", 10)
                        in_lon_window = (7 <= h_utc < lon_cutoff)
                        if in_lon_window:
                            if self._london_trades_today >= max_sess_trades:
                                session_limit_reached = True
                        else:
                            if self._ny_trades_today >= max_sess_trades:
                                session_limit_reached = True


                    # ── El Professor Hidden Guards ─────────────────────────────────────────
                    professor_veto = False
                    spec_prof = get_asset_spec(self.symbol)

                    # Guard 5 (NAS): Intra-Session Consecutive-Loss Cooldown for Nasdaq 100
                    if spec_prof["is_index"] and getattr(self.cfg.trading, "nas_consec_loss_guard", True):
                        nas_max_consec = getattr(self.cfg.trading, "nas_consec_loss_max", 2)
                        if self._nas_g5_paused_today:
                            professor_veto = True
                            log.debug("[%s] NAS G5 Consec-Loss Guard: paused for rest of day (%d consecutive SLs)",
                                      self.symbol, self._nas_g5_consec_losses)

                    if spec_prof["is_gold"]:
                        # Guard 1 (XAU only): London Close Wall — no new entries after 15:45 UTC
                        # Backtested: Win% 41.5%→46.3%, PF 1.54→1.74
                        if getattr(self.cfg.trading, "xau_london_close_guard", True) and current_time is not None:
                            g1_h = getattr(self.cfg.trading, "xau_london_close_cutoff_hour", 15)
                            g1_m = getattr(self.cfg.trading, "xau_london_close_cutoff_min", 45)
                            h_c = current_time.hour if hasattr(current_time, "hour") else 0
                            m_c = current_time.minute if hasattr(current_time, "minute") else 0
                            if h_c > g1_h or (h_c == g1_h and m_c >= g1_m):
                                professor_veto = True
                                log.debug("[%s] G1 London Close Wall: veto at %02d:%02d UTC", self.symbol, h_c, m_c)

                        # Guard 3 Parity (XAU): H4 Macro Trend Bias — block blind counter-trend entries
                        if not professor_veto and getattr(self.cfg.trading, "xau_h4_bias_guard", False):
                            h4_slice = self._slice_data(data, "H4", i, current_time)
                            if h4_slice is not None and len(h4_slice.close) >= getattr(self.cfg.trading, "xau_h4_ema_slow", 50) + 5:
                                g3_fast = getattr(self.cfg.trading, "xau_h4_ema_fast", 9)
                                g3_slow = getattr(self.cfg.trading, "xau_h4_ema_slow", 50)
                                h4_cl = list(h4_slice.close[-60:])
                                k_f, k_s = 2.0 / (g3_fast + 1), 2.0 / (g3_slow + 1)
                                ef = es = h4_cl[0]
                                for p in h4_cl[1:]:
                                    ef = p * k_f + ef * (1 - k_f)
                                    es = p * k_s + es * (1 - k_s)
                                if ef > es and signal.direction == TradeDirection.SELL:
                                    professor_veto = True
                                    log.debug("[%s] XAU Macro Bias: BULLISH H4 vetos SELL signal", self.symbol)
                                elif ef < es and signal.direction == TradeDirection.BUY:
                                    professor_veto = True
                                    log.debug("[%s] XAU Macro Bias: BEARISH H4 vetos BUY signal", self.symbol)

                        # Guard 5 (XAU): Intra-Session Consecutive-Loss Cooldown
                        # After 2 consecutive SL hits today, pause for rest of day.
                        # Targets false-sweep trap clusters (choppy/summer days) with zero date hardcoding.
                        if not professor_veto and getattr(self.cfg.trading, "xau_consec_loss_guard", True):
                            max_consec = getattr(self.cfg.trading, "xau_consec_loss_max", 2)
                            if self._xau_g5_paused_today:
                                professor_veto = True
                                log.debug("[%s] G5 XAU Consec-Loss Guard: paused for rest of day (%d consecutive SLs)",
                                          self.symbol, self._xau_g5_consec_losses)
                            # Guard 5b: London session SL pause
                            # After 1 SL hit during London (07:45-10:30 UTC), block more London entries that day
                            # This is MORE targeted than a hard trade count limit:
                            # - Good days: 1st London trade wins -> no pause -> can take 2nd
                            # - Bad days:  1st London trade loses -> London paused for day -> max 1 bad London trade
                            elif not professor_veto:
                                h_now = current_time.hour if current_time else 0
                                m_now = current_time.minute if current_time else 0
                                in_london_now = self.cfg.trading.is_in_xau_london_killzone(current_time) if hasattr(self.cfg.trading, "is_in_xau_london_killzone") else ((h_now == 7 and m_now >= 45) or (8 <= h_now < 10) or (h_now == 10 and m_now <= 30))
                                if in_london_now:
                                    if self._xau_london_paused_today:
                                        professor_veto = True
                                        log.debug("[%s] G5b London SL Pause: blocked London entry (lost London trade today)", self.symbol)
                                    elif (getattr(self.cfg.trading, "xau_london_protect_profits", True) or getattr(self, "_test_london_win_done", False)) and self._xau_london_won_today:
                                        professor_veto = True
                                        log.debug("[%s] London Profit Protect: won London trade today, locked in profit", self.symbol)

                    # Friday Weekend Guard Entry Veto
                    if not professor_veto and getattr(self.cfg.trading, "friday_weekend_guard", True) and current_time is not None:
                        from ..filters.session_filter import is_friday_weekend_close
                        fw_h = getattr(self.cfg.trading, "friday_close_cutoff_hour", 20)
                        fw_m = getattr(self.cfg.trading, "friday_close_cutoff_min", 45)
                        if is_friday_weekend_close(current_time, fw_h, fw_m):
                            professor_veto = True
                            log.debug("[%s] Friday Weekend Guard: veto at %s", self.symbol, current_time)
                    # ── End Professor Guards ───────────────────────────────────────────────

                    if not professor_veto and allow_entry and not has_pending and self._session_trades_count < max_daily_trades and not session_limit_reached and not in_cooldown and not same_dir_cooldown:
                        remaining = self.daily_loss.remaining_budget_amount()
                        sym = signal.symbol
                        spec = get_asset_spec(sym, signal.entry_price)
                        contract_sz = spec["contract_sz"]
                        tick_sz = spec["tick_sz"]
                        point_val = spec["point_val"]
                        risk_scale = 1.0
                        if getattr(self.cfg.trading, "enable_net_beta_gate", True):
                            has_same_usd = any(
                                c.status == TradeStatus.OPEN and getattr(c, "symbol", "") != sym and c.direction == signal.direction
                                for c in self._clusters
                            )
                            if has_same_usd:
                                risk_scale = getattr(self.cfg.trading, "correlated_usd_risk_scale", 0.60)
                        if getattr(self.cfg.trading, "enable_conviction_sizing", True) and hasattr(self.cfg.trading, "get_conviction_scale"):
                            risk_scale *= self.cfg.trading.get_conviction_scale(signal)
                        if current_time.weekday() == 1 and getattr(self.cfg.trading, "tuesday_reduced_risk", True):
                            tue_scale = getattr(self.cfg.trading, "tuesday_risk_scale", 0.43)
                            risk_scale *= tue_scale
                        if current_time.weekday() == 4 and "XAU" in self.symbol.upper():
                            fri_scale = getattr(self.cfg.trading, "xau_friday_risk_scale", 0.50)
                            risk_scale *= fri_scale
                        lot = self.sizer.calculate_lot_size(
                            account=account, entry_price=signal.entry_price, sl_price=signal.sl_price,
                            direction=signal.direction, point_value=point_val, contract_size=contract_sz,
                            tick_size=tick_sz, remaining_budget=remaining, risk_scale=risk_scale,
                        )
                        if lot > 0:
                            signal.lot_size = lot
                            if getattr(signal, "setup_type", "") == "OVERLAP_PULLBACK":
                                cluster = PyraCluster(
                                    signal_id=signal.id, direction=signal.direction, entry_tf="M1",
                                    symbol=signal.symbol, collective_sl=signal.sl_price,
                                    open_time=current_time, status=TradeStatus.OPEN,
                                )
                                leg = TradeLeg(
                                    direction=signal.direction, entry_price=signal.entry_price, lot_size=lot,
                                    symbol=signal.symbol, sl_price=signal.sl_price, tp_price=signal.tp_price,
                                    open_time=current_time, status=TradeStatus.OPEN,
                                )
                                cluster.legs.append(leg)
                                cluster.r_distance()
                                self._clusters.append(cluster)
                                self._session_trades_count += 1
                                self._ablation_counters["orders_filled"] += 1
                                self.daily_loss.register_trade()
                            else:
                                max_expiry = self.cfg.trading.get_fvg_expiry_bars(self.symbol) if hasattr(self.cfg.trading, "get_fvg_expiry_bars") else getattr(self.cfg.trading, "xau_retest_max_bars", 8)
                                self._pending_fvg_orders.append({
                                    "signal": signal,
                                    "direction": signal.direction,
                                    "limit_price": signal.entry_price,
                                    "sl_price": signal.sl_price,
                                    "tp_price": signal.tp_price,
                                    "lot_size": lot,
                                    "bars_active": 0,
                                    "max_bars": max_expiry,
                                    "retest_touched": False,
                                    "pyramid_cluster": open_cluster if can_pyramid else None,
                                })
                                self._ablation_counters["orders_placed"] += 1
                else:
                    has_active = any(c.status == TradeStatus.OPEN and c.direction == signal.direction for c in self._clusters)
                    if has_active:
                        for cluster in self._clusters:
                            if cluster.status == TradeStatus.OPEN and cluster.direction == signal.direction:
                                if self.pyramid_mgr.can_add_leg(cluster, signal.entry_price, cluster.avg_entry_price(), cluster.collective_sl):
                                    remaining = self.daily_loss.remaining_budget_amount()
                                    sym = signal.symbol
                                    spec = get_asset_spec(sym, current_price)
                                    contract_sz = spec["contract_sz"]
                                    tick_sz = spec["tick_sz"]
                                    point_val = spec["point_val"]
                                    lot = self.sizer.calculate_lot_size(
                                        account=account, entry_price=current_price, sl_price=signal.sl_price,
                                        direction=signal.direction, point_value=point_val, contract_size=contract_sz,
                                        tick_size=tick_sz, remaining_budget=remaining,
                                    )
                                    if lot > 0:
                                        leg = TradeLeg(
                                            direction=signal.direction, entry_price=current_price, lot_size=lot,
                                            symbol=signal.symbol, sl_price=signal.sl_price, tp_price=signal.tp_price,
                                            open_time=signal.timestamp, status=TradeStatus.OPEN,
                                        )
                                        cluster.legs.append(leg)
                                        cluster.collective_sl = cluster.avg_entry_price()
                    else:
                        cluster = self._execute_backtest_order(signal, account, data_all, i, current_price, current_time=current_time)
                        if cluster:
                            self._clusters.append(cluster)

            for cluster in list(self._clusters):
                if cluster.status != TradeStatus.OPEN:
                    continue
                m1_start = max(0, i + 1 - 30)
                m1_slice = TypeSliceData(m1, m1_start, i + 1)
                data_all_slice = {
                    "M1": m1_slice, "M5": m5, "M15": m15,
                }
                actions = self._manage_backtest_exits(cluster, data_all_slice, i, current_price)
                for action in actions:
                    self.trades.append(action)

                if cluster.status == TradeStatus.CLOSED:
                    for leg in cluster.legs:
                        if leg.status == TradeStatus.CLOSED and leg.exit_price and not getattr(leg, "_balance_credited", False):
                            leg._balance_credited = True
                            diff = (leg.exit_price - leg.entry_price) if leg.direction == TradeDirection.BUY else (leg.entry_price - leg.exit_price)
                            sym = getattr(leg, "symbol", self.symbol)
                            spec = get_asset_spec(sym, leg.entry_price or current_price)
                            c_sz = spec["contract_sz"]
                            raw_pnl = diff * leg.lot_size * c_sz
                            friction_on = getattr(self.cfg.trading, "backtest_apply_friction", True)
                            comm_rate = self.cfg.trading.get_commission_per_lot(sym) if (friction_on and hasattr(self.cfg.trading, "get_commission_per_lot")) else (getattr(self.cfg.trading, "backtest_commission_per_lot", 6.0) if friction_on else 0.0)
                            pnl = raw_pnl - (comm_rate * leg.lot_size)
                            leg.pnl = round(pnl, 2)
                            # BUG-01 FIX: account.balance is the single source of truth for live equity.
                            # _report() will reuse leg.pnl (already computed here) to avoid double commission.
                            account.balance += pnl

                    # ── Consecutive-Loss Guard Tracker (updates after each cluster close) ──
                    # BUG-08 FIX: use cluster.open_time (entry time) not current_time (exit time)
                    # to correctly determine WHICH session the losing trade was originally placed in.
                    _entry_time = cluster.open_time if cluster.open_time is not None else current_time

                    # XAU Guard 5 / 5b
                    if ("XAU" in self.symbol or "GOLD" in self.symbol.upper()) and getattr(self.cfg.trading, "xau_consec_loss_guard", True):
                        if not self._xau_g5_paused_today:
                            cluster_pnl = 0.0
                            for leg in cluster.legs:
                                if leg.status == TradeStatus.CLOSED and leg.exit_price:
                                    p_pts = (leg.exit_price - leg.entry_price) if leg.direction == TradeDirection.BUY else (leg.entry_price - leg.exit_price)
                                    cluster_pnl += p_pts
                            max_consec = getattr(self.cfg.trading, "xau_consec_loss_max", 2)
                            if cluster_pnl > 0:
                                self._xau_g5_consec_losses = 0
                                if _entry_time is not None:
                                    _h = _entry_time.hour if hasattr(_entry_time, 'hour') else 0
                                    _m = _entry_time.minute if hasattr(_entry_time, 'minute') else 0
                                    _in_lon = self.cfg.trading.is_in_xau_london_killzone(_entry_time) if hasattr(self.cfg.trading, "is_in_xau_london_killzone") else ((_h == 7 and _m >= 45) or (8 <= _h < 10) or (_h == 10 and _m <= 30))
                                    if _in_lon:
                                        self._xau_london_won_today = True
                            else:
                                self._xau_g5_consec_losses += 1
                                if _entry_time is not None:
                                    _h = _entry_time.hour if hasattr(_entry_time, 'hour') else 0
                                    _m = _entry_time.minute if hasattr(_entry_time, 'minute') else 0
                                    _in_lon = self.cfg.trading.is_in_xau_london_killzone(_entry_time) if hasattr(self.cfg.trading, "is_in_xau_london_killzone") else ((_h == 7 and _m >= 45) or (8 <= _h < 10) or (_h == 10 and _m <= 30))
                                    if _in_lon:
                                        self._xau_london_paused_today = True
                                        log.debug("[%s] G5b London SL pause activated (entry was %02d:%02d UTC)",
                                                  self.symbol, _h, _m)
                                log.debug("[%s] G5: SL hit #%d (streak=%d, limit=%d)",
                                          self.symbol, self._xau_g5_consec_losses, self._xau_g5_consec_losses, max_consec)
                                if self._xau_g5_consec_losses >= max_consec:
                                    self._xau_g5_paused_today = True
                                    log.debug("[%s] G5 XAU Consec-Loss Guard: %d consecutive SLs — PAUSED for rest of day",
                                              self.symbol, self._xau_g5_consec_losses)

                    # NAS Guard 5 (BUG-06 FIX)
                    spec_cl = get_asset_spec(self.symbol)
                    if spec_cl["is_index"] and getattr(self.cfg.trading, "nas_consec_loss_guard", True):
                        if not self._nas_g5_paused_today:
                            nas_cluster_pnl = sum(
                                ((leg.exit_price - leg.entry_price) if leg.direction == TradeDirection.BUY else (leg.entry_price - leg.exit_price))
                                for leg in cluster.legs
                                if leg.status == TradeStatus.CLOSED and leg.exit_price
                            )
                            nas_max_consec = getattr(self.cfg.trading, "nas_consec_loss_max", 2)
                            if nas_cluster_pnl > 0:
                                self._nas_g5_consec_losses = 0
                            else:
                                self._nas_g5_consec_losses += 1
                                log.debug("[%s] NAS G5: SL hit #%d (streak=%d, limit=%d)",
                                          self.symbol, self._nas_g5_consec_losses, self._nas_g5_consec_losses, nas_max_consec)
                                if self._nas_g5_consec_losses >= nas_max_consec:
                                    self._nas_g5_paused_today = True
                                    log.debug("[%s] NAS G5 Consec-Loss Guard: %d consecutive SLs — PAUSED for rest of day",
                                              self.symbol, self._nas_g5_consec_losses)

        return self._report()

    @staticmethod
    def _convert_dicts(data: dict) -> Dict[str, TimeframeData]:
        result = {}
        for tf, d in data.items():
            times = [datetime.fromisoformat(t) if isinstance(t, str) else t for t in d.get("time", [])]
            result[tf] = TimeframeData(
                tf=tf,
                time=times,
                open=d.get("open", []),
                high=d.get("high", []),
                low=d.get("low", []),
                close=d.get("close", []),
                tick_volume=d.get("tick_volume", []) or d.get("volume", []),
                spread=d.get("spread", []),
            )
        return result

    @staticmethod
    def _resample_m1_to_m15(m1: TimeframeData) -> TimeframeData:
        """Accurately resample M1 TimeframeData into M15 TimeframeData without lookahead."""
        times_m1 = m1.time
        opens_m1 = m1.open
        highs_m1 = m1.high
        lows_m1 = m1.low
        closes_m1 = m1.close
        vols_m1 = m1.tick_volume
        spreads_m1 = m1.spread

        m15_times, m15_opens, m15_highs, m15_lows, m15_closes, m15_vols, m15_spreads = [], [], [], [], [], [], []
        cur_bucket = None
        b_open = b_high = b_low = b_close = b_vol = b_spread = None

        for i in range(len(times_m1)):
            dt = times_m1[i]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            elif isinstance(dt, (int, float)):
                dt = datetime.fromtimestamp(dt, tz=timezone.utc)

            bucket_min = (dt.minute // 15) * 15
            bucket_dt = dt.replace(minute=bucket_min, second=0, microsecond=0)

            if cur_bucket != bucket_dt:
                if cur_bucket is not None:
                    m15_times.append(cur_bucket)
                    m15_opens.append(b_open)
                    m15_highs.append(b_high)
                    m15_lows.append(b_low)
                    m15_closes.append(b_close)
                    m15_vols.append(b_vol)
                    m15_spreads.append(b_spread)
                cur_bucket = bucket_dt
                b_open = opens_m1[i]
                b_high = highs_m1[i]
                b_low = lows_m1[i]
                b_close = closes_m1[i]
                b_vol = vols_m1[i] if vols_m1 else 1
                b_spread = spreads_m1[i] if spreads_m1 else 0
            else:
                b_high = max(b_high, highs_m1[i])
                b_low = min(b_low, lows_m1[i])
                b_close = closes_m1[i]
                if vols_m1:
                    b_vol += vols_m1[i]
                if spreads_m1:
                    b_spread = spreads_m1[i]

        if cur_bucket is not None:
            m15_times.append(cur_bucket)
            m15_opens.append(b_open)
            m15_highs.append(b_high)
            m15_lows.append(b_low)
            m15_closes.append(b_close)
            m15_vols.append(b_vol)
            m15_spreads.append(b_spread)

        return TimeframeData(
            tf="M15",
            time=m15_times,
            open=m15_opens,
            high=m15_highs,
            low=m15_lows,
            close=m15_closes,
            tick_volume=m15_vols,
            spread=m15_spreads,
        )

    def _slice_data(self, data: Dict[str, TimeframeData], tf: str, idx: int, current_time: Optional[datetime] = None) -> Optional[TimeframeData]:
        if tf not in data:
            return None
        src = data[tf]
        required = 100
        if current_time is not None and src.time:
            import bisect
            from datetime import timedelta
            tf_minutes = {"M1": 1, "M3": 3, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}.get(tf, 1)
            cutoff = current_time - timedelta(minutes=tf_minutes)
            src_sample = src.time[0]
            if getattr(current_time, "tzinfo", None) is not None and getattr(src_sample, "tzinfo", None) is None:
                cutoff = cutoff.replace(tzinfo=None)
            elif getattr(current_time, "tzinfo", None) is None and getattr(src_sample, "tzinfo", None) is not None:
                cutoff = cutoff.replace(tzinfo=src_sample.tzinfo)

            end = bisect.bisect_right(src.time, cutoff)
            if end < 15:
                return None
            start = max(0, end - required)
            return TimeframeData(
                tf=tf,
                time=src.time[start:end],
                open=src.open[start:end],
                high=src.high[start:end],
                low=src.low[start:end],
                close=src.close[start:end],
                tick_volume=src.tick_volume[start:end],
                spread=src.spread[start:end],
            )
        ratio = {"M5": 1, "M15": 3, "M30": 6, "H1": 12, "H4": 48}.get(tf, 1)
        required = 200
        start = max(0, idx // ratio - required)
        end = idx // ratio
        if end >= len(src.close) or end <= start:
            return None
        return TimeframeData(
            tf=tf,
            time=src.time[start:end],
            open=src.open[start:end],
            high=src.high[start:end],
            low=src.low[start:end],
            close=src.close[start:end],
            tick_volume=src.tick_volume[start:end],
            spread=src.spread[start:end],
        )

    def _generate_signal(self, hierarchy_result: dict, data_all: dict, price: float, current_time: Optional[datetime] = None) -> Optional[Signal]:
        trigger_type = getattr(self.cfg.trading, "strategy_trigger_type", "momentum")

        if trigger_type in ("xau_liquidity_sweep_fvg_m1", "liquidity_sweep_fvg"):
            m15_data = data_all.get("M15")
            m1_data = data_all.get("M1")
            if not m15_data or not m1_data or len(m15_data.close) < 15 or len(m1_data.close) < 15:
                return None

            m1_atr = atr(m1_data.high, m1_data.low, m1_data.close, getattr(self.cfg.trading, "xau_atr_period", 14)) or 1.0
            ecosystem_mode = getattr(self.cfg.trading, "xau_ecosystem_mode", True)
            seq = None

            sym = getattr(self.cfg.trading, "symbol", "XAUUSD")
            spec = get_asset_spec(self.symbol or sym, price)
            is_index = spec["is_index"]
            is_gold = spec["is_gold"]
            point_val = spec["tick_sz"]

            if ecosystem_mode and current_time is not None:
                from ..utils.time_utils import is_in_ny_session
                s_start = getattr(self.cfg.trading, "xau_session_start", "10:00")
                s_end = getattr(self.cfg.trading, "xau_session_end", "11:00")
                s_tz = getattr(self.cfg.trading, "xau_session_timezone", "America/New_York")
                h_utc = current_time.hour if hasattr(current_time, "hour") else 0
                m_utc = current_time.minute if hasattr(current_time, "minute") else 0

                if getattr(self.cfg.trading, "xau_strict_killzones", True) and is_gold:
                    in_ny_core = (13 < h_utc < 16) or (h_utc == 13 and m_utc >= 30) or (h_utc == 16 and m_utc <= 30)
                    cutoff_h = getattr(self.cfg.trading, "xau_session_cutoff_hour", 24)
                    if cutoff_h < 24 and h_utc >= cutoff_h:
                        in_ny_core = False
                elif is_index:
                    in_ny_core = (13 < h_utc < 20) or (h_utc == 13 and m_utc >= 30)
                else:
                    in_ny_core = is_in_ny_session(current_time, s_start, s_end, s_tz)

                h1_b = hierarchy_result.get("h1_bias", Bias.NEUTRAL)
                h1_dir = TradeDirection.BUY if h1_b == Bias.BULLISH else (TradeDirection.SELL if h1_b == Bias.BEARISH else None)

                # Dynamic Volatility-Regime: adapt target_r, be_trigger, displacement
                vr = getattr(self, '_current_regime', None)
                _vr_target_r = vr.target_r if vr else (self.cfg.trading.get_target_r(self.symbol) if hasattr(self.cfg.trading, 'get_target_r') else getattr(self.cfg.trading, 'xau_target_r', 2.0))
                _vr_min_atr_mult_ny = vr.min_atr_mult if vr else getattr(self.cfg.trading, 'xau_displacement_atr_mult', 0.60)
                _vr_min_body_ny = vr.min_body_ratio if vr else getattr(self.cfg.trading, 'xau_displacement_body_ratio', 0.60)
                # London gets a slightly tighter base, regime further adjusts on top
                _base_lon_atr = getattr(self.cfg.trading, 'xau_london_displacement_atr_mult', 0.75)
                _base_lon_body = getattr(self.cfg.trading, 'xau_london_displacement_body_ratio', 0.65)
                _vr_min_atr_mult_lon = max(_base_lon_atr, _vr_min_atr_mult_ny) if vr else _base_lon_atr
                _vr_min_body_lon = max(_base_lon_body, _vr_min_body_ny) if vr else _base_lon_body

                # Tier 1: Flagship NY Core (10:00 - 11:00 AM NY)
                if in_ny_core:
                    nas_trend_bias = h1_dir if (is_index and getattr(self.cfg.trading, "nas_require_h1_trend", True)) else None
                    seq = self.trigger.detect_xau_scalp_sequence(
                        m15_data=m15_data,
                        m1_data=m1_data,
                        m1_atr=m1_atr,
                        lookback_m15=getattr(self.cfg.trading, "xau_swing_lookback_m15", 20),
                        sequence_window_m1=getattr(self.cfg.trading, "xau_sequence_window_m1", 10),
                        min_atr_mult=_vr_min_atr_mult_ny,
                        min_body_ratio=_vr_min_body_ny,
                        mss_lookback=getattr(self.cfg.trading, "xau_mss_lookback_m1", 5),
                        target_r=_vr_target_r,
                        point_value=point_val,
                        stops_level_points=getattr(self.cfg.trading, "deviation_points", 10),
                        telemetry=self._ablation_counters,
                        liquidity_source="m15_swings",
                        current_time=current_time,
                        trend_bias=nas_trend_bias,
                        enable_delta_absorption=getattr(self.cfg.trading, "enable_delta_absorption", True),
                        delta_absorption_mode=getattr(self.cfg.trading, "delta_absorption_mode", "soft"),
                        enable_hvn_tp_calibration=getattr(self.cfg.trading, "enable_hvn_tp_calibration", True),
                        min_sl_distance=self.cfg.trading.get_min_sl_distance(self.symbol, current_price=price, m1_atr=m1_atr) if hasattr(self.cfg.trading, "get_min_sl_distance") else 0.0,
                    )
                # Tier 2: London Cash Open Killzone (07:45 - 10:30 UTC) with m15 swing sweeps
                elif is_gold and getattr(self.cfg.trading, "xau_enable_london_asian_sweep", True) and (self.cfg.trading.is_in_xau_london_killzone(current_time) if hasattr(self.cfg.trading, "is_in_xau_london_killzone") else ((h_utc == 7 and m_utc >= 45) or (8 <= h_utc < 10) or (h_utc == 10 and m_utc <= 30))):
                    req_h1 = getattr(self.cfg.trading, "xau_london_require_h1_trend", True) or getattr(self, "_test_full_london_trend", False)
                    early_london = (h_utc == 7 and m_utc >= 45) or (h_utc == 8 and m_utc <= 30)
                    lon_trend_bias = h1_dir if (early_london or req_h1) else None
                    seq = self.trigger.detect_xau_scalp_sequence(
                        m15_data=m15_data,
                        m1_data=m1_data,
                        m1_atr=m1_atr,
                        lookback_m15=getattr(self.cfg.trading, "xau_swing_lookback_m15", 20),
                        sequence_window_m1=getattr(self.cfg.trading, "xau_sequence_window_m1", 10),
                        min_atr_mult=_vr_min_atr_mult_lon,
                        min_body_ratio=_vr_min_body_lon,
                        mss_lookback=getattr(self.cfg.trading, "xau_mss_lookback_m1", 5),
                        target_r=_vr_target_r,
                        point_value=point_val,
                        stops_level_points=getattr(self.cfg.trading, "deviation_points", 10),
                        telemetry=self._ablation_counters,
                        liquidity_source="m15_swings",
                        current_time=current_time,
                        trend_bias=lon_trend_bias,
                        enable_delta_absorption=getattr(self.cfg.trading, "enable_delta_absorption", True),
                        delta_absorption_mode=getattr(self.cfg.trading, "delta_absorption_mode", "soft"),
                        enable_hvn_tp_calibration=getattr(self.cfg.trading, "enable_hvn_tp_calibration", True),
                        min_sl_distance=self.cfg.trading.get_min_sl_distance(self.symbol, current_price=price, m1_atr=m1_atr) if hasattr(self.cfg.trading, "get_min_sl_distance") else 0.0,
                    )
                # Tier 3: London/NY Overlap Pullback (disabled by default in high-quality killzone ecosystem)
                elif getattr(self.cfg.trading, "xau_enable_overlap_pullback", False) and (13 <= h_utc < 16) and not hierarchy_result.get("is_sideways"):
                    if h1_dir is not None:
                        seq = self.trigger.detect_overlap_pullback_setup(
                            m15_data=m15_data,
                            m1_data=m1_data,
                            m1_atr=m1_atr,
                            trend_direction=h1_dir,
                            target_r=self.cfg.trading.get_target_r(self.symbol) if hasattr(self.cfg.trading, "get_target_r") else getattr(self.cfg.trading, "xau_target_r", 2.0),
                            point_value=point_val,
                            stops_level_points=getattr(self.cfg.trading, "deviation_points", 10),
                            telemetry=self._ablation_counters,
                            min_sl_distance=self.cfg.trading.get_min_sl_distance(self.symbol) if hasattr(self.cfg.trading, "get_min_sl_distance") else 0.0,
                        )
            else:
                # Standard single-window mode
                if getattr(self.cfg.trading, "enable_session_filter", False) or getattr(self.cfg.trading, "xau_session_start", None):
                    from ..utils.time_utils import is_in_ny_session
                    s_start = getattr(self.cfg.trading, "xau_session_start", "10:00")
                    s_end = getattr(self.cfg.trading, "xau_session_end", "11:00")
                    s_tz = getattr(self.cfg.trading, "xau_session_timezone", "America/New_York")
                    if current_time is not None and not is_in_ny_session(current_time, s_start, s_end, s_tz):
                        return None

                seq = self.trigger.detect_xau_scalp_sequence(
                    m15_data=m15_data,
                    m1_data=m1_data,
                    m1_atr=m1_atr,
                    lookback_m15=getattr(self.cfg.trading, "xau_swing_lookback_m15", 20),
                    sequence_window_m1=getattr(self.cfg.trading, "xau_sequence_window_m1", 10),
                    min_atr_mult=getattr(self.cfg.trading, "xau_displacement_atr_mult", 0.60),
                    min_body_ratio=getattr(self.cfg.trading, "xau_displacement_body_ratio", 0.60),
                    mss_lookback=getattr(self.cfg.trading, "xau_mss_lookback_m1", 5),
                    target_r=self.cfg.trading.get_target_r(self.symbol) if hasattr(self.cfg.trading, "get_target_r") else getattr(self.cfg.trading, "xau_target_r", 2.0),
                    point_value=point_val,
                    stops_level_points=getattr(self.cfg.trading, "deviation_points", 10),
                    telemetry=self._ablation_counters,
                    liquidity_source=getattr(self.cfg.trading, "xau_liquidity_source", "m15_swings"),
                    current_time=current_time,
                    enable_delta_absorption=getattr(self.cfg.trading, "enable_delta_absorption", True),
                    delta_absorption_mode=getattr(self.cfg.trading, "delta_absorption_mode", "soft"),
                    enable_hvn_tp_calibration=getattr(self.cfg.trading, "enable_hvn_tp_calibration", True),
                    min_sl_distance=self.cfg.trading.get_min_sl_distance(self.symbol) if hasattr(self.cfg.trading, "get_min_sl_distance") else 0.0,
                )

            if not seq:
                return None

            direction = seq["direction"]
            entry_price = seq["entry_price"]
            sl = seq["sl_price"]
            tp = seq["tp_price"]
            entry_tf = "M1"
            atr_val = m1_atr
            setup_type = seq.get("setup_type", "SWEEP_FVG")


        else:
            if hierarchy_result.get("is_sideways"):
                return None
            allowed = hierarchy_result.get("allowed_direction")
            if allowed is None:
                return None
            direction = TradeDirection.BUY if allowed == "bullish" else TradeDirection.SELL
            entry_tf = hierarchy_result.get("entry_tier", "M15")
            entry_data = data_all.get(entry_tf) or data_all.get("M15")
            if not entry_data:
                return None
            atr_val = atr(entry_data.high, entry_data.low, entry_data.close, 14) or 0

            if trigger_type == "top_bottom_hunter":
                # Optional trend filter
                if getattr(self.cfg.trading, "tbh_use_trend_filter", False):
                    from ..indicators.moving_averages import sma
                    sma_len = getattr(self.cfg.trading, "tbh_trend_sma_len", 200)
                    trend_ma = sma(entry_data.close, sma_len)
                    if trend_ma is not None:
                        if direction == TradeDirection.BUY and price < trend_ma:
                            return None
                        if direction == TradeDirection.SELL and price > trend_ma:
                            return None

                tbh_ok, _ = self.trigger.check_top_bottom_hunter(
                    entry_data,
                    direction,
                    lookback=getattr(self.cfg.trading, "tbh_lookback", 2),
                    fib_0=getattr(self.cfg.trading, "tbh_fib_0", 0.382),
                    fib_1=getattr(self.cfg.trading, "tbh_fib_1", 0.618),
                    rsi_oversold=getattr(self.cfg.trading, "tbh_rsi_oversold", 30.0),
                    rsi_overbought=getattr(self.cfg.trading, "tbh_rsi_overbought", 70.0),
                )
                if not tbh_ok:
                    return None
                sl_dist = (atr_val or 1.0) * getattr(self.cfg.trading, "tbh_atr_sl_mult", 2.0)
                sl = price - sl_dist if direction == TradeDirection.BUY else price + sl_dist
                tp_dist = sl_dist * getattr(self.cfg.trading, "tbh_rr_ratio", 1.5)
                tp = price + tp_dist if direction == TradeDirection.BUY else price - tp_dist
            elif trigger_type == "hybrid":
                momentum_ok, _ = self.trigger.check_momentum_continuation(entry_data, direction)
                tbh_ok, _ = self.trigger.check_top_bottom_hunter(
                    entry_data,
                    direction,
                    lookback=getattr(self.cfg.trading, "tbh_lookback", 2),
                    fib_0=getattr(self.cfg.trading, "tbh_fib_0", 0.382),
                    fib_1=getattr(self.cfg.trading, "tbh_fib_1", 0.618),
                    rsi_oversold=getattr(self.cfg.trading, "tbh_rsi_oversold", 30.0),
                    rsi_overbought=getattr(self.cfg.trading, "tbh_rsi_overbought", 70.0),
                )
                if not (momentum_ok and tbh_ok):
                    return None
                sl = self.exit_mgr.calc_atr_sl(entry_data, direction, entry_tf)
                tp = self.exit_mgr.calc_structure_tp(entry_data, direction, price, atr_val)
            else:
                momentum_ok, _ = self.trigger.check_momentum_continuation(entry_data, direction)
                if not momentum_ok:
                    return None
                sl = self.exit_mgr.calc_atr_sl(entry_data, direction, entry_tf)
                tp = self.exit_mgr.calc_structure_tp(entry_data, direction, price, atr_val)

        zone = hierarchy_result.get("m15_zone")
        in_zone = self.zone.price_in_zone(price, zone) if zone else False

        is_fvg = trigger_type in ("xau_liquidity_sweep_fvg_m1", "liquidity_sweep_fvg")
        grade = SignalGrade.B
        if is_fvg:
            if is_index:
                # Tiered Conviction Grading for Nasdaq:
                # Grade A+ (Unicorn Index Setup: 2.40x) vs Grade A (Normal: 1.00x)
                h1_b = hierarchy_result.get("h1_bias", Bias.NEUTRAL)
                h1_val = h1_b.value if isinstance(h1_b, Bias) else str(h1_b)
                h_utc = current_time.hour if current_time is not None else 0
                in_prime_nas = (h_utc == 14) or (16 <= h_utc <= 19)
                trend_ok = (h1_val == "bullish" and direction == TradeDirection.BUY) or (h1_val == "bearish" and direction == TradeDirection.SELL)
                sl_dist_ok = (abs(entry_price - sl) >= getattr(self.cfg.trading, "nas_min_sl_distance", 10.0))
                if in_prime_nas and trend_ok and sl_dist_ok:
                    grade = SignalGrade.A_PLUS
                else:
                    grade = SignalGrade.A
            else:
                # Tiered Conviction Grading for Gold: Grade A+ (Unicorn: 2.60x) vs Grade A (Normal: 1.00x)
                h1_b = hierarchy_result.get("h1_bias", Bias.NEUTRAL)
                h1_val = h1_b.value if isinstance(h1_b, Bias) else str(h1_b)
                h_utc = current_time.hour if current_time is not None else 0

                in_ny_core_window = (13 <= h_utc <= 15) if getattr(self.cfg.trading, "xau_a_plus_ny_core_only", True) else True
                not_bullish_trap = (h1_val != "bullish") if getattr(self.cfg.trading, "xau_a_plus_block_h1_bullish", True) else True
                sl_dist_ok = (abs(entry_price - sl) >= getattr(self.cfg.trading, "xau_a_plus_min_sl_dist", 0.0))

                if in_ny_core_window and not_bullish_trap and sl_dist_ok:
                    grade = SignalGrade.A_PLUS
                else:
                    grade = SignalGrade.A

        signal = Signal(
            # BUG-12 FIX: use self.symbol (engine instance symbol) not cfg.trading.symbol (global default)
            symbol=self.symbol,
            direction=direction,
            grade=grade,
            entry_tf=entry_tf,
            h4_bias=hierarchy_result.get("h4_bias", Bias.NEUTRAL),
            h1_bias=hierarchy_result.get("h1_bias", Bias.NEUTRAL),
            m15_bias=hierarchy_result.get("m15_bias", Bias.NEUTRAL),
            m5_bias=hierarchy_result.get("m5_bias", Bias.NEUTRAL),
            regime=hierarchy_result.get("regime", Regime.RANGING),
            entry_price=entry_price if is_fvg else price,
            sl_price=sl,
            tp_price=tp,
            atr_value=atr_val,
            zone_high=zone[1] if zone else 0,
            zone_low=zone[0] if zone else 0,
            score=hierarchy_result.get("alignment_score", 0),
            setup_type=setup_type if is_fvg else "LEGACY",
        )
        if is_fvg and seq:
            signal.fvg_low = seq.get("fvg_low", 0.0)
            signal.fvg_high = seq.get("fvg_high", 0.0)
        if not is_fvg:
            signal.grade = self.scorer.grade(signal)


        # Dedicated XAUUSD Session Cutoff: block new setups at or after cutoff hour (e.g. 13:00 UTC)
        # BUG-03 FIX: was referencing undefined 'sym_check'; use self.symbol instead.
        cutoff_h = getattr(self.cfg.trading, "xau_session_cutoff_hour", 24)
        _sym_check = self.symbol
        if cutoff_h < 24 and ("XAU" in _sym_check.upper() or "GOLD" in _sym_check.upper() or price >= 100.0) and current_time is not None:
            if current_time.hour >= cutoff_h:
                return None

        return signal

    def _execute_backtest_order(self, signal: Signal, account: AccountInfo,
                                data_all: dict, idx: int, price: float,
                                current_time: Optional[datetime] = None) -> Optional[PyraCluster]:
        # BUG-04 FIX: current_time is now an explicit parameter instead of relying on loop-scope closure
        remaining = self.daily_loss.remaining_budget_amount()
        sym = signal.symbol
        spec = get_asset_spec(sym, price)
        contract_sz = spec["contract_sz"]
        tick_sz = spec["tick_sz"]
        point_val = spec["point_val"]

        risk_scale = 1.0
        if getattr(self.cfg.trading, "enable_net_beta_gate", True):
            has_same_usd = any(
                c.status == TradeStatus.OPEN and getattr(c, "symbol", "") != sym and c.direction == signal.direction
                for c in self._clusters
            )
            if has_same_usd:
                risk_scale = getattr(self.cfg.trading, "correlated_usd_risk_scale", 0.60)

        if getattr(self.cfg.trading, "enable_conviction_sizing", True) and hasattr(self.cfg.trading, "get_conviction_scale"):
            risk_scale *= self.cfg.trading.get_conviction_scale(signal)

        if current_time is not None and current_time.weekday() == 1 and getattr(self.cfg.trading, "tuesday_reduced_risk", True):
            tue_scale = getattr(self.cfg.trading, "tuesday_risk_scale", 0.43)
            risk_scale *= tue_scale
        if current_time is not None and current_time.weekday() == 4 and "XAU" in self.symbol.upper():
            fri_scale = getattr(self.cfg.trading, "xau_friday_risk_scale", 0.50)
            risk_scale *= fri_scale

        lot = self.sizer.calculate_lot_size(
            account=account, entry_price=price, sl_price=signal.sl_price,
            direction=signal.direction, point_value=point_val, contract_size=contract_sz,
            tick_size=tick_sz,
            remaining_budget=remaining,
            risk_scale=risk_scale,
        )
        if lot <= 0:
            return None
        signal.lot_size = lot
        cluster = PyraCluster(
            signal_id=signal.id, direction=signal.direction, entry_tf=signal.entry_tf,
            symbol=signal.symbol,
            collective_sl=signal.sl_price, open_time=signal.timestamp, status=TradeStatus.OPEN,
        )
        leg = TradeLeg(
            direction=signal.direction, entry_price=price, lot_size=lot,
            symbol=signal.symbol,
            sl_price=signal.sl_price, tp_price=signal.tp_price,
            open_time=signal.timestamp, status=TradeStatus.OPEN,
        )
        cluster.legs.append(leg)
        self.daily_loss.register_trade()
        return cluster

    def _manage_backtest_exits(self, cluster: PyraCluster, data_all: dict,
                                idx: int, price: float) -> List[dict]:
        actions = []
        m1_d = data_all.get("M1")
        bar_time = m1_d.time[-1] if (m1_d and m1_d.time) else None
        if cluster.direction == TradeDirection.BUY:
            cluster.highest_price = max(cluster.highest_price, price)
        else:
            if cluster.lowest_price <= 0.0:
                cluster.lowest_price = price
            else:
                cluster.lowest_price = min(cluster.lowest_price, price)

        # 0. Friday Weekend Guard: Auto-Flat Liquidation at Friday EOD (20:45 UTC cutoff)
        if getattr(self.cfg.trading, "friday_weekend_guard", True) and bar_time and cluster.status == TradeStatus.OPEN:
            from ..filters.session_filter import is_friday_weekend_close
            fw_h = getattr(self.cfg.trading, "friday_close_cutoff_hour", 20)
            fw_m = getattr(self.cfg.trading, "friday_close_cutoff_min", 45)
            if is_friday_weekend_close(bar_time, fw_h, fw_m):
                for leg in cluster.legs:
                    if leg.status == TradeStatus.OPEN:
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = price
                        leg.exit_reason = ExitReason.WEEKEND_CLOSE
                        actions.append({"action": "weekend_close", "price": price, "reason": "Friday EOD Weekend Guard"})
                cluster.status = TradeStatus.CLOSED
                self._last_exit_time = bar_time
                return actions

        # 1. Dynamic Breakeven Ratchet (regime-adaptive trigger)
        if getattr(self.cfg.trading, "xau_breakeven_ratchet_enabled", True) and not cluster.breakeven_activated:
            sym = getattr(cluster, "symbol", self.symbol)
            # Use regime-adapted BE trigger if available (COMPRESSED: 0.8R, NEUTRAL: 1.2R, TRENDING: 1.5R)
            vr = getattr(self, '_current_regime', None)
            if vr and "XAU" in sym.upper():
                be_trig = vr.be_trigger_r
                be_buf = vr.be_buffer_r
            elif hasattr(self.cfg.trading, "get_breakeven_trigger_r"):
                be_trig = self.cfg.trading.get_breakeven_trigger_r(sym)
                be_buf = self.cfg.trading.get_breakeven_buffer_r(sym) if hasattr(self.cfg.trading, "get_breakeven_buffer_r") else 0.10
            else:
                be_trig = getattr(self.cfg.trading, "xau_breakeven_trigger_r", 1.50)
                be_buf = getattr(self.cfg.trading, "xau_breakeven_buffer_r", 0.10)

            # Tuesday Breakeven Cushioning: prevent premature wick-outs in compression
            if bar_time is not None and hasattr(bar_time, "weekday") and bar_time.weekday() == 1:
                tue_be = getattr(self.cfg.trading, "tuesday_breakeven_trigger_r", 1.40)
                be_trig = max(be_trig, tue_be)

            new_be = self.exit_mgr.check_breakeven_ratchet(cluster, price, trigger_r=be_trig, buffer_r=be_buf)
            if new_be is not None:
                cluster.collective_sl = new_be
                cluster.breakeven_activated = True
                for leg in cluster.legs:
                    if leg.status == TradeStatus.OPEN:
                        leg.sl_price = new_be
                actions.append({"action": "breakeven_ratchet", "sl": new_be, "cluster": cluster.cluster_id})

        # 2. Structural Damage / Opposite MSS Early Exit
        if getattr(self.cfg.trading, "xau_early_invalidation_exit", False) and cluster.status == TradeStatus.OPEN:
            m1_slice = data_all.get("M1")
            if m1_slice and len(m1_slice.close) >= 7:
                m1_atr = atr(m1_slice.high, m1_slice.low, m1_slice.close, 14) or 1.0
                inv_ok, inv_reason = self.exit_mgr.check_structural_invalidation(cluster, m1_slice, m1_atr)
                if inv_ok:
                    for leg in cluster.legs:
                        if leg.status == TradeStatus.OPEN:
                            leg.status = TradeStatus.CLOSED
                            leg.exit_price = price
                            leg.exit_reason = ExitReason.STRUCTURAL_INVALIDATION
                            actions.append({"action": "structural_invalidation", "price": price, "reason": inv_reason})
                    cluster.status = TradeStatus.CLOSED
                    m1_d = data_all.get("M1")
                    self._last_exit_time = m1_d.time[-1] if (m1_d and m1_d.time) else (cluster.legs[0].open_time if cluster.legs else None)
                    return actions

        # 3. Partial TP check (guarded by xau_partial_close_enabled)
        if getattr(self.cfg.trading, "xau_partial_close_enabled", False) and self.partial_close.check_partial_tp(cluster, price):
            new_closed_legs = []
            close_pct = (getattr(self.partial_close, "close_pct", getattr(self.cfg.trading, "partial_tp_tranche1_pct", 25.0))) / 100.0
            for leg in cluster.legs:
                if leg.status == TradeStatus.OPEN:
                    part_lot = round(leg.lot_size * close_pct, 2)
                    if part_lot > 0 and (leg.lot_size - part_lot) >= 0.01:
                        closed_part = TradeLeg(
                            direction=leg.direction,
                            entry_price=leg.entry_price,
                            lot_size=part_lot,
                            symbol=getattr(leg, "symbol", self.symbol),
                            sl_price=leg.sl_price,
                            tp_price=price,
                            open_time=leg.open_time,
                            status=TradeStatus.CLOSED,
                            exit_price=price,
                            exit_reason="partial_tp",
                        )
                        new_closed_legs.append(closed_part)
                        leg.lot_size = round(leg.lot_size - part_lot, 2)
            cluster.legs.extend(new_closed_legs)
            cluster.breakeven_activated = True
            cluster.collective_sl = cluster.avg_entry_price()
            actions.append({"action": "partial_tp", "price": price, "cluster": cluster.cluster_id})

        # 4. Stagnation Exit
        cluster_bars = getattr(cluster, "_bars_open", 0) + 1
        cluster._bars_open = cluster_bars
        if getattr(self.cfg.trading, "xau_stagnation_exit_enabled", False) and cluster.status == TradeStatus.OPEN:
            spec_stag = get_asset_spec(getattr(cluster, "symbol", self.symbol))
            if spec_stag["is_index"]:
                max_stag_bars = getattr(self.cfg.trading, "nas_stagnation_bars", 25)
            else:
                max_stag_bars = getattr(self.cfg.trading, "xau_stagnation_bars", 15)
            min_stag_r = getattr(self.cfg.trading, "xau_stagnation_min_r", 0.40)
            if self.exit_mgr.check_stagnation_exit(cluster, price, cluster_bars, max_bars=max_stag_bars, min_r=min_stag_r):
                for leg in cluster.legs:
                    if leg.status == TradeStatus.OPEN:
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = price
                        leg.exit_reason = ExitReason.STAGNATION
                        actions.append({"action": "stagnation_exit", "price": price})
                cluster.status = TradeStatus.CLOSED
                m1_d = data_all.get("M1")
                self._last_exit_time = m1_d.time[-1] if (m1_d and m1_d.time) else (cluster.legs[0].open_time if cluster.legs else None)
                return actions

        # 5. Standard SL / TP check & Split-Tranche Runner
        m1_slice = data_all.get("M1")
        m1_atr = atr(m1_slice.high, m1_slice.low, m1_slice.close, 14) or 1.5 if (m1_slice and len(m1_slice.close) >= 14) else 1.5
        bar_low = m1_slice.low[-1] if m1_slice and len(m1_slice.low) > 0 else price
        bar_high = m1_slice.high[-1] if m1_slice and len(m1_slice.high) > 0 else price
        enable_runner = getattr(self.cfg.trading, "enable_split_tranche_runner", True)
        trail_mult = getattr(self.cfg.trading, "runner_trail_atr_mult", 2.0)

        for leg in list(cluster.legs):
            if leg.status != TradeStatus.OPEN:
                continue

            # Trailing stop check for moonbag runner
            if getattr(leg, "_is_runner", False):
                if leg.direction == TradeDirection.BUY:
                    trail = cluster.highest_price - (trail_mult * m1_atr)
                    if trail > leg.sl_price:
                        leg.sl_price = trail
                    if bar_low <= leg.sl_price:
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = leg.sl_price
                        leg.exit_reason = ExitReason.CHANDELIER_TRAIL
                        actions.append({"action": "runner_trail_exit", "price": leg.exit_price})
                        continue
                else:
                    trail = cluster.lowest_price + (trail_mult * m1_atr)
                    if trail < leg.sl_price:
                        leg.sl_price = trail
                    if bar_high >= leg.sl_price:
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = leg.sl_price
                        leg.exit_reason = ExitReason.CHANDELIER_TRAIL
                        actions.append({"action": "runner_trail_exit", "price": leg.exit_price})
                        continue

            if leg.direction == TradeDirection.BUY:
                sl_hit = bar_low <= leg.sl_price
                tp_hit = bar_high >= leg.tp_price
                if sl_hit and tp_hit:
                    # Intrabar collision: conservative assumption (SL hit first)
                    leg.status = TradeStatus.CLOSED
                    leg.exit_price = leg.sl_price
                    leg.exit_reason = ExitReason.STOP_LOSS
                    self._last_sl_direction = leg.direction
                    self._last_sl_time = bar_time
                    actions.append({"action": "sl_hit", "price": leg.sl_price})
                elif sl_hit:
                    leg.status = TradeStatus.CLOSED
                    leg.exit_price = leg.sl_price
                    leg.exit_reason = ExitReason.STOP_LOSS
                    self._last_sl_direction = leg.direction
                    self._last_sl_time = bar_time
                    actions.append({"action": "sl_hit", "price": leg.sl_price})
                elif tp_hit:
                    if enable_runner and not getattr(leg, "_partial_banked", False) and leg.lot_size >= 0.02:
                        leg._partial_banked = True
                        t1_pct = getattr(self.cfg.trading, "partial_tp_tranche1_pct", 25.0)
                        t2_pct = getattr(self.cfg.trading, "partial_tp_tranche2_pct", 35.0)
                        rem_pct = max(1.0, 100.0 - t1_pct)
                        bank_frac = t2_pct / rem_pct
                        bank_lot = round(leg.lot_size * bank_frac, 2)
                        bank_lot = max(0.01, min(bank_lot, round(leg.lot_size - 0.01, 2)))
                        runner_lot = round(leg.lot_size - bank_lot, 2)
                        leg.lot_size = bank_lot
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = leg.tp_price
                        leg.exit_reason = ExitReason.TAKE_PROFIT
                        actions.append({"action": "banker_tp_hit", "price": leg.tp_price})

                        # Spawn Moonbag Runner Leg with SL trailed to Breakeven
                        # BUG-02 FIX: use asset-appropriate SL buffer (5pts for NAS100, $0.20 for Gold)
                        _runner_spec = get_asset_spec(getattr(leg, "symbol", self.symbol), leg.entry_price)
                        _runner_sl_buf = self.cfg.trading.get_min_sl_distance(
                            getattr(leg, "symbol", self.symbol), leg.entry_price
                        ) if hasattr(self.cfg.trading, "get_min_sl_distance") else (0.20 if "XAU" in self.symbol else 5.0)
                        runner_sl = leg.entry_price + _runner_sl_buf
                        runner_leg = TradeLeg(
                            direction=leg.direction, entry_price=leg.entry_price, lot_size=runner_lot,
                            symbol=leg.symbol, sl_price=runner_sl, tp_price=999999.0,
                            open_time=leg.open_time, status=TradeStatus.OPEN,
                        )
                        runner_leg._is_runner = True
                        cluster.legs.append(runner_leg)
                        cluster.breakeven_activated = True
                    else:
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = leg.tp_price
                        leg.exit_reason = ExitReason.TAKE_PROFIT
                        actions.append({"action": "tp_hit", "price": leg.tp_price})
            else:
                sl_hit = bar_high >= leg.sl_price
                # BUG-14 FIX: tp_price == -1.0 means trailing-only runner (no fixed TP); never trigger TP check
                tp_hit = leg.tp_price > 0 and bar_low <= leg.tp_price
                if sl_hit and tp_hit:
                    # Intrabar collision: conservative assumption (SL hit first)
                    leg.status = TradeStatus.CLOSED
                    leg.exit_price = leg.sl_price
                    leg.exit_reason = ExitReason.STOP_LOSS
                    self._last_sl_direction = leg.direction
                    self._last_sl_time = bar_time
                    actions.append({"action": "sl_hit", "price": leg.sl_price})
                elif sl_hit:
                    leg.status = TradeStatus.CLOSED
                    leg.exit_price = leg.sl_price
                    leg.exit_reason = ExitReason.STOP_LOSS
                    self._last_sl_direction = leg.direction
                    self._last_sl_time = bar_time
                    actions.append({"action": "sl_hit", "price": leg.sl_price})
                elif tp_hit:
                    if enable_runner and not getattr(leg, "_partial_banked", False) and leg.lot_size >= 0.02:
                        leg._partial_banked = True
                        t1_pct = getattr(self.cfg.trading, "partial_tp_tranche1_pct", 25.0)
                        t2_pct = getattr(self.cfg.trading, "partial_tp_tranche2_pct", 35.0)
                        rem_pct = max(1.0, 100.0 - t1_pct)
                        bank_frac = t2_pct / rem_pct
                        bank_lot = round(leg.lot_size * bank_frac, 2)
                        bank_lot = max(0.01, min(bank_lot, round(leg.lot_size - 0.01, 2)))
                        runner_lot = round(leg.lot_size - bank_lot, 2)
                        leg.lot_size = bank_lot
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = leg.tp_price
                        leg.exit_reason = ExitReason.TAKE_PROFIT
                        actions.append({"action": "banker_tp_hit", "price": leg.tp_price})

                        # Spawn Moonbag Runner Leg with SL trailed to Breakeven
                        # BUG-02 FIX: asset-appropriate SL buffer for SELL runner
                        # BUG-14 FIX: SELL runner TP was 0.0 which can never trigger; use -1.0 sentinel (disabled)
                        _runner_spec_s = get_asset_spec(getattr(leg, "symbol", self.symbol), leg.entry_price)
                        _runner_sl_buf_s = self.cfg.trading.get_min_sl_distance(
                            getattr(leg, "symbol", self.symbol), leg.entry_price
                        ) if hasattr(self.cfg.trading, "get_min_sl_distance") else (0.20 if "XAU" in self.symbol else 5.0)
                        runner_sl = leg.entry_price - _runner_sl_buf_s
                        runner_leg = TradeLeg(
                            direction=leg.direction, entry_price=leg.entry_price, lot_size=runner_lot,
                            symbol=leg.symbol, sl_price=runner_sl, tp_price=-1.0,  # -1.0 = trailing-only, no fixed TP
                            open_time=leg.open_time, status=TradeStatus.OPEN,
                        )
                        runner_leg._is_runner = True
                        cluster.legs.append(runner_leg)
                        cluster.breakeven_activated = True
                    else:
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = leg.tp_price
                        leg.exit_reason = ExitReason.TAKE_PROFIT
                        actions.append({"action": "tp_hit", "price": leg.tp_price})

        open_legs = [l for l in cluster.legs if l.status == TradeStatus.OPEN]
        if not open_legs:
            cluster.status = TradeStatus.CLOSED
            m1_d = data_all.get("M1")
            self._last_exit_time = m1_d.time[-1] if (m1_d and m1_d.time) else (cluster.legs[0].open_time if cluster.legs else None)

        # 6. Check time stop for FVG scalping strategy (runners exempt)
        is_fvg_strat = getattr(self.cfg.trading, "strategy_trigger_type", "momentum") in (
            "xau_liquidity_sweep_fvg_m1", "liquidity_sweep_fvg"
        )
        if is_fvg_strat and cluster.status == TradeStatus.OPEN:
            sym = getattr(cluster, "symbol", self.symbol)
            if hasattr(self.cfg.trading, "get_max_holding_bars"):
                max_holding = self.cfg.trading.get_max_holding_bars(sym)
            else:
                max_holding = getattr(self.cfg.trading, "xau_max_holding_bars", 60)
            if max_holding > 0 and cluster_bars >= max_holding:
                for leg in cluster.legs:
                    if leg.status == TradeStatus.OPEN and not getattr(leg, "_is_runner", False):
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = price
                        leg.exit_reason = ExitReason.TIME_BASED
                        actions.append({"action": "time_stop_hit", "price": price})
                open_legs = [l for l in cluster.legs if l.status == TradeStatus.OPEN]
                if not open_legs:
                    cluster.status = TradeStatus.CLOSED
                    m1_d = data_all.get("M1")
                    self._last_exit_time = m1_d.time[-1] if (m1_d and m1_d.time) else (cluster.legs[0].open_time if cluster.legs else None)
        return actions

    def _close_all(self, price: float):
        for cluster in self._clusters:
            if cluster.status == TradeStatus.OPEN:
                for leg in cluster.legs:
                    if leg.status == TradeStatus.OPEN:
                        leg.status = TradeStatus.CLOSED
                        leg.exit_price = price
                        leg.exit_reason = ExitReason.EQUITY_KILL
                cluster.status = TradeStatus.CLOSED

    def _compute_equity(self, balance: float, current_price: float, idx: int) -> float:
        unrealized = 0.0
        for cluster in self._clusters:
            if cluster.status == TradeStatus.OPEN:
                sym = getattr(cluster, "symbol", "XAUUSD")
                spec = get_asset_spec(sym, current_price)
                contract_sz = int(spec["contract_sz"])
                tick_sz = spec["tick_sz"]
                point_val = spec["point_val"]
                unrealized += cluster.unrealized_pnl(current_price, point_val, contract_sz, tick_size=tick_sz)
        return balance + unrealized

    def _report(self) -> dict:
        total_trades = 0
        wins = 0
        losses = 0
        total_pnl = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        pnl_list: List[float] = []

        for cluster in self._clusters:
            for leg in cluster.legs:
                if leg.status == TradeStatus.CLOSED and leg.exit_price:
                    total_trades += 1
                    # BUG-01 FIX: reuse leg.pnl already calculated (with commission) in the main loop.
                    # _balance_credited is set True only when pnl was computed AND credited in the loop.
                    # leg.pnl defaults to 0.0 so we can't use None-check — use the explicit flag instead.
                    if getattr(leg, "_balance_credited", False):
                        pnl = leg.pnl
                    else:
                        # Fallback for legs closed by kill-switch / weekend guard (bypassed the main credit loop)
                        sym = getattr(leg, "symbol", "XAUUSD")
                        spec = get_asset_spec(sym, leg.entry_price or leg.exit_price)
                        c_sz = spec["contract_sz"]
                        diff = (leg.exit_price - leg.entry_price) if leg.direction == TradeDirection.BUY else (leg.entry_price - leg.exit_price)
                        raw_pnl = diff * leg.lot_size * c_sz
                        friction_on = getattr(self.cfg.trading, "backtest_apply_friction", True)
                        comm_rate = self.cfg.trading.get_commission_per_lot(getattr(leg, "symbol", "XAUUSD")) if (friction_on and hasattr(self.cfg.trading, "get_commission_per_lot")) else (getattr(self.cfg.trading, "backtest_commission_per_lot", 6.0) if friction_on else 0.0)
                        pnl = raw_pnl - (comm_rate * leg.lot_size)
                        leg.pnl = round(pnl, 2)
                    total_pnl += pnl

                    pnl_list.append(pnl)
                    if pnl > 0:
                        wins += 1
                        gross_profit += pnl
                    elif pnl < 0:
                        losses += 1
                        gross_loss += abs(pnl)

        max_dd = float(self.max_dd.current_dd_pct)
        init_bal = self.cfg.trading.backtest_initial_balance
        final_bal = init_bal + total_pnl
        return_pct = round((total_pnl / init_bal) * 100, 2) if init_bal else 0.0
        win_rate = round(wins / total_trades * 100, 2) if total_trades else 0.0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        # Institutional Quant Metrics (from awesome-quant / quantstats / empyrical)
        avg_win = round(gross_profit / wins, 2) if wins > 0 else 0.0
        avg_loss = round(gross_loss / losses, 2) if losses > 0 else 0.0
        payoff_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0
        expectancy = round((wins / total_trades * avg_win) - (losses / total_trades * avg_loss), 2) if total_trades > 0 else 0.0

        # Sharpe & Sortino ratios based on trade returns
        # BUG-05 FIX: use trades_per_year annualization (not a constant 252 which assumes daily returns).
        # We derive trades_per_year from the actual trade frequency over the backtest period.
        trade_returns = [p / init_bal for p in pnl_list] if init_bal else []
        sharpe_ratio = 0.0
        sortino_ratio = 0.0
        if len(trade_returns) > 1:
            mean_r = sum(trade_returns) / len(trade_returns)
            var_r = sum((r - mean_r) ** 2 for r in trade_returns) / (len(trade_returns) - 1)
            std_r = math.sqrt(var_r)
            # Annualization factor: scale by expected trades per year
            # Assumes ~252 trading days and infers avg trades/day from sample size & date range
            _first_time = next((c.open_time for c in self._clusters if c.open_time), None)
            _last_time = next((c.open_time for c in reversed(self._clusters) if c.open_time), None)
            if _first_time and _last_time and _first_time != _last_time:
                import datetime as _dt
                _days = max(1, (_last_time - _first_time).days if hasattr(_last_time - _first_time, 'days') else 1)
                _trades_per_year = total_trades / _days * 252
            else:
                _trades_per_year = max(total_trades, 1)
            _annualize = math.sqrt(max(_trades_per_year, 1))
            if std_r > 0:
                sharpe_ratio = round((mean_r / std_r) * _annualize, 2)

            downside_sq = [r ** 2 for r in trade_returns if r < 0]
            if downside_sq:
                downside_std = math.sqrt(sum(downside_sq) / len(downside_sq))
                if downside_std > 0:
                    sortino_ratio = round((mean_r / downside_std) * _annualize, 2)

        calmar_ratio = round(return_pct / max_dd, 2) if max_dd > 0 else 0.0
        max_dd_dollars = round(init_bal * (max_dd / 100.0), 2)
        recovery_factor = round(total_pnl / max_dd_dollars, 2) if max_dd_dollars > 0 else 0.0
        kelly_fraction = round(PositionSizer.calculate_kelly_fraction(
            win_rate=wins / total_trades if total_trades else 0.0,
            win_loss_ratio=payoff_ratio,
            half_kelly=True,
        ) * 100, 2)

        return {
            "initial_balance": init_bal,
            "final_balance": round(final_bal, 2),
            "total_pnl": round(total_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "return_pct": return_pct,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_pct": round(max_dd, 2),
            "clusters": len(self._clusters),
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "calmar_ratio": calmar_ratio,
            "expectancy": expectancy,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "payoff_ratio": payoff_ratio,
            "recovery_factor": recovery_factor,
            "kelly_fraction_pct": kelly_fraction,
            "ablation": dict(self._ablation_counters),
            "trade_pnls": pnl_list,
        }

    @classmethod
    def run_sweep(
        cls,
        data: Dict,
        base_config: Config,
        param_grid: List[Dict[str, Any]],
        symbol: Optional[str] = None,
        strategy_version: str = "TopBottomHunter_v1.0",
    ) -> List[Dict[str, Any]]:
        """Run parameter sweeps deterministically adhering to Appendix A result schema.

        For each configuration:
        - Deepcopies base_config and applies parameter overrides.
        - Runs the backtest engine.
        - Formats results into an immutable record.
        - Preserves failed/losing tests with status='FAILED' without hallucinating missing metrics.
        """
        results = []
        for idx, param_set in enumerate(param_grid):
            config_id = param_set.get("config_id", f"EXP-{idx + 1:05d}")
            cfg = copy.deepcopy(base_config)

            # Apply parameters to trading config
            for k, v in param_set.items():
                if hasattr(cfg.trading, k):
                    setattr(cfg.trading, k, v)
                elif hasattr(cfg.mt5, k):
                    setattr(cfg.mt5, k, v)

            if symbol:
                cfg.trading.symbol = symbol

            try:
                engine = cls(cfg)
                res = engine.run(data)
                total_trades = res.get("total_trades", 0)
                status = "COMPLETED" if total_trades > 0 else "NO_TRADES"

                record = {
                    "config_id": config_id,
                    "strategy_version": strategy_version,
                    "symbol": cfg.trading.symbol,
                    "timeframe": cfg.trading.tradingview_timeframe or "M15",
                    "parameters": dict(param_set),
                    "metrics": {
                        "total_trades": total_trades,
                        "net_profit": res.get("total_pnl", 0.0),
                        "net_profit_pct": res.get("return_pct", 0.0),
                        "max_drawdown_pct": res.get("max_drawdown_pct", 0.0),
                        "win_rate": res.get("win_rate", 0.0),
                        "profit_factor": res.get("profit_factor", 0.0),
                        "avg_trade": round(res.get("total_pnl", 0.0) / total_trades, 2) if total_trades > 0 else 0.0,
                        "sharpe_ratio": res.get("sharpe_ratio", 0.0),
                        "sortino_ratio": res.get("sortino_ratio", 0.0),
                        "calmar_ratio": res.get("calmar_ratio", 0.0),
                        "payoff_ratio": res.get("payoff_ratio", 0.0),
                        "expectancy": res.get("expectancy", 0.0),
                    },
                    "status": status,
                    "error_message": None,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as e:
                log.warning("Sweep failed for config %s: %s", config_id, e)
                record = {
                    "config_id": config_id,
                    "strategy_version": strategy_version,
                    "symbol": cfg.trading.symbol,
                    "timeframe": cfg.trading.tradingview_timeframe or "M15",
                    "parameters": dict(param_set),
                    "metrics": {
                        "total_trades": 0,
                        "net_profit": 0.0,
                        "net_profit_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                        "win_rate": 0.0,
                        "profit_factor": 0.0,
                        "avg_trade": 0.0,
                        "sharpe_ratio": 0.0,
                        "sortino_ratio": 0.0,
                        "calmar_ratio": 0.0,
                        "payoff_ratio": 0.0,
                        "expectancy": 0.0,
                    },
                    "status": "FAILED",
                    "error_message": str(e),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }
            results.append(record)
        return results

    @staticmethod
    def audit_neighborhood(
        results: List[Dict[str, Any]],
        param_keys: Optional[List[str]] = None,
        min_trades: int = 5,
    ) -> List[Dict[str, Any]]:
        """Audit parameter neighborhoods and assign robustness classifications.

        Classifies each candidate region as:
        - ROBUST: Neighbor median PF >= 1.2, worst neighbor PF >= 1.0, candidate PF >= 1.3
        - PROMISING: Candidate PF >= 1.15, median neighbor PF >= 1.05
        - FRAGILE: Candidate has high return/PF but neighbors collapse (isolated cliff/overfit)
        - REJECT: Negative return, insufficient trades, or failing metrics
        """
        import statistics

        if not results:
            return []

        # Determine keys to compare
        all_keys = set()
        for r in results:
            all_keys.update(r.get("parameters", {}).keys())
        keys_to_compare = param_keys if param_keys else sorted(list(all_keys))

        # Build sorted index map for each numeric or hashable parameter
        val_indices: Dict[str, Dict[Any, int]] = {}
        for k in keys_to_compare:
            try:
                uniq = sorted({r.get("parameters", {}).get(k) for r in results if k in r.get("parameters", {})})
            except TypeError:
                uniq = list({r.get("parameters", {}).get(k) for r in results if k in r.get("parameters", {})})
            val_indices[k] = {v: idx for idx, v in enumerate(uniq)}

        audited = []
        for i, cand in enumerate(results):
            c_metrics = cand.get("metrics", {})
            c_trades = c_metrics.get("total_trades", 0)
            c_pf = c_metrics.get("profit_factor", 0.0)
            c_pnl = c_metrics.get("net_profit", 0.0)
            c_params = cand.get("parameters", {})

            # Find immediate adjacent neighbors in the grid
            neighbors = []
            for j, other in enumerate(results):
                if i == j:
                    continue
                o_params = other.get("parameters", {})
                is_neighbor = True
                diff_steps = 0
                for k in keys_to_compare:
                    if k in c_params and k in o_params:
                        idx_c = val_indices[k].get(c_params[k], 0)
                        idx_o = val_indices[k].get(o_params[k], 0)
                        step = abs(idx_c - idx_o)
                        if step > 1:
                            is_neighbor = False
                            break
                        diff_steps += step
                    else:
                        is_neighbor = False
                        break
                # Immediate grid neighbor has exactly 1 step difference across the grid
                if is_neighbor and diff_steps == 1:
                    neighbors.append(other)

            if neighbors:
                n_pfs = [n.get("metrics", {}).get("profit_factor", 0.0) for n in neighbors]
                median_n_pf = statistics.median(n_pfs)
                worst_n_pf = min(n_pfs)
            else:
                median_n_pf = c_pf
                worst_n_pf = c_pf

            # Robustness classification
            if c_trades < min_trades or c_pnl <= 0:
                label = "REJECT"
            elif c_pf >= 1.3 and median_n_pf >= 1.2 and worst_n_pf >= 1.0:
                label = "ROBUST"
            elif c_pf >= 1.15 and median_n_pf >= 1.05:
                label = "PROMISING"
            elif c_pf >= 1.25 and (median_n_pf < 1.0 or worst_n_pf < 0.8):
                label = "FRAGILE"
            else:
                label = "REJECT"

            cand_copy = copy.deepcopy(cand)
            cand_copy["neighborhood_audit"] = {
                "median_neighbor_pf": round(median_n_pf, 2),
                "worst_neighbor_pf": round(worst_n_pf, 2),
                "neighbor_count": len(neighbors),
                "robustness_label": label,
            }
            audited.append(cand_copy)

        return audited


class TypeSliceData(TimeframeData):
    def __init__(self, src: TimeframeData, start: int, end: int):
        super().__init__(
            tf=src.tf,
            time=src.time[start:end],
            open=src.open[start:end],
            high=src.high[start:end],
            low=src.low[start:end],
            close=src.close[start:end],
            tick_volume=src.tick_volume[start:end],
            spread=src.spread[start:end],
        )
