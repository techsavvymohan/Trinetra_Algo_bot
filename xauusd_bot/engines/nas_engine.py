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
    AccountInfo, ExitReason, PyraCluster, Signal, SignalGrade,
    TimeframeData, TradeDirection, TradeStatus,
)
from ..strategy.trigger import TriggerDetector
from ..trade.trade_manager import TradeManager
from ..trade.cluster import ClusterManager
from ..state.persistence import StatePersistence
from ..utils.time_utils import broker_date, to_ny_time

log = logging.getLogger("xauusd_bot.engines.nas")


class Nas100Engine(BaseSymbolEngine):
    """Dedicated Institutional Trading Engine for Nasdaq 100 (USTECH100M / NAS100 / US100).

    Specialized for Nasdaq 100 index dynamics:
      - US Cash Open & Core Trading Session (13:30–20:00 UTC / 9:30 AM–4:00 PM NY)
      - Independent Consecutive-Loss Guard (nas_consec_loss_guard & nas_consec_loss_max)
      - Independent daily trade counters & cooldowns (zero interference with Gold)
      - Index Contract Specifications (1.0 contract size, 0.1/1.0 point value)
      - Minimum SL breathing room floor for index volatility (5.0–10.0 pts)
      - Tailored Target-R (2.0R) and Breakeven Ratchet (1.5R)
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

    @property
    def asset_name(self) -> str:
        return "Nasdaq 100 (NAS100 / USTECH100M)"

    def is_session_active(self, now_utc: datetime) -> bool:
        """Determine if current time is within Nasdaq 100 active US cash session."""
        tc = self.cfg.trading
        if hasattr(tc, "is_in_nas_session"):
            return tc.is_in_nas_session(now_utc)
        h_utc = now_utc.hour
        m_utc = now_utc.minute
        return (13 < h_utc < 20) or (h_utc == 13 and m_utc >= 30)

    def check_symbol_guards(self, now_utc: datetime, data_all: Dict[str, TimeframeData], current_price: float) -> bool:
        tc = self.cfg.trading

        # Reset daily tracking on day transition
        today_date = now_utc.date()
        if self.last_g5_day is not None and self.last_g5_day != today_date:
            self.consec_losses = 0
            self.paused_today = False
            self.session_trades = 0
        self.last_g5_day = today_date

        # Dedicated NAS Consecutive-Loss Guard
        if getattr(tc, "nas_consec_loss_guard", True) and self.paused_today:
            log.info("[%s] 🛡️ NAS Consec-Loss Guard: paused for rest of day (%d consecutive SLs)",
                     self.symbol, self.consec_losses)
            return False

        return True

    def on_position_closed(self, cluster_pnl: float, now_utc: datetime, exit_reason: ExitReason):
        tc = self.cfg.trading
        self.last_g5_day = now_utc.date()
        if getattr(tc, "nas_consec_loss_guard", True):
            max_consec = getattr(tc, "nas_consec_loss_max", 2)
            if cluster_pnl > 0:
                self.consec_losses = 0
                log.info("[%s] 🏆 NAS100 Win recorded — streak reset to 0", self.symbol)
            else:
                self.consec_losses += 1
                log.info("[%s] 🛡️ NAS100 SL hit — streak=%d (limit=%d)", self.symbol, self.consec_losses, max_consec)
                if self.consec_losses >= max_consec:
                    self.paused_today = True
                    log.warning("[%s] 🛡️ NAS Consec-Loss Guard: %d consecutive SLs — ALL NAS100 entries paused for today",
                                self.symbol, self.consec_losses)

    def get_min_sl_distance(self, current_price: float, m1_atr: float) -> float:
        tc = self.cfg.trading
        return getattr(tc, "nas_min_sl_distance", 5.0)

    def get_risk_per_trade(self) -> float:
        tc = self.cfg.trading
        return getattr(tc, "nas_risk_per_trade", 0.025)

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

        m1_atr = atr(m1_data.high, m1_data.low, m1_data.close, getattr(tc, "atr_period", 14)) or 5.0

        disp_atr = getattr(tc, "xau_displacement_atr_mult", 0.60)
        disp_body = getattr(tc, "xau_displacement_body_ratio", 0.60)
        target_r = getattr(tc, "nas_target_r", 2.0)
        pv = self.account.point_size(self.symbol) if hasattr(self.account, "point_size") else 0.1

        h1_data = data_all.get("H1")
        trend_bias = None
        if getattr(tc, "nas_require_h1_trend", True) and h1_data and len(h1_data.close) >= 20:
            from ..indicators.moving_averages import ema
            fast_ema = ema(h1_data.close, 9)
            slow_ema = ema(h1_data.close, 50)
            if fast_ema is not None and slow_ema is not None:
                trend_bias = TradeDirection.BUY if fast_ema > slow_ema else TradeDirection.SELL

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
            trend_bias=trend_bias,
            enable_delta_absorption=getattr(tc, "enable_delta_absorption", True),
            enable_hvn_tp_calibration=getattr(tc, "enable_hvn_tp_calibration", True),
            min_sl_distance=self.get_min_sl_distance(current_price, m1_atr),
        )
        if not seq:
            return

        # Prevent duplicate pending orders in same direction
        if getattr(tc, "xau_prevent_duplicate_pending", True):
            if any(pc.direction == seq["direction"] for pc in pending_clusters):
                return

        utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        ny_str = ny_dt.strftime("%Y-%m-%d %H:%M:%S NY")
        log.info("[%s] 🎯 Valid Nasdaq 100 Scalp Sequence Detected (US_CASH)! UTC: %s | NY: %s | Broker: %s",
                 self.symbol, utc_str, ny_str, broker_date())
        log.info(f"[{self.symbol}] Swept: {seq['sweep_direction']} at {seq['swept_level']:.1f} | MSS={seq['mss_level']:.1f} | FVG=[{seq['fvg_low']:.1f}, {seq['fvg_high']:.1f}], Entry={seq['entry_price']:.1f}, SL={seq['sl_price']:.1f}, TP={seq['tp_price']:.1f}")

        # Tiered Conviction Grading for Nasdaq:
        # Grade A+ (Unicorn Index Setup: 1.50x) vs Grade A (Normal: 1.00x)
        in_prime_nas = tc.is_in_nas_session(now_utc)
        trend_ok = (trend_bias == seq["direction"]) if trend_bias is not None else False
        sl_dist_ok = (abs(seq["entry_price"] - seq["sl_price"]) >= getattr(tc, "nas_min_sl_distance", 10.0))
        grade = SignalGrade.A_PLUS if (in_prime_nas and trend_ok and sl_dist_ok) else SignalGrade.A

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
        sig.grade = grade
        sig.setup_type = "SWEEP_FVG_US_CASH"
        sig.fvg_low = seq.get("fvg_low", 0.0)
        sig.fvg_high = seq.get("fvg_high", 0.0)

        # Net Dollar Beta Gate (Correlation Shield)
        risk_scale = 1.0
        if getattr(tc, "enable_net_beta_gate", True):
            if self.cluster_mgr.has_same_usd_exposure(self.symbol, sig.direction):
                risk_scale = getattr(tc, "correlated_usd_risk_scale", 0.60)
                log.info("[%s] 🛡️ Net Dollar Beta Gate active: correlated USD exposure detected — scaling risk by %.2fx",
                         self.symbol, risk_scale)

        # Conviction sizing
        if getattr(tc, "enable_conviction_sizing", True) and hasattr(tc, "get_conviction_scale"):
            conv_scale = tc.get_conviction_scale(sig)
            risk_scale *= conv_scale

        point_val = self.account.point_value(self.symbol) if hasattr(self.account, "point_value") else 0.1
        contract_sz = self.account.contract_size(self.symbol) if hasattr(self.account, "contract_size") else 1.0
        min_lot = self.account.min_lot(self.symbol) if hasattr(self.account, "min_lot") else 0.01
        lot_step = self.account.lot_step(self.symbol) if hasattr(self.account, "lot_step") else 0.01
        max_lot = self.account.max_lot(self.symbol) if hasattr(self.account, "max_lot") else 100.0

        use_moc = getattr(tc, "nas_require_retest", True)
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
                log.info(f"[{self.symbol}] 🎯 Nasdaq 100 FVG Zone Registered (Awaiting MoC Retest): {sig.direction.value} at {seq['entry_price']:.1f} (SL={seq['sl_price']:.1f}, TP={seq['tp_price']:.1f})")
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
                log.info(f"[{self.symbol}] 📥 Pending Nasdaq 100 FVG Limit Order registered in cluster {cluster.cluster_id[:8]}: {sig.direction.value} at {seq['entry_price']:.1f} (SL={seq['sl_price']:.1f}, TP={seq['tp_price']:.1f})")
