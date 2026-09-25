import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base_engine import BaseSymbolEngine
from ..config import Config
from ..broker.mt5_connector import MT5Connector
from ..broker.account import AccountManager
from ..data.ohlcv import MultiTFData
from ..data.spread import SpreadTracker
from ..filters.spread_filter import SpreadFilter
from ..filters.news_filter import NewsFilter
from ..indicators.atr import atr
from ..models import (
    AccountInfo, Bias, ExitReason, PyraCluster, Signal, SignalGrade,
    TimeframeData, TradeDirection, TradeStatus,
)
from ..strategy.trigger import TriggerDetector
from ..strategy.volatility_regime import VolatilityRegimeEngine, RegimeState
from ..trade.trade_manager import TradeManager
from ..trade.cluster import ClusterManager
from ..state.persistence import StatePersistence
from ..utils.time_utils import broker_date, to_ny_time

log = logging.getLogger("xauusd_bot.engines.xau")


class XauusdEngine(BaseSymbolEngine):
    """Authoritative Institutional Trading Engine for Gold (XAUUSD / GOLD).

    Specialized for Gold intraday dynamics:
      - London Killzone (07:45–10:30 UTC) & NY Core (13:30–16:30 UTC)
      - El Professor Hidden Guards (London Close Wall 15:45 UTC, H4 Bias, G5/G5b SL Pauses)
      - London Profit Protection (lock daily gains after winning London trade)
      - Dynamic Volatility-Regime Adaptation (zero date/month hardcoding)
      - Minimum $5.00 SL breathing room floor
    """

    def __init__(
        self,
        symbol: str,
        config: Config,
        connector: MT5Connector,
        account: AccountManager,
        data_feed: MultiTFData,
        spread_tracker: SpreadTracker,
        spread_filter: SpreadFilter,
        news_filter: NewsFilter,
        trigger: TriggerDetector,
        trade_mgr: TradeManager,
        cluster_mgr: ClusterManager,
        persistence: StatePersistence,
    ):
        super().__init__(
            symbol=symbol,
            config=config,
            connector=connector,
            account=account,
            data_feed=data_feed,
            spread_tracker=spread_tracker,
            spread_filter=spread_filter,
            news_filter=news_filter,
            trigger=trigger,
            trade_mgr=trade_mgr,
            cluster_mgr=cluster_mgr,
            persistence=persistence,
        )
        self.london_trades_today: int = 0
        self.ny_trades_today: int = 0
        self.london_paused_today: bool = False
        self.london_won_today: bool = False
        self.h4_bullish: Optional[bool] = None
        self.h4_bearish: Optional[bool] = None
        self.vr_engine: VolatilityRegimeEngine = VolatilityRegimeEngine()
        self.vr_regime: RegimeState = RegimeState()

    @property
    def asset_name(self) -> str:
        return "Gold (XAUUSD)"

    def is_session_active(self, now_utc: datetime) -> bool:
        tc = self.cfg.trading
        h_utc = now_utc.hour
        m_utc = now_utc.minute

        # Friday filter: Skip entire day if Friday trading disabled for Gold
        if not getattr(tc, "xau_friday_trade_enabled", False) and now_utc.weekday() == 4:
            return False

        if getattr(tc, "xau_strict_killzones", True):
            lon_start_h = getattr(tc, "xau_london_start_hour", 8)
            lon_start_m = getattr(tc, "xau_london_start_minute", 0)
            in_london = (h_utc > lon_start_h or (h_utc == lon_start_h and m_utc >= lon_start_m)) and (h_utc < 10 or (h_utc == 10 and m_utc <= 30))

            ny_end_h = getattr(tc, "xau_london_close_cutoff_hour", 14)
            ny_end_m = getattr(tc, "xau_london_close_cutoff_min", 45)
            in_ny_core = (13 < h_utc < ny_end_h) or (h_utc == 13 and m_utc >= 30) or (h_utc == ny_end_h and m_utc <= ny_end_m)

            if getattr(tc, "friday_skip_ny_session", True) and now_utc.weekday() == 4:
                in_ny_core = False
            cutoff_h = getattr(tc, "xau_session_cutoff_hour", 24)
            if cutoff_h < 24 and h_utc >= cutoff_h:
                in_ny_core = False
            return in_london or in_ny_core

        return True

    def check_symbol_guards(self, now_utc: datetime, data_all: Dict[str, TimeframeData], current_price: float) -> bool:
        tc = self.cfg.trading
        h_utc = now_utc.hour
        m_utc = now_utc.minute

        # Friday trading check
        if not getattr(tc, "xau_friday_trade_enabled", False) and now_utc.weekday() == 4:
            return False

        # Tuesday trading check
        if now_utc.weekday() == 1 and not getattr(tc, "tuesday_trade_enabled", True):
            return False

        # Reset daily tracking
        today_date = now_utc.date()
        if self.last_g5_day is not None and self.last_g5_day != today_date:
            self.consec_losses = 0
            self.paused_today = False
            self.london_paused_today = False
            self.london_won_today = False
            self.london_trades_today = 0
            self.ny_trades_today = 0
        self.last_g5_day = today_date

        # Max trades per session
        lon_start_h = getattr(tc, "xau_london_start_hour", 8)
        lon_start_m = getattr(tc, "xau_london_start_minute", 0)
        in_london = (h_utc > lon_start_h or (h_utc == lon_start_h and m_utc >= lon_start_m)) and (h_utc < 10 or (h_utc == 10 and m_utc <= 30))

        ny_end_h = getattr(tc, "xau_london_close_cutoff_hour", 14)
        ny_end_m = getattr(tc, "xau_london_close_cutoff_min", 45)
        in_ny_core = (13 < h_utc < ny_end_h) or (h_utc == 13 and m_utc >= 30) or (h_utc == ny_end_h and m_utc <= ny_end_m)

        max_sess_trades = getattr(tc, "xau_max_trades_per_session", 2)
        if in_london and self.london_trades_today >= max_sess_trades:
            return False
        if in_ny_core and self.ny_trades_today >= max_sess_trades:
            return False

        # Session Cutoff Hour
        cutoff_h = getattr(tc, "xau_session_cutoff_hour", 24)
        if cutoff_h < 24 and h_utc >= cutoff_h:
            log.debug("[%s] XAU Session Cutoff: veto at %02d:%02d UTC (cutoff: %d:00 UTC)", self.symbol, h_utc, m_utc, cutoff_h)
            return False

        # Guard 1: NY Cutoff / London Close Wall — no new entries after cutoff
        if getattr(tc, "xau_london_close_guard", True):
            if h_utc > ny_end_h or (h_utc == ny_end_h and m_utc >= ny_end_m):
                log.debug("[%s] G1 NY Cutoff Wall: live veto at %02d:%02d UTC", self.symbol, h_utc, m_utc)
                return False

        # Guard 3: H4 Macro Bias Alignment
        if getattr(tc, "xau_h4_bias_guard", False):
            h4_data = data_all.get("H4")
            if h4_data and len(h4_data.close) >= getattr(tc, "xau_h4_ema_slow", 50) + 5:
                g3_fast = getattr(tc, "xau_h4_ema_fast", 9)
                g3_slow = getattr(tc, "xau_h4_ema_slow", 50)
                h4_cl = list(h4_data.close[-60:])
                k_f, k_s = 2.0 / (g3_fast + 1), 2.0 / (g3_slow + 1)
                ef = es = h4_cl[0]
                for p in h4_cl[1:]:
                    ef = p * k_f + ef * (1 - k_f)
                    es = p * k_s + es * (1 - k_s)
                self.h4_bullish = ef > es
                self.h4_bearish = ef < es

        # Guard 5: Intra-Session Consecutive-Loss Cooldown
        if getattr(tc, "xau_consec_loss_guard", True):
            if self.paused_today:
                log.info("[%s] G5 XAU Consec-Loss Guard: paused for rest of day (%d consecutive SLs)",
                         self.symbol, self.consec_losses)
                return False
            if self.london_paused_today and in_london:
                log.info("[%s] G5b London SL Pause: blocked London entry (lost a London trade today)", self.symbol)
                return False
            if getattr(tc, "xau_london_protect_profits", True) and self.london_won_today and in_london:
                log.info("[%s] London Profit Protect: won London trade today, locked in profit", self.symbol)
                return False

        return True

    def on_position_closed(self, cluster_pnl: float, now_utc: datetime, exit_reason: ExitReason):
        tc = self.cfg.trading
        self.last_g5_day = now_utc.date()
        h_utc = now_utc.hour
        m_utc = now_utc.minute
        in_london = (h_utc == 7 and m_utc >= 45) or (8 <= h_utc < 10) or (h_utc == 10 and m_utc <= 30)

        if getattr(tc, "xau_consec_loss_guard", True):
            max_consec = getattr(tc, "xau_consec_loss_max", 2)
            if cluster_pnl > 0:
                self.consec_losses = 0
                log.info("[%s] G5: Win recorded — streak reset to 0", self.symbol)
                if in_london:
                    self.london_won_today = True
                    log.info("[%s] 🏆 London Win recorded at %02d:%02d UTC — London profits protected for today",
                             self.symbol, h_utc, m_utc)
            else:
                self.consec_losses += 1
                if in_london:
                    self.london_paused_today = True
                    log.warning("[%s] 🛡️ G5b London SL Pause activated at %02d:%02d UTC — London entries blocked for today",
                                self.symbol, h_utc, m_utc)
                log.info("[%s] G5: SL hit — streak=%d (limit=%d)", self.symbol, self.consec_losses, max_consec)
                if self.consec_losses >= max_consec:
                    self.paused_today = True
                    log.warning("[%s] 🛡️ G5 XAU Consec-Loss Guard: %d consecutive SLs — ALL XAU entries paused for today",
                                self.symbol, self.consec_losses)

    def get_min_sl_distance(self, current_price: float, m1_atr: float) -> float:
        tc = self.cfg.trading
        return getattr(tc, "xau_min_sl_distance", 5.0)

    def get_risk_per_trade(self) -> float:
        tc = self.cfg.trading
        return tc.get_risk_per_trade(self.symbol) if hasattr(tc, "get_risk_per_trade") else getattr(tc, "xau_risk_per_trade", 0.0085)

    def on_trade_opened(self, now_utc: datetime):
        super().on_trade_opened(now_utc)
        tc = self.cfg.trading
        in_london = tc.is_in_xau_london_killzone(now_utc) if hasattr(tc, "is_in_xau_london_killzone") else (7 <= now_utc.hour < 10)
        if in_london:
            self.london_trades_today += 1
        else:
            self.ny_trades_today += 1

    def evaluate_and_trigger(
        self,
        now_utc: datetime,
        ny_dt: datetime,
        data_all: Dict[str, TimeframeData],
        m1_data: TimeframeData,
        current_price: float,
        pending_clusters: List[PyraCluster],
        account_info: AccountInfo,
    ):
        tc = self.cfg.trading
        m15_data = data_all.get("M15")
        if not m15_data or len(m15_data.close) < 15 or len(m1_data.close) < 15:
            return

        m15_closed = TimeframeData(
            tf="M15",
            time=m15_data.time[:-1],
            open=m15_data.open[:-1],
            high=m15_data.high[:-1],
            low=m15_data.low[:-1],
            close=m15_data.close[:-1],
            tick_volume=m15_data.tick_volume[:-1],
            spread=m15_data.spread[:-1],
        )

        m1_atr = atr(m1_data.high, m1_data.low, m1_data.close, getattr(tc, "xau_atr_period", 14)) or 1.0

        # Dynamic Volatility-Regime Engine classification
        if len(m15_closed.close) >= 20:
            self.vr_regime = self.vr_engine.classify(m15_closed, m1_data)
        vr = self.vr_regime

        h_utc = now_utc.hour
        m_utc = now_utc.minute
        in_london = (h_utc == 7 and m_utc >= 45) or (8 <= h_utc < 10) or (h_utc == 10 and m_utc <= 30)
        in_ny_core = (13 < h_utc < 16) or (h_utc == 13 and m_utc >= 30) or (h_utc == 16 and m_utc <= 30)

        if in_ny_core:
            disp_atr = vr.min_atr_mult
            disp_body = vr.min_body_ratio
        else:
            base_lon_atr = getattr(tc, "xau_london_displacement_atr_mult", 0.75)
            base_lon_body = getattr(tc, "xau_london_displacement_body_ratio", 0.65)
            disp_atr = max(base_lon_atr, vr.min_atr_mult)
            disp_body = max(base_lon_body, vr.min_body_ratio)

        target_r = vr.target_r
        pv = self.account.point_size(self.symbol) if hasattr(self.account, "point_size") else 0.01

        # London H1 Macro Trend Alignment Guard
        lon_trend_bias = None
        if in_london:
            req_h1 = getattr(tc, "xau_london_require_h1_trend", True)
            early_london = (h_utc == 7 and m_utc >= 45) or (h_utc == 8 and m_utc <= 30)
            if early_london or req_h1:
                h1_data = data_all.get("H1")
                if h1_data and hasattr(self.trigger, "evaluate_h4_macro_bias"):
                    from ..indicators.moving_averages import ema
                    if len(h1_data.close) >= 21:
                        ema9 = ema(h1_data.close, 9)
                        ema21 = ema(h1_data.close, 21)
                        if ema9 and ema21 and len(ema9) > 0 and len(ema21) > 0:
                            lon_trend_bias = TradeDirection.BUY if ema9[-1] > ema21[-1] else TradeDirection.SELL

        seq = self.trigger.detect_xau_scalp_sequence(
            m15_data=m15_closed,
            m1_data=m1_data,
            m1_atr=m1_atr,
            lookback_m15=getattr(tc, "xau_swing_lookback_m15", 20),
            sequence_window_m1=10,
            min_atr_mult=disp_atr,
            min_body_ratio=disp_body,
            mss_lookback=getattr(tc, "xau_mss_lookback_m1", 5),
            target_r=target_r,
            point_value=pv,
            stops_level_points=getattr(tc, "deviation_points", 10),
            liquidity_source="m15_swings",
            trend_bias=lon_trend_bias,
            enable_delta_absorption=getattr(tc, "enable_delta_absorption", True),
            enable_hvn_tp_calibration=getattr(tc, "enable_hvn_tp_calibration", True),
            min_sl_distance=self.get_min_sl_distance(current_price, m1_atr),
        )
        if not seq:
            return

        # Prevent duplicate pending in same direction
        if getattr(tc, "xau_prevent_duplicate_pending", True):
            if any(pc.direction == seq["direction"] for pc in pending_clusters):
                return

        # Check H4 Bias veto
        if getattr(tc, "xau_h4_bias_guard", False):
            if self.h4_bullish and seq["direction"] == TradeDirection.SELL:
                log.info("[%s] XAU H4 Bias: H4 BULLISH — SELL signal vetoed", self.symbol)
                return
            if self.h4_bearish and seq["direction"] == TradeDirection.BUY:
                log.info("[%s] XAU H4 Bias: H4 BEARISH — BUY signal vetoed", self.symbol)
                return

        sess_name = "NY_CORE" if in_ny_core else "LONDON_OPEN"
        utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        ny_str = ny_dt.strftime("%Y-%m-%d %H:%M:%S NY")
        log.info("[%s] 🎯 Valid Gold Scalp Sequence Detected (%s)! UTC: %s | NY: %s | Broker: %s",
                 self.symbol, sess_name, utc_str, ny_str, broker_date())
        log.info(f"[{self.symbol}] Swept: {seq['sweep_direction']} at {seq['swept_level']:.2f} | MSS={seq['mss_level']:.2f} | FVG=[{seq['fvg_low']:.2f}, {seq['fvg_high']:.2f}], Entry={seq['entry_price']:.2f}, SL={seq['sl_price']:.2f}, TP={seq['tp_price']:.2f}")

        sig = Signal(
            symbol=self.symbol,
            direction=seq["direction"],
            entry_tf="M1",
            entry_price=seq["entry_price"],
            sl_price=seq["sl_price"],
            tp_price=seq["tp_price"],
            atr_value=seq["atr"],
            score=10,
        )
        # Tiered Conviction: Grade A+ (Unicorn: 2.60x) vs Grade A (Normal: 1.00x)
        h1_data = data_all.get("H1")
        h1_bias_val = "neutral"
        if h1_data and len(h1_data.close) >= 21:
            from ..indicators.moving_averages import ema
            ema9 = ema(h1_data.close, 9)
            ema21 = ema(h1_data.close, 21)
            if ema9 and ema21 and len(ema9) > 0 and len(ema21) > 0:
                h1_bias_val = "bullish" if ema9[-1] > ema21[-1] else "bearish"

        in_ny_core_window = in_ny_core if getattr(tc, "xau_a_plus_ny_core_only", True) else True
        not_bullish_trap = (h1_bias_val != "bullish") if getattr(tc, "xau_a_plus_block_h1_bullish", False) else True
        sl_dist_ok = (abs(seq["entry_price"] - seq["sl_price"]) >= getattr(tc, "xau_a_plus_min_sl_dist", 0.0))

        if in_ny_core_window and not_bullish_trap and sl_dist_ok:
            sig.grade = SignalGrade.A_PLUS
            sig.setup_type = f"SWEEP_FVG_A_PLUS_{sess_name}"
            log.info("[%s] 🦄 UNICORN SETUP: Grade A+ Conviction Active (Scale=%.2fx)", self.symbol, getattr(tc, "conviction_scale_a_plus", 1.50))
        else:
            sig.grade = SignalGrade.A
            sig.setup_type = f"SWEEP_FVG_A_{sess_name}"
            log.info("[%s] ⚡ STANDARD SETUP: Grade A Normal Conviction Active (Scale=%.2fx)", self.symbol, getattr(tc, "conviction_scale_a", 1.00))

        sig.fvg_low = seq.get("fvg_low", 0.0)
        sig.fvg_high = seq.get("fvg_high", 0.0)

        # Risk scaling
        risk_scale = 1.0
        if getattr(tc, "enable_net_beta_gate", True):
            if self.cluster_mgr.has_same_usd_exposure(self.symbol, sig.direction):
                risk_scale = getattr(tc, "correlated_usd_risk_scale", 0.60)
                log.info("[%s] 🛡️ Net Dollar Beta Gate active: correlated USD exposure detected — scaling risk by %.2fx",
                         self.symbol, risk_scale)

        if getattr(tc, "enable_conviction_sizing", True) and hasattr(tc, "get_conviction_scale"):
            conv_scale = tc.get_conviction_scale(sig)
            risk_scale *= conv_scale

        if now_utc.weekday() == 1 and getattr(tc, "tuesday_reduced_risk", True):
            tue_scale = getattr(tc, "tuesday_risk_scale", 0.80)
            risk_scale *= tue_scale

        point_val = self.account.point_value(self.symbol) if hasattr(self.account, "point_value") else 1.0
        contract_sz = self.account.contract_size(self.symbol) if hasattr(self.account, "contract_size") else 100.0
        min_lot = self.account.min_lot(self.symbol) if hasattr(self.account, "min_lot") else 0.01
        lot_step = self.account.lot_step(self.symbol) if hasattr(self.account, "lot_step") else 0.01
        max_lot = self.account.max_lot(self.symbol) if hasattr(self.account, "max_lot") else 100.0

        use_moc = getattr(tc, "xau_require_retest", True)
        if use_moc:
            cluster = self.trade_mgr.create_pending_retest_cluster(
                signal=sig,
                limit_price=seq["entry_price"],
                account=account_info,
                point_value=point_val,
                contract_size=contract_sz,
                min_lot=min_lot,
                lot_step=lot_step,
                max_lot=max_lot,
                risk_scale=risk_scale,
            )
            if cluster:
                self.cluster_mgr.add(cluster)
                log.info(f"[{self.symbol}] 🎯 Gold FVG Zone Registered (Awaiting MoC Retest): {sig.direction.value} at {seq['entry_price']:.2f} (SL={seq['sl_price']:.2f}, TP={seq['tp_price']:.2f})")
        else:
            cluster = self.trade_mgr.execute_limit_signal(
                signal=sig,
                limit_price=seq["entry_price"],
                account=account_info,
                point_value=point_val,
                contract_size=contract_sz,
                min_lot=min_lot,
                lot_step=lot_step,
                max_lot=max_lot,
                risk_scale=risk_scale,
            )
            if cluster:
                self.cluster_mgr.add(cluster)
                log.info(f"[{self.symbol}] 📥 Pending Gold FVG Limit Order registered in cluster {cluster.cluster_id[:8]} ({sess_name}): {sig.direction.value} at {seq['entry_price']:.2f} (SL={seq['sl_price']:.2f}, TP={seq['tp_price']:.2f})")
