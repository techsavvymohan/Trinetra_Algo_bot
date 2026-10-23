"""Authoritative Daily VWAP Auction Secret Agent for Gold (XAUUSD).

Runs independently and simultaneously alongside the primary XauusdEngine.
Replaces lagging multi-hour H1 EMA with zero-lag Daily Rolling VWAP:
- When price < VWAP (Discount): Hunts BUYS on Sell-Side Liquidity (SSL) Sweeps.
- When price > VWAP (Premium): Hunts SELLS on Buy-Side Liquidity (BSL) Sweeps.
Enables clean execution of BOTH Buys and Sells on the same trading day!
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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

log = logging.getLogger("xauusd_bot.engines.vwap_agent")


class VwapAuctionAgent(BaseSymbolEngine):
    """Independent Secret Agent: Daily VWAP Auction Engine for Gold (XAUUSD).

    Key Specifications:
      - Independent lifecycle, worker thread, and session tracking.
      - Zero H1 EMA blindfold: Direction is dynamically governed by Daily VWAP.
      - Discount Zone (Price < VWAP): Accumulation -> BUY on SSL Sweep.
      - Premium Zone (Price > VWAP): Distribution -> SELL on BSL Sweep.
      - Dedicated 1:2.20 Risk-to-Reward ratio with +1.0R Breakeven ratchet.
      - Isolated order tagging: comment="VWAP_Auction_Agent".
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
        engine_id_suffix: str = "VWAP_SECRET_AGENT",
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
        self.engine_id: str = f"{symbol}_{engine_id_suffix}"
        self.london_trades_today: int = 0
        self.ny_trades_today: int = 0
        self.london_paused_today: bool = False
        self.last_vwap_day: Optional[object] = None
        self.current_day_vwap: float = 0.0
        self.paper_trades: List[Dict] = []
        self.paper_journal_path: str = "logs/vwap_paper_journal.jsonl"

    @property
    def is_paper_mode(self) -> bool:
        return getattr(self.cfg.trading, "vwap_agent_paper_mode", True)

    @property
    def asset_name(self) -> str:
        mode_str = " [PAPER / DRY-RUN]" if self.is_paper_mode else " [LIVE]"
        return f"Gold VWAP Auction Secret Agent ({self.symbol}){mode_str}"

    def step(self, account_info: AccountInfo, now_epoch: float) -> bool:
        if self.is_paper_mode and self.paper_trades:
            self._update_paper_trades()
        return super().step(account_info, now_epoch)

    def _update_paper_trades(self):
        """Update and monitor active paper trades in real-time."""
        tick = self.connector.symbol_info_tick(self.symbol)
        if not tick:
            return
        curr_bid = getattr(tick, "bid", 0.0)
        curr_ask = getattr(tick, "ask", 0.0)
        curr_p = (curr_bid + curr_ask) / 2.0
        now_dt = datetime.now(timezone.utc)

        for pt in list(self.paper_trades):
            direction = pt["direction"]
            entry_p = pt["entry_price"]
            sl_p = pt["sl_price"]
            tp_p = pt["tp_price"]
            risk_dist = pt["risk_dist"]

            # Breakeven ratchet @ +1.0R
            if not pt.get("be_moved", False):
                if direction == "BUY" and (curr_p - entry_p) >= (risk_dist * 1.0):
                    pt["sl_price"] = entry_p + (risk_dist * 0.15)
                    pt["be_moved"] = True
                    log.info("[%s] 🛡️ [PAPER TRADE] Breakeven ratchet triggered for BUY! SL moved to %.2f", self.engine_id, pt["sl_price"])
                elif direction == "SELL" and (entry_p - curr_p) >= (risk_dist * 1.0):
                    pt["sl_price"] = entry_p - (risk_dist * 0.15)
                    pt["be_moved"] = True
                    log.info("[%s] 🛡️ [PAPER TRADE] Breakeven ratchet triggered for SELL! SL moved to %.2f", self.engine_id, pt["sl_price"])

            outcome = None
            exit_price = None
            if direction == "BUY":
                if curr_bid <= pt["sl_price"]:
                    outcome = "BE" if pt.get("be_moved") else "SL"
                    exit_price = pt["sl_price"]
                elif curr_bid >= tp_p:
                    outcome = "TP"
                    exit_price = tp_p
            else:
                if curr_ask >= pt["sl_price"]:
                    outcome = "BE" if pt.get("be_moved") else "SL"
                    exit_price = pt["sl_price"]
                elif curr_ask <= tp_p:
                    outcome = "TP"
                    exit_price = tp_p

            if outcome:
                spread = getattr(self.cfg.trading, "spread_limit_xau", 0.40)
                raw_pts = (exit_price - entry_p) if direction == "BUY" else (entry_p - exit_price)
                net_pts = raw_pts - (spread + 0.10)
                lot = pt.get("lot", 0.01)
                pnl_cash = net_pts * lot * 100.0 - (7.0 * lot)
                r_mult = pnl_cash / (risk_dist * lot * 100.0) if risk_dist > 0 else 0.0

                log.info("[%s] 📝 [PAPER TRADE RESULT] %s EXITED (%s)! Exit=%.2f | Net PnL: $%.2f (%+.2f R)",
                         self.engine_id, direction, outcome, exit_price, pnl_cash, r_mult)

                pt["exit_price"] = exit_price
                pt["exit_time"] = now_dt.isoformat()
                pt["outcome"] = outcome
                pt["pnl_cash"] = round(pnl_cash, 2)
                pt["r_multiple"] = round(r_mult, 2)
                self._record_paper_journal(pt)

                self.on_position_closed(pnl_cash, now_dt, ExitReason.TAKE_PROFIT if outcome == "TP" else ExitReason.STOP_LOSS)
                self.paper_trades.remove(pt)

    def _record_paper_journal(self, trade_data: Dict):
        try:
            import json, os
            os.makedirs(os.path.dirname(self.paper_journal_path), exist_ok=True)
            with open(self.paper_journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(trade_data) + "\n")
        except Exception as e:
            log.warning("Failed to record paper journal: %s", e)

    def is_session_active(self, now_utc: datetime) -> bool:
        tc = self.cfg.trading
        h_utc = now_utc.hour
        m_utc = now_utc.minute

        if getattr(tc, "xau_strict_killzones", True):
            in_london = tc.is_in_xau_london_killzone(now_utc) if hasattr(tc, "is_in_xau_london_killzone") else (
                (h_utc == 7 and m_utc >= 45) or (8 <= h_utc < 10) or (h_utc == 10 and m_utc <= 30)
            )

            ny_end_h = getattr(tc, "xau_london_close_cutoff_hour", 16)
            ny_end_m = getattr(tc, "xau_london_close_cutoff_min", 30)
            in_ny_core = (13 < h_utc < ny_end_h) or (h_utc == 13 and m_utc >= 30) or (h_utc == ny_end_h and m_utc <= ny_end_m)

            cutoff_h = getattr(tc, "xau_session_cutoff_hour", 24)
            if cutoff_h < 24 and h_utc >= cutoff_h:
                in_ny_core = False
            return in_london or in_ny_core

        return True

    def check_symbol_guards(self, now_utc: datetime, data_all: Dict[str, TimeframeData], current_price: float) -> bool:
        tc = self.cfg.trading
        h_utc = now_utc.hour
        m_utc = now_utc.minute

        today_date = now_utc.date()
        if self.last_g5_day is not None and self.last_g5_day != today_date:
            self.consec_losses = 0
            self.paused_today = False
            self.london_trades_today = 0
            self.ny_trades_today = 0
            self.london_paused_today = False
        self.last_g5_day = today_date

        in_london = tc.is_in_xau_london_killzone(now_utc) if hasattr(tc, "is_in_xau_london_killzone") else (7 <= h_utc < 11)
        ny_end_h = getattr(tc, "xau_london_close_cutoff_hour", 16)
        ny_end_m = getattr(tc, "xau_london_close_cutoff_min", 30)
        in_ny_core = (13 < h_utc < ny_end_h) or (h_utc == 13 and m_utc >= 30) or (h_utc == ny_end_h and m_utc <= ny_end_m)

        max_sess_trades = getattr(tc, "xau_max_trades_per_session", 2)
        if in_london and self.london_trades_today >= max_sess_trades:
            return False
        if in_ny_core and self.ny_trades_today >= max_sess_trades:
            return False

        if getattr(tc, "xau_london_close_guard", True):
            if h_utc > ny_end_h or (h_utc == ny_end_h and m_utc >= ny_end_m):
                return False

        if self.paused_today:
            log.info("[%s] VWAP Secret Agent: paused for rest of day (%d consecutive SLs)",
                     self.engine_id, self.consec_losses)
            return False

        return True

    def calculate_daily_vwap(self, m1_data: TimeframeData, now_utc: datetime) -> float:
        """Calculate true Volume-Weighted Average Price (VWAP) for the current UTC day."""
        if not m1_data.close or not m1_data.time:
            return 0.0

        n = len(m1_data.close)
        today_date = now_utc.date()
        cum_pv = 0.0
        cum_vol = 0.0

        times = m1_data.time
        highs = m1_data.high
        lows = m1_data.low
        closes = m1_data.close
        vols = m1_data.tick_volume if m1_data.tick_volume else [1.0] * n

        # Walk backwards until midnight UTC
        for i in range(n - 1, -1, -1):
            t_val = times[i]
            if isinstance(t_val, datetime):
                bar_dt = t_val if t_val.tzinfo else t_val.replace(tzinfo=timezone.utc)
            elif isinstance(t_val, (int, float)):
                bar_dt = datetime.fromtimestamp(t_val, tz=timezone.utc)
            else:
                continue
            if bar_dt.date() != today_date:
                break
            typical = (highs[i] + lows[i] + closes[i]) / 3.0
            vol = float(vols[i]) if vols[i] > 0 else 1.0
            cum_pv += typical * vol
            cum_vol += vol

        if cum_vol > 0:
            self.current_day_vwap = cum_pv / cum_vol
            return self.current_day_vwap
        return m1_data.close[-1]

    def on_position_closed(self, cluster_pnl: float, now_utc: datetime, exit_reason: ExitReason):
        super().on_position_closed(cluster_pnl, now_utc, exit_reason)
        tc = self.cfg.trading
        self.last_g5_day = now_utc.date()

        in_lon = tc.is_in_xau_london_killzone(now_utc) if hasattr(tc, "is_in_xau_london_killzone") else (7 <= now_utc.hour < 11)
        if in_lon and cluster_pnl < 0:
            self.london_paused_today = True

        max_consec = getattr(tc, "xau_consec_loss_max", 2)
        if cluster_pnl > 0:
            self.consec_losses = 0
            log.info("[%s] Win recorded — streak reset to 0", self.engine_id)
        else:
            self.consec_losses += 1
            log.info("[%s] SL hit — streak=%d (limit=%d)", self.engine_id, self.consec_losses, max_consec)
            if self.consec_losses >= max_consec:
                self.paused_today = True
                log.warning("[%s] 🛡️ VWAP Secret Agent: %d consecutive SLs — entries paused for today",
                            self.engine_id, self.consec_losses)

    def get_min_sl_distance(self, current_price: float, m1_atr: float) -> float:
        return getattr(self.cfg.trading, "vwap_agent_min_sl_distance", 5.0)

    def get_risk_per_trade(self) -> float:
        return getattr(self.cfg.trading, "vwap_agent_risk_pct", 0.0085)

    def on_trade_opened(self, now_utc: datetime):
        super().on_trade_opened(now_utc)
        tc = self.cfg.trading
        in_london = tc.is_in_xau_london_killzone(now_utc) if hasattr(tc, "is_in_xau_london_killzone") else (7 <= now_utc.hour < 11)
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
        """Evaluate Daily VWAP Auction setups (Discount Buys and Premium Sells)."""
        tc = self.cfg.trading
        m15_data = data_all.get("M15")
        if not m15_data or len(m15_data.close) < 16 or len(m1_data.close) < 15:
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

        # 1. Calculate Daily Rolling VWAP
        daily_vwap = self.calculate_daily_vwap(m1_data, now_utc)
        if daily_vwap <= 0.0:
            return

        # 2. Identify Auction Regime
        is_discount = current_price < daily_vwap
        is_premium = current_price > daily_vwap

        # 3. Identify M15 External Liquidity Swings
        lookback_bars = getattr(tc, "vwap_agent_swing_lookback_m15", 16)
        h15 = m15_closed.high[-lookback_bars:]
        l15 = m15_closed.low[-lookback_bars:]
        bsl = max(h15)
        ssl = min(l15)

        m1_atr = atr(m1_data.high, m1_data.low, m1_data.close, 14) or 1.0
        c1 = m1_data.close
        h1 = m1_data.high
        l1 = m1_data.low
        o1 = m1_data.open
        n1 = len(c1)

        target_r = getattr(tc, "vwap_agent_target_rr", 2.20)
        curr_c = c1[-1]
        curr_h = h1[-1]
        curr_l = l1[-1]
        curr_o = o1[-1]

        detected_setup: Optional[Dict] = None

        # -------------------------------------------------------------
        # DISCOUNT AUCTION (Price < VWAP) -> HUNT BUYS ON SSL SWEEPS
        # -------------------------------------------------------------
        if is_discount:
            # Check if any of last 10 M1 bars swept SSL
            swept_ssl = any(l < ssl for l in l1[-10:])
            if swept_ssl and curr_c > ssl:
                body = curr_c - curr_o
                rng = curr_h - curr_l
                # Displacement verification
                if body > 0 and (body / m1_atr) >= 0.70 and (body / (rng + 1e-4)) >= 0.55:
                    prior_high = max(h1[-5:-1])
                    if curr_c > prior_high:  # Closed MSS Breakout
                        entry_p = curr_c
                        sweep_low = min(l1[-10:])
                        sl_p = sweep_low - (m1_atr * 1.5)
                        risk_dist = entry_p - sl_p
                        min_sl = self.get_min_sl_distance(current_price, m1_atr)
                        if risk_dist < min_sl:
                            risk_dist = min_sl
                            sl_p = entry_p - risk_dist

                        if 2.5 <= risk_dist <= 12.0:
                            tp_p = entry_p + (risk_dist * target_r)
                            detected_setup = {
                                "direction": TradeDirection.BUY,
                                "entry_price": entry_p,
                                "sl_price": sl_p,
                                "tp_price": tp_p,
                                "risk_dist": risk_dist,
                                "swept_level": ssl,
                                "sweep_type": "SSL_DISCOUNT_SWEEP",
                                "fvg_low": sweep_low,
                                "fvg_high": entry_p,
                            }

        # -------------------------------------------------------------
        # PREMIUM AUCTION (Price > VWAP) -> HUNT SELLS ON BSL SWEEPS
        # -------------------------------------------------------------
        elif is_premium:
            swept_bsl = any(h > bsl for h in h1[-10:])
            if swept_bsl and curr_c < bsl:
                body = curr_o - curr_c
                rng = curr_h - curr_l
                if body > 0 and (body / m1_atr) >= 0.70 and (body / (rng + 1e-4)) >= 0.55:
                    prior_low = min(l1[-5:-1])
                    if curr_c < prior_low:  # Closed MSS Breakdown
                        entry_p = curr_c
                        sweep_high = max(h1[-10:])
                        sl_p = sweep_high + (m1_atr * 1.5)
                        risk_dist = sl_p - entry_p
                        min_sl = self.get_min_sl_distance(current_price, m1_atr)
                        if risk_dist < min_sl:
                            risk_dist = min_sl
                            sl_p = entry_p + risk_dist

                        if 2.5 <= risk_dist <= 12.0:
                            tp_p = entry_p - (risk_dist * target_r)
                            detected_setup = {
                                "direction": TradeDirection.SELL,
                                "entry_price": entry_p,
                                "sl_price": sl_p,
                                "tp_price": tp_p,
                                "risk_dist": risk_dist,
                                "swept_level": bsl,
                                "sweep_type": "BSL_PREMIUM_SWEEP",
                                "fvg_low": entry_p,
                                "fvg_high": sweep_high,
                            }

        if not detected_setup:
            return

        h_utc = now_utc.hour
        in_ny_core = (13 <= h_utc <= 16)
        sess_name = "NY_CORE" if in_ny_core else "LONDON_OPEN"
        utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

        log.info("[%s] 🕵️ VWAP AUCTION SECRET AGENT TRIGGERED (%s)! UTC: %s | VWAP: %.2f",
                 self.engine_id, sess_name, utc_str, daily_vwap)
        log.info(f"[{self.engine_id}] {detected_setup['direction'].value} Setup: Swept={detected_setup['sweep_type']} at {detected_setup['swept_level']:.2f} | Entry={detected_setup['entry_price']:.2f}, SL={detected_setup['sl_price']:.2f}, TP={detected_setup['tp_price']:.2f} (RR={target_r})")

        # -----------------------------------------------------------------
        # OPTION 2: PAPER / DRY-RUN FORWARD TESTING MODE (ZERO REAL CAPITAL RISK)
        # -----------------------------------------------------------------
        if self.is_paper_mode:
            dir_str = detected_setup["direction"].value.upper()
            if any(pt["direction"] == dir_str for pt in self.paper_trades):
                return

            lot = round((account_info.balance * self.get_risk_per_trade()) / (detected_setup["risk_dist"] * 100.0), 2)
            lot = max(0.01, min(lot, 1.0))

            paper_trade = {
                "id": f"PAPER_{int(now_utc.timestamp())}",
                "symbol": self.symbol,
                "direction": dir_str,
                "entry_price": detected_setup["entry_price"],
                "sl_price": detected_setup["sl_price"],
                "tp_price": detected_setup["tp_price"],
                "risk_dist": detected_setup["risk_dist"],
                "lot": lot,
                "entry_time": now_utc.isoformat(),
                "swept_level": detected_setup["swept_level"],
                "sweep_type": detected_setup["sweep_type"],
                "daily_vwap": round(daily_vwap, 2),
                "target_r": target_r,
                "be_moved": False,
            }
            self.paper_trades.append(paper_trade)
            self.on_trade_opened(now_utc)
            self._record_paper_journal(paper_trade)
            log.info("[%s] 📝 [PAPER TRADE OPENED] %s at %.2f | SL=%.2f, TP=%.2f (RR=%.2f) | Lot=%.2f | ZERO REAL RISK",
                     self.engine_id, paper_trade["direction"], paper_trade["entry_price"],
                     paper_trade["sl_price"], paper_trade["tp_price"], target_r, lot)
            return

        # -----------------------------------------------------------------
        # LIVE EXECUTION MODE (When paper mode is explicitly False)
        # -----------------------------------------------------------------
        # Prevent duplicate pending cluster in same direction for this agent
        agent_pending = [pc for pc in pending_clusters if getattr(pc, "strategy", "") == "VWAP_AUCTION"]
        if any(pc.direction == detected_setup["direction"] for pc in agent_pending):
            return

        sig = Signal(
            symbol=self.symbol,
            direction=detected_setup["direction"],
            entry_tf="M1",
            entry_price=detected_setup["entry_price"],
            sl_price=detected_setup["sl_price"],
            tp_price=detected_setup["tp_price"],
            atr_value=m1_atr,
            score=9,
        )
        sig.grade = SignalGrade.A
        sig.setup_type = f"VWAP_AUCTION_{sess_name}"
        sig.fvg_low = detected_setup["fvg_low"]
        sig.fvg_high = detected_setup["fvg_high"]
        sig.dynamic_t1_r = 1.00  # Breakeven @ 1.0R
        sig.dynamic_t2_r = target_r

        risk_scale = self.get_risk_per_trade() / getattr(tc, "xau_risk_per_trade", 0.0085)

        point_val = self.account.point_value(self.symbol) if hasattr(self.account, "point_value") else 1.0
        contract_sz = self.account.contract_size(self.symbol) if hasattr(self.account, "contract_size") else 100.0
        min_lot = self.account.min_lot(self.symbol) if hasattr(self.account, "min_lot") else 0.01
        lot_step = self.account.lot_step(self.symbol) if hasattr(self.account, "lot_step") else 0.01
        max_lot = self.account.max_lot(self.symbol) if hasattr(self.account, "max_lot") else 100.0

        cluster = self.trade_mgr.create_pending_retest_cluster(
            signal=sig,
            limit_price=detected_setup["entry_price"],
            account=account_info,
            point_value=point_val,
            contract_size=contract_sz,
            min_lot=min_lot,
            lot_step=lot_step,
            max_lot=max_lot,
            risk_scale=risk_scale,
        )
        if cluster:
            cluster.strategy = "VWAP_AUCTION"
            cluster.engine_id = self.engine_id
            self.cluster_mgr.add(cluster)
            self.on_trade_opened(now_utc)
            log.info(f"[{self.engine_id}] 🎯 Secret Agent MoC Cluster Registered: {sig.direction.value} at {detected_setup['entry_price']:.2f}")
