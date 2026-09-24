import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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
    TimeframeData, TradeDirection, TradeLeg, TradeStatus,
)
from ..strategy.trigger import TriggerDetector
from ..trade.trade_manager import TradeManager
from ..trade.cluster import ClusterManager
from ..state.persistence import StatePersistence
from ..utils.time_utils import broker_date, to_ny_time

log = logging.getLogger("xauusd_bot.engines.base")


class BaseSymbolEngine(ABC):
    """Abstract Base Class for Symbol Trading Engines.

    Encapsulates isolated state, lifecycle management, order execution,
    and monitoring for a single traded financial instrument.
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
        self.symbol = symbol
        self.cfg = config
        self.connector = connector
        self.account = account
        self.data_feed = data_feed
        self.spread_tracker = spread_tracker
        self.spread_filter = spread_filter
        self.news_filter = news_filter
        self.trigger = trigger
        self.trade_mgr = trade_mgr
        self.cluster_mgr = cluster_mgr
        self.persistence = persistence

        # Isolated state per symbol
        self.session_trades: int = 0
        self.last_exit_time: Optional[datetime] = None
        self.current_session_date: Optional[object] = None
        self.consec_losses: int = 0
        self.paused_today: bool = False
        self.last_g5_day: Optional[object] = None
        self.last_data_update_time: float = 0.0
        self.running: bool = False

    @property
    @abstractmethod
    def asset_name(self) -> str:
        """Human-readable asset name (e.g. 'Gold' or 'Nasdaq 100')."""
        pass

    @abstractmethod
    def is_session_active(self, now_utc: datetime) -> bool:
        """Determine if current time is within this symbol's active trading window."""
        pass

    @abstractmethod
    def check_symbol_guards(self, now_utc: datetime, data_all: Dict[str, TimeframeData], current_price: float) -> bool:
        """Evaluate symbol-specific guards (e.g. London Close Wall, H4 Macro Bias).

        Returns:
            True if all guards pass and entry is ALLOWED, False if vetoed.
        """
        pass

    @abstractmethod
    def on_position_closed(self, cluster_pnl: float, now_utc: datetime, exit_reason: ExitReason):
        """Callback invoked when a position on this symbol is closed (SL, TP, or manual)."""
        pass

    @abstractmethod
    def get_min_sl_distance(self, current_price: float, m1_atr: float) -> float:
        """Get minimum stop-loss breathing room distance in points/dollars."""
        pass

    @abstractmethod
    def get_risk_per_trade(self) -> float:
        """Get base fractional risk per trade for this symbol."""
        pass

    def on_trade_opened(self, now_utc: datetime):
        """Hook called when an order is actually filled into an open position."""
        self.session_trades += 1

    def sync_positions(
        self,
        now_utc: datetime,
        current_price: float,
        active_clusters: List[PyraCluster],
        pending_clusters: List[PyraCluster],
        pos_tickets: set,
    ):
        """Synchronize in-memory pending and open clusters with MT5 open deals & broker closures."""
        tc = self.cfg.trading

        # 1. Check if pending limit order was filled
        for pc in list(pending_clusters):
            for leg in pc.legs:
                if leg.position_ticket in pos_tickets:
                    now_utc_naive = now_utc.replace(tzinfo=None)
                    leg.status = TradeStatus.OPEN
                    leg.open_time = now_utc_naive
                    pc.status = TradeStatus.OPEN
                    pc.open_time = now_utc_naive
                    pc.highest_price = current_price
                    pc.lowest_price = current_price
                    self.on_trade_opened(now_utc)
                    log.info("[%s] ⚡ Pending limit order filled into OPEN position: ticket=%d",
                             self.symbol, leg.position_ticket)
                    if hasattr(self.trade_mgr, "order_entry") and hasattr(self.trade_mgr.order_entry, "reservation"):
                        self.trade_mgr.order_entry.reservation.release(getattr(pc, "signal_id", None), self.symbol)
                    if pc in pending_clusters:
                        pending_clusters.remove(pc)
                    active_clusters.append(pc)
                    break

        # 2. Check if open position was closed by broker (SL/TP hit)
        for ac in list(active_clusters):
            open_legs = [l for l in ac.legs if l.status == TradeStatus.OPEN]
            if open_legs and not any(l.position_ticket in pos_tickets for l in open_legs):
                ac.status = TradeStatus.CLOSED
                active_clusters.remove(ac)
                self.last_exit_time = now_utc.replace(tzinfo=None)
                if hasattr(self.trade_mgr, "order_entry") and hasattr(self.trade_mgr.order_entry, "reservation"):
                    self.trade_mgr.order_entry.reservation.release(getattr(ac, "signal_id", None), self.symbol)
                log.info("[%s] Position closed by broker (SL/TP) for cluster %s", self.symbol, ac.cluster_id[:8])

                # Calculate realized PnL
                cluster_pnl = 0.0
                deals = self.connector.history_deals_get(
                    ac.open_time or (now_utc - timedelta(days=1)), now_utc
                ) if hasattr(self.connector, "history_deals_get") else []
                leg_tickets = {l.position_ticket for l in ac.legs}
                found_deal = False
                for d in deals:
                    pos_id = getattr(d, "position_id", 0)
                    if pos_id in leg_tickets:
                        cluster_pnl += getattr(d, "profit", 0.0)
                        found_deal = True
                if not found_deal:
                    for l in open_legs:
                        p_pts = (current_price - l.entry_price) if l.direction == TradeDirection.BUY else (l.entry_price - current_price)
                        from ..utils.asset_specs import get_asset_spec
                        spec = get_asset_spec(self.symbol, current_price)
                        c_sz = spec.get("contract_sz", 1.0)
                        cluster_pnl += p_pts * l.lot_size * c_sz

                self.on_position_closed(cluster_pnl, now_utc, ExitReason.STOP_LOSS if cluster_pnl < 0 else ExitReason.TAKE_PROFIT)

    def manage_pending_setups(
        self,
        now_utc: datetime,
        current_price: float,
        m1_data: TimeframeData,
        pending_clusters: List[PyraCluster],
        session_active: bool,
        news_ok: bool,
        spread_ok: bool,
        account_info: AccountInfo,
    ):
        """Manage in-memory pending setups (Market-on-Confirmation) and legacy pending orders."""
        tc = self.cfg.trading
        fvg_tol_pct = getattr(tc, "fvg_adaptive_retest_tolerance_pct", 0.25)
        fvg_expiry_limit = tc.get_fvg_expiry_bars(self.symbol) if hasattr(tc, "get_fvg_expiry_bars") else getattr(tc, "xau_fvg_expiry_bars", 8)

        point_val = self.account.point_value(self.symbol) if hasattr(self.account, "point_value") else 1.0
        contract_sz = self.account.contract_size(self.symbol) if hasattr(self.account, "contract_size") else 1.0
        min_lot = self.account.min_lot(self.symbol) if hasattr(self.account, "min_lot") else 0.01
        lot_step = self.account.lot_step(self.symbol) if hasattr(self.account, "lot_step") else 0.01

        for pc in list(pending_clusters):
            should_cancel = False
            cancel_reason = ""
            fvg_h = getattr(pc, "fvg_high", 0.0)
            fvg_l = getattr(pc, "fvg_low", 0.0)
            lim_price = getattr(pc, "limit_price", getattr(pc, "highest_price", 0.0))
            is_moc_pending = (len(pc.legs) == 0 or getattr(pc.legs[0], "position_ticket", 0) == 0)

            if not session_active:
                should_cancel = True
                cancel_reason = "Session window closed"
            elif not news_ok:
                should_cancel = True
                cancel_reason = "News blackout window active"
            elif not spread_ok:
                should_cancel = True
                cancel_reason = "Excessive spread anomaly"

            elapsed_m1_bars = int((now_utc.replace(tzinfo=None) - pc.open_time).total_seconds() / 60.0) if pc.open_time else 0
            if elapsed_m1_bars >= fvg_expiry_limit:
                should_cancel = True
                cancel_reason = f"FVG setup expired after {elapsed_m1_bars} M1 bars (limit: {fvg_expiry_limit})"

            if should_cancel:
                log.info("[%s] 🛡️ Cancelling pending FVG setup %s: %s", self.symbol, pc.cluster_id[:8], cancel_reason)
                if is_moc_pending:
                    self.cluster_mgr.remove(pc)
                else:
                    self.trade_mgr._close_cluster_positions(pc, current_price, ExitReason.SIGNAL_REVERSAL)
                continue

            # Market-on-Confirmation (MoC) Retest & Fill Verification
            if is_moc_pending and lim_price > 0:
                fvg_span = abs(fvg_h - fvg_l) if (fvg_h > 0 and fvg_l > 0) else 0.0
                is_gold = "XAU" in self.symbol.upper() or "GOLD" in self.symbol.upper()
                tol = max(0.25, fvg_span * fvg_tol_pct) if is_gold else max(1.0, fvg_span * fvg_tol_pct)
                inv_buf = 0.5 * tol

                c_bar = m1_data.close[-1]
                o_bar = m1_data.open[-1]
                h_bar = m1_data.high[-1]
                l_bar = m1_data.low[-1]
                prev_l = m1_data.low[-2] if len(m1_data.low) >= 2 else l_bar
                prev_h = m1_data.high[-2] if len(m1_data.high) >= 2 else h_bar

                if pc.direction == TradeDirection.BUY:
                    if l_bar <= (lim_price + tol) or prev_l <= (lim_price + tol):
                        pc.retest_touched = True
                else:
                    if h_bar >= (lim_price - tol) or prev_h >= (lim_price - tol):
                        pc.retest_touched = True

                if getattr(pc, "retest_touched", False):
                    body = abs(c_bar - o_bar)
                    bar_range = h_bar - l_bar

                    if pc.direction == TradeDirection.BUY:
                        if fvg_l > 0 and c_bar < (fvg_l - inv_buf):
                            log.warning("[%s] 🛡️ MoC Guard: Adverse bar plunged below FVG support (Close: %.2f < FVG Low: %.2f) — Setup Discarded",
                                        self.symbol, c_bar, fvg_l)
                            self.cluster_mgr.remove(pc)
                            continue

                        confirmed = (c_bar > o_bar or (min(o_bar, c_bar) - l_bar) >= 0.4 * body or (bar_range > 0 and (c_bar - l_bar) / bar_range >= 0.5)) and c_bar >= (fvg_l - inv_buf)
                        if confirmed:
                            entered = self.trade_mgr.confirm_retest_and_enter(
                                cluster=pc,
                                account=account_info,
                                point_value=point_val,
                                contract_size=contract_sz,
                                min_lot=min_lot,
                                lot_step=lot_step,
                            )
                            if entered:
                                self.on_trade_opened(now_utc)
                    else:
                        if fvg_h > 0 and c_bar > (fvg_h + inv_buf):
                            log.warning("[%s] 🛡️ MoC Guard: Adverse bar spiked above FVG resistance (Close: %.2f > FVG High: %.2f) — Setup Discarded",
                                        self.symbol, c_bar, fvg_h)
                            self.cluster_mgr.remove(pc)
                            continue

                        confirmed = (c_bar < o_bar or (h_bar - max(o_bar, c_bar)) >= 0.4 * body or (bar_range > 0 and (h_bar - c_bar) / bar_range >= 0.5)) and c_bar <= (fvg_h + inv_buf)
                        if confirmed:
                            entered = self.trade_mgr.confirm_retest_and_enter(
                                cluster=pc,
                                account=account_info,
                                point_value=point_val,
                                contract_size=contract_sz,
                                min_lot=min_lot,
                                lot_step=lot_step,
                            )
                            if entered:
                                self.on_trade_opened(now_utc)

    def check_holding_stops(self, now_utc: datetime, current_price: float, active_positions: List[PyraCluster]):
        """Evaluate maximum holding time stop on active open positions."""
        tc = self.cfg.trading
        for c in list(active_positions):
            if c.open_time:
                bars_held = int((now_utc.replace(tzinfo=None) - c.open_time).total_seconds() / 60.0)
                max_holding = tc.get_max_holding_bars(c.symbol) if hasattr(tc, "get_max_holding_bars") else getattr(tc, "xau_max_holding_bars", 60)
                if max_holding > 0 and bars_held >= max_holding:
                    log.info("[%s] %d-bar holding time stop reached for cluster %s — closing at market",
                             self.symbol, max_holding, c.cluster_id[:8])
                    self.trade_mgr._close_cluster_positions(c, current_price, ExitReason.TIME_BASED)
                    self.last_exit_time = now_utc.replace(tzinfo=None)
                    if c in active_positions:
                        active_positions.remove(c)

    def manage_active_exits(self, data_all: Dict[str, TimeframeData]):
        """Manage exits, breakeven ratchets, and partial closes for open positions."""
        clusters = [c for c in self.cluster_mgr.active_clusters_for_symbol(self.symbol) if c.status == TradeStatus.OPEN]
        for cluster in clusters:
            actions = self.trade_mgr.manage_exits(cluster, data_all)
            for action in actions:
                log.info("[%s] Exit action: %s cluster=%s", self.symbol, action.get("action"), cluster.cluster_id[:8])

    def step(self, account_info: AccountInfo, now: float) -> bool:
        """Execute one complete lifecycle step for this symbol engine.

        Returns:
            True if cycle completed normally, False on recoverable error.
        """
        tc = self.cfg.trading
        now_utc = datetime.now(timezone.utc)
        ny_dt = to_ny_time(now_utc, getattr(tc, "xau_session_timezone", "America/New_York"))

        # Daily reset for session trade counters
        today_date = ny_dt.date()
        if self.current_session_date != today_date:
            self.current_session_date = today_date
            self.session_trades = 0

        # Update data feed if needed
        if now - self.last_data_update_time > 5.0:
            self.data_feed.update_all()
            self.last_data_update_time = now

        # Update spread tracker
        current_spread = self.account.current_spread(self.symbol)
        self.spread_tracker.update(current_spread)

        data_all = self.data_feed.all_tfs()
        m1_data = data_all.get("M1")
        if not m1_data or not m1_data.close:
            return False

        current_price = m1_data.close[-1]
        active_clusters = [c for c in self.cluster_mgr.active_clusters_for_symbol(self.symbol) if c.status == TradeStatus.OPEN]
        pending_clusters = [c for c in self.cluster_mgr.active_clusters_for_symbol(self.symbol) if c.status == TradeStatus.PENDING]

        # 0. Friday Weekend Guard: Auto-Flat Liquidation & Entry Shield
        if getattr(tc, "friday_weekend_guard", True):
            from ..filters.session_filter import is_friday_weekend_close
            fw_h = getattr(tc, "friday_close_cutoff_hour", 20)
            fw_m = getattr(tc, "friday_close_cutoff_min", 45)
            if is_friday_weekend_close(now_utc, fw_h, fw_m):
                for pc in list(pending_clusters):
                    log.warning("[%s] 🛡️ Friday Weekend Guard: Cancelling pending setup cluster %s at %02d:%02d UTC",
                                self.symbol, pc.cluster_id[:8], now_utc.hour, now_utc.minute)
                    self.trade_mgr._close_cluster_positions(pc, current_price, ExitReason.WEEKEND_CLOSE)
                    if pc in pending_clusters:
                        pending_clusters.remove(pc)

                for ac in list(active_clusters):
                    log.warning("[%s] 🛡️ Friday Weekend Guard: Auto-flat liquidating open position cluster %s at %02d:%02d UTC",
                                self.symbol, ac.cluster_id[:8], now_utc.hour, now_utc.minute)
                    self.trade_mgr._close_cluster_positions(ac, current_price, ExitReason.WEEKEND_CLOSE)
                    self.last_exit_time = now_utc.replace(tzinfo=None)
                    if ac in active_clusters:
                        active_clusters.remove(ac)
                return True

        # Sync open and pending positions with MT5
        open_pos = self.connector.positions_get(symbol=self.symbol)
        pos_tickets = {getattr(p, "ticket", 0) for p in open_pos} if open_pos else set()
        self.sync_positions(now_utc, current_price, active_clusters, pending_clusters, pos_tickets)

        # Filters: Spread, News, Session
        if hasattr(self.spread_filter, "is_spread_acceptable"):
            spread_ok = self.spread_filter.is_spread_acceptable()
        elif hasattr(self.spread_filter, "check"):
            spread_ok, _ = self.spread_filter.check()
        else:
            spread_ok = True
        news_ok, _ = self.news_filter.check(self.symbol)
        session_active = self.is_session_active(now_utc)

        # Manage pending setups
        self.manage_pending_setups(
            now_utc=now_utc,
            current_price=current_price,
            m1_data=m1_data,
            pending_clusters=pending_clusters,
            session_active=session_active,
            news_ok=news_ok,
            spread_ok=spread_ok,
            account_info=account_info,
        )

        # Holding time stops
        self.check_holding_stops(now_utc, current_price, active_clusters)

        # Manage active trades (breakeven ratchet, trailing, partials)
        self.manage_active_exits(data_all)

        # Check entry eligibility
        max_concurrent_pending = getattr(tc, "max_concurrent_pending_orders", 2)
        if len(active_clusters) > 0 or len(pending_clusters) >= max_concurrent_pending:
            return True

        if not session_active:
            return True

        max_daily_trades = getattr(tc, "max_daily_trades", 4)
        if self.session_trades >= max_daily_trades:
            return True

        # Cooldown check
        if self.last_exit_time:
            cooldown_min = getattr(tc, "xau_cooldown_minutes", 5)
            elapsed_cd = (now_utc.replace(tzinfo=None) - self.last_exit_time).total_seconds() / 60.0
            if elapsed_cd < cooldown_min:
                return True

        # Symbol-specific guards (e.g. G1 London close wall, H4 bias, G5 consec loss)
        if not self.check_symbol_guards(now_utc, data_all, current_price):
            return True

        if not spread_ok or not news_ok:
            return True

        # Scan for setup & trigger
        self.evaluate_and_trigger(now_utc, ny_dt, data_all, m1_data, current_price, pending_clusters, account_info)
        return True

    @abstractmethod
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
        """Perform technical setup analysis and submit order if criteria are met."""
        pass
