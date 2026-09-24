import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base_engine import BaseSymbolEngine
from ..config import Config
from ..broker.mt5_connector import MT5Connector
from ..broker.account import AccountManager
from ..risk.daily_loss import DailyLossTracker
from ..risk.max_dd import MaxDDTracker
from ..risk.position_sizer import PositionSizer
from ..trade.trade_manager import TradeManager
from ..trade.cluster import ClusterManager
from ..filters.news_filter import NewsFilter
from ..state.persistence import StatePersistence
from ..models import ExitReason, TradeStatus

log = logging.getLogger("xauusd_bot.engines.coordinator")


class MultiEngineCoordinator:
    """Concurrent Multi-Handling Orchestrator for Multi-Asset Algorithmic Trading.

    Coordinates concurrent execution of specialized symbol engines (e.g. XauusdEngine,
    Nas100Engine) with unified portfolio-level risk management, shared cluster state,
    and thread-safe MT5 access.
    """

    def __init__(
        self,
        config: Config,
        connector: MT5Connector,
        account: AccountManager,
        daily_loss: DailyLossTracker,
        max_dd: MaxDDTracker,
        sizer: PositionSizer,
        trade_mgr: TradeManager,
        cluster_mgr: ClusterManager,
        news_filter: NewsFilter,
        persistence: StatePersistence,
    ):
        self.cfg = config
        self.connector = connector
        self.account = account
        self.daily_loss = daily_loss
        self.max_dd = max_dd
        self.sizer = sizer
        self.trade_mgr = trade_mgr
        self.cluster_mgr = cluster_mgr
        self.news_filter = news_filter
        self.persistence = persistence

        self.engines: Dict[str, BaseSymbolEngine] = {}
        self.worker_threads: Dict[str, threading.Thread] = {}
        self.running: bool = False
        self._active_account_login: Optional[int] = None
        self._capital_calibrated: bool = False

    def register_engine(self, engine: BaseSymbolEngine):
        """Register a symbol engine under its traded symbol."""
        self.engines[engine.symbol] = engine
        log.info("Registered engine [%s] for symbol '%s'", engine.asset_name, engine.symbol)

    def get_engine(self, symbol: str) -> Optional[BaseSymbolEngine]:
        return self.engines.get(symbol)

    def close_all_positions(self, reason: str):
        """Emergency liquidation across all open clusters across all symbols."""
        log.warning("🚨 Emergency Liquidation Triggered: %s", reason)
        for cluster in list(self.cluster_mgr.active):
            sym = getattr(cluster, "symbol", "XAUUSD")
            tick = self.connector.symbol_info_tick(sym)
            price = (tick.bid + tick.ask) / 2 if tick else 0.0
            self.trade_mgr._close_cluster_positions(cluster, price, ExitReason.EQUITY_KILL)
            log.warning("[%s] Position closed due to %s at %.2f", sym, reason, price)

    def _engine_worker_loop(self, engine: BaseSymbolEngine):
        """Dedicated execution loop running in a background worker thread for a single engine."""
        sym = engine.symbol
        poll_s = self.cfg.trading.poll_interval_ms / 1000.0
        log.info("🧵 [Thread-%s] Worker thread started for %s", sym, engine.asset_name)

        while self.running and engine.running:
            try:
                account_info = self.account.refresh()
                if not account_info:
                    time.sleep(poll_s)
                    continue

                # If global kill switch engaged, pause execution
                if self.daily_loss.kill_switch_engaged() or self.max_dd.kill_switch_engaged():
                    time.sleep(poll_s * 5)
                    continue

                now = time.time()
                engine.step(account_info, now)
                time.sleep(poll_s)

            except Exception as e:
                log.exception("Unhandled error in worker thread [%s]: %s", sym, e)
                time.sleep(poll_s * 2)

        log.info("🧵 [Thread-%s] Worker thread terminated", sym)

    def start(self, mode: str = "threaded"):
        """Start the multi-engine coordinator in threaded (concurrent) or sequential mode."""
        log.info("Starting MultiEngineCoordinator in '%s' mode with %d engines: %s",
                 mode, len(self.engines), ", ".join(self.engines.keys()))

        if not self.connector.ensure_connected():
            log.critical("Failed to connect to MT5")
            return

        # Auto-resolve broker symbols and subscribe in Market Watch
        for sym in list(self.engines.keys()):
            resolved = self.connector.resolve_broker_symbol(sym)
            if resolved != sym:
                engine = self.engines.pop(sym)
                engine.symbol = resolved
                if hasattr(engine, "data_feed") and engine.data_feed:
                    engine.data_feed.symbol = resolved
                self.engines[resolved] = engine
                log.info("🎯 Auto-Resolved Engine Symbol: '%s' -> '%s'", sym, resolved)
            self.connector.symbol_select(resolved, True)

        # Initial account calibration from live MT5 broker deals
        account_init = self.account.refresh()
        if account_init:
            self._active_account_login = getattr(account_init, "login", 0) or getattr(self.cfg.mt5, "login", 0)
            self.daily_loss.calibrate_from_broker(self.connector, account_init)
            self.max_dd.update(account_init.equity)
            self.sizer.initial_balance = account_init.balance
            self._capital_calibrated = True

        self.news_filter.update_fetch()
        self.running = True
        for engine in self.engines.values():
            engine.running = True

        if mode == "threaded":
            self._start_threaded()
        else:
            self._start_sequential()

    def _start_threaded(self):
        """Launch worker threads for each symbol engine and run the portfolio watchdog on the main thread."""
        for sym, engine in self.engines.items():
            t = threading.Thread(
                target=self._engine_worker_loop,
                args=(engine,),
                name=f"Engine-{sym}",
                daemon=True,
            )
            self.worker_threads[sym] = t
            t.start()

        poll_s = self.cfg.trading.poll_interval_ms / 1000.0
        last_calendar_update = time.time()
        last_reconcile_time = time.time()

        try:
            while self.running:
                now = time.time()
                account_info = self.account.refresh()
                if not account_info:
                    time.sleep(poll_s)
                    continue

                # Auto Account-Switch Detection
                current_login = getattr(account_info, "login", 0) or getattr(self.cfg.mt5, "login", 0)
                if self._active_account_login is not None and current_login != self._active_account_login:
                    log.warning(
                        "🔄 MT5 Account Switch Detected: %s -> %s! Performing full in-memory state reset and fresh calibration.",
                        self._active_account_login, current_login,
                    )
                    self.daily_loss.reset()
                    self.max_dd._peak_equity = account_info.equity
                    self.max_dd._current_dd_pct = 0.0
                    self.max_dd._breached = False
                    self.sizer.initial_balance = account_info.balance
                    self.daily_loss.calibrate_from_broker(self.connector, account_info)
                    self._capital_calibrated = True

                self._active_account_login = current_login

                # Portfolio-level risk watchdog
                self.daily_loss.update(account_info)
                self.max_dd.update(account_info.equity)

                if self.daily_loss.kill_switch_engaged() or self.max_dd.kill_switch_engaged():
                    self.close_all_positions("portfolio_risk_limit")
                    log.warning("Portfolio risk limit breached — idling engines")
                    time.sleep(poll_s * 10)
                    continue

                # Periodic calendar update
                if now - last_calendar_update > 3600:
                    self.news_filter.update_fetch()
                    last_calendar_update = now

                # Save daily loss persistence
                self.persistence.save_daily_state(self.daily_loss.state)
                time.sleep(poll_s)

        except KeyboardInterrupt:
            log.info("KeyboardInterrupt received — stopping coordinator...")
            self.stop()
        except Exception as e:
            log.exception("Unhandled error in coordinator watchdog: %s", e)
            self.stop()

    def _start_sequential(self):
        """Sequential cooperative execution loop (single-threaded)."""
        poll_s = self.cfg.trading.poll_interval_ms / 1000.0
        last_calendar_update = time.time()

        try:
            while self.running:
                now = time.time()
                account_info = self.account.refresh()
                if not account_info:
                    time.sleep(poll_s)
                    continue

                self.daily_loss.update(account_info)
                self.max_dd.update(account_info.equity)

                if self.daily_loss.kill_switch_engaged() or self.max_dd.kill_switch_engaged():
                    self.close_all_positions("portfolio_risk_limit")
                    time.sleep(poll_s * 10)
                    continue

                if now - last_calendar_update > 3600:
                    self.news_filter.update_fetch()
                    last_calendar_update = now

                for engine in self.engines.values():
                    engine.step(account_info, now)

                self.persistence.save_daily_state(self.daily_loss.state)
                time.sleep(poll_s)

        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            log.exception("Unhandled error in sequential coordinator: %s", e)
            self.stop()

    def stop(self):
        """Gracefully stop all symbol engines and worker threads."""
        log.info("Shutting down MultiEngineCoordinator...")
        self.running = False
        for engine in self.engines.values():
            engine.running = False

        for sym, t in self.worker_threads.items():
            if t.is_alive():
                t.join(timeout=3.0)
                log.info("Joined worker thread for %s", sym)

        self.persistence.save_daily_state(self.daily_loss.state)
        log.info("Coordinator shutdown complete.")
