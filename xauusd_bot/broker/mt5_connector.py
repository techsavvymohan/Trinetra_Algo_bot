import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from ..config import MT5Config

log = logging.getLogger("xauusd_bot.broker")


class MT5Connector:
    def __init__(self, cfg: MT5Config):
        self.cfg = cfg
        self._connected = False
        self._reconnect_attempts = 0
        self._lock = threading.RLock()

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def connect(self) -> bool:
        with self._lock:
            if self._connected:
                return True
            if mt5 is None:
                log.error("MetaTrader5 package is not installed. Please run: pip install MetaTrader5")
                return False

            init_kwargs = {"timeout": self.cfg.timeout_ms}
            if self.cfg.path and Path(self.cfg.path).exists():
                init_kwargs["path"] = self.cfg.path
            if self.cfg.login:
                init_kwargs["login"] = self.cfg.login
            if self.cfg.password:
                init_kwargs["password"] = self.cfg.password
            if self.cfg.server:
                init_kwargs["server"] = self.cfg.server

            ok = mt5.initialize(**init_kwargs)
            if not ok:
                err = mt5.last_error()
                log.warning("Direct MT5 initialize failed: %s — trying fallback attach & login...", err)
                # Fallback 1: Try attaching to existing running terminal or start path without credential parameters
                attached = mt5.initialize(path=self.cfg.path, timeout=self.cfg.timeout_ms) if (self.cfg.path and Path(self.cfg.path).exists()) else mt5.initialize(timeout=self.cfg.timeout_ms)
                if not attached:
                    # Fallback 2: Attach to any active GUI terminal instance
                    attached = mt5.initialize()

                if attached:
                    if self.cfg.login and self.cfg.server:
                        logged_in = mt5.login(
                            login=self.cfg.login,
                            password=self.cfg.password,
                            server=self.cfg.server,
                            timeout=self.cfg.timeout_ms,
                        )
                        if logged_in:
                            ok = True
                        else:
                            login_err = mt5.last_error()
                            log.error("MT5 login failed for account %s on %s: %s", self.cfg.login, self.cfg.server, login_err)
                            mt5.shutdown()
                            return False
                    else:
                        ok = True
                else:
                    log.error("MT5 initialize failed completely: %s", err)
                    return False

            self._connected = True
            acc = mt5.account_info()
            actual_login = getattr(acc, "login", self.cfg.login)
            actual_server = getattr(acc, "server", self.cfg.server)
            log.info("MT5 connected — account %s on %s", actual_login, actual_server)
            return True

    def disconnect(self):
        with self._lock:
            if self._connected:
                mt5.shutdown()
                self._connected = False
                log.info("MT5 disconnected")

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and mt5 is not None and mt5.terminal_info() is not None

    def reconnect(self, max_retries: int = 3, delay: float = 2.0) -> bool:
        self.disconnect()
        for attempt in range(1, max_retries + 1):
            log.info("Reconnect attempt %d/%d", attempt, max_retries)
            if self.connect():
                return True
            if attempt < max_retries:
                time.sleep(delay)
        return False

    def ensure_connected(self) -> bool:
        if self.is_connected:
            self._reconnect_attempts = 0
            return True
        delay = min(2.0 * (2 ** self._reconnect_attempts), 60.0)
        self._reconnect_attempts += 1
        log.warning("Reconnecting (attempt %d, delay=%.1fs)", self._reconnect_attempts, delay)
        time.sleep(delay)
        return self.reconnect()

    def symbol_info(self, symbol: str = "XAUUSD"):
        with self._lock:
            if mt5 is None:
                return None
            return mt5.symbol_info(symbol)

    def symbol_info_tick(self, symbol: str = "XAUUSD"):
        with self._lock:
            if mt5 is None:
                return None
            return mt5.symbol_info_tick(symbol)

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        with self._lock:
            if mt5 is None:
                return False
            return mt5.symbol_select(symbol, enable)

    def resolve_broker_symbol(self, symbol: str) -> str:
        """
        Auto-detects the exact active, tradeable broker symbol variant for any input symbol.
        Supports XAUUSD / GOLD / USTECH100M / NAS100 across all brokers (suffixes: .x, .pro, .raw, +, m, etc.)
        and automatically subscribes it in Market Watch.
        """
        with self._lock:
            if mt5 is None:
                return symbol

            sym_clean = symbol.strip()
            sym_upper = sym_clean.upper()
            trade_disabled = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)

            # 1. Direct check: If exact symbol exists and is tradeable
            info = mt5.symbol_info(sym_clean)
            if info is not None and getattr(info, "trade_mode", 1) != trade_disabled:
                mt5.symbol_select(sym_clean, True)
                return info.name

            # 2. Retrieve all available symbols from the broker
            all_syms = mt5.symbols_get() or []
            tradeable = [s for s in all_syms if getattr(s, "trade_mode", 1) != trade_disabled]
            if not tradeable:
                tradeable = all_syms

            # Case-insensitive direct match (e.g. US100CASH -> US100Cash)
            for s in tradeable:
                if s.name.upper() == sym_upper:
                    mt5.symbol_select(s.name, True)
                    return s.name

            # 3. Determine asset family / root aliases
            if "XAU" in sym_upper or "GOLD" in sym_upper:
                roots = ["XAUUSD", "GOLD"]
            elif any(idx in sym_upper for idx in ["USTEC", "NAS", "US100", "TECH"]):
                roots = ["US100CASH", "US100", "USTECH100M", "NAS100", "USTECH", "NASDAQ"]
            else:
                root_cand = re.sub(r"[._+].*$", "", sym_upper)
                roots = [root_cand] if root_cand else [sym_upper]

            # Priority A: Exact match with root alias
            for root in roots:
                for s in tradeable:
                    if s.name.upper() == root:
                        mt5.symbol_select(s.name, True)
                        log.info("🎯 Auto-detected broker symbol: '%s' -> '%s'", symbol, s.name)
                        return s.name

            # Priority B: Standard broker suffixes
            suffixes = [".x", ".pro", ".raw", ".ecn", ".stp", "+", "m", ".s", "_sb", ".c", "i", ".r"]
            for root in roots:
                for sfx in suffixes:
                    cand = f"{root}{sfx}".upper()
                    for s in tradeable:
                        if s.name.upper() == cand:
                            mt5.symbol_select(s.name, True)
                            log.info("🎯 Auto-detected broker symbol: '%s' -> '%s'", symbol, s.name)
                            return s.name

            # Priority C: Symbol starts with root
            for root in roots:
                for s in tradeable:
                    if s.name.upper().startswith(root):
                        mt5.symbol_select(s.name, True)
                        log.info("🎯 Auto-detected broker symbol: '%s' -> '%s'", symbol, s.name)
                        return s.name

            # Priority D: Root contained in symbol name
            for root in roots:
                for s in tradeable:
                    if root in s.name.upper():
                        mt5.symbol_select(s.name, True)
                        log.info("🎯 Auto-detected broker symbol: '%s' -> '%s'", symbol, s.name)
                        return s.name

            log.warning("Could not auto-detect broker symbol for '%s', keeping original", symbol)
            return symbol

    def symbols_get(self):
        with self._lock:
            if mt5 is None:
                return []
            return mt5.symbols_get() or []

    def account_info(self):
        with self._lock:
            if mt5 is None:
                return None
            return mt5.account_info()

    def positions_get(self, symbol: str = "", magic: int = 0):
        with self._lock:
            if mt5 is None:
                return []
            kwargs = {}
            if symbol:
                kwargs["symbol"] = symbol
            if magic:
                kwargs["magic"] = magic
            return mt5.positions_get(**kwargs) or []

    def orders_get(self, symbol: str = "", magic: int = 0):
        with self._lock:
            if mt5 is None:
                return []
            kwargs = {}
            if symbol:
                kwargs["symbol"] = symbol
            if magic:
                kwargs["magic"] = magic
            return mt5.orders_get(**kwargs) or []

    def order_send(self, request: dict) -> Optional[dict]:
        with self._lock:
            if mt5 is None:
                log.error("MetaTrader5 package is not installed.")
                return None
            result = mt5.order_send(request)
            if result is None:
                log.error("order_send returned None — MT5 error: %s", mt5.last_error())
                return None
            trade_retcode_done = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            trade_retcode_placed = getattr(mt5, "TRADE_RETCODE_PLACED", 10008)
            trade_retcode_partial = getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
            trade_retcode_no_changes = getattr(mt5, "TRADE_RETCODE_NO_CHANGES", 10025)
            acceptable_retcodes = {trade_retcode_done, trade_retcode_placed, trade_retcode_partial, trade_retcode_no_changes}
            if result.retcode not in acceptable_retcodes:
                log.error("Order failed retcode=%d: %s", result.retcode, result.comment)
                return None
            return result

    def history_deals_get(self, from_date, to_date):
        with self._lock:
            if mt5 is None:
                return []
            return mt5.history_deals_get(from_date, to_date) or []

    def copy_rates_from_pos(self, symbol: str, tf: int, start: int, count: int):
        with self._lock:
            if mt5 is None:
                return None
            return mt5.copy_rates_from_pos(symbol, tf, start, count)

    @staticmethod
    def tf_to_mt5(tf: str) -> int:
        if mt5 is None:
            return 1
        mapping = {
            "M1": getattr(mt5, "TIMEFRAME_M1", 1),
            "M5": getattr(mt5, "TIMEFRAME_M5", 5),
            "M15": getattr(mt5, "TIMEFRAME_M15", 15),
            "M30": getattr(mt5, "TIMEFRAME_M30", 30),
            "H1": getattr(mt5, "TIMEFRAME_H1", 16385),
            "H4": getattr(mt5, "TIMEFRAME_H4", 16388),
        }
        return mapping.get(tf, 1)
