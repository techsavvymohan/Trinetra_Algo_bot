import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..models import DailyState, ExitReason, PyraCluster, TradeDirection, TradeLeg, TradeStatus

log = logging.getLogger("xauusd_bot.state.persistence")


class StatePersistence:
    """Zero-DB lightweight persistence layer.
    
    Eliminates fragile SQLite file locks and cross-account state corruption.
    State is maintained dynamically in-memory from MT5 broker deals,
    while completed trade logs are cleanly persisted to CSV for auditing.
    """

    def __init__(self, db_path: str = "data/bot_state.db", trade_log_path: str = "data/trade_log.csv"):
        self.db_path = db_path
        self.trade_log_path = trade_log_path
        self._last_daily_state: Optional[DailyState] = None
        Path(trade_log_path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        """No-op connection for zero-DB architecture."""
        pass

    def save_daily_state(self, state: DailyState):
        """In-memory cache of daily state (no database write)."""
        self._last_daily_state = state

    def load_daily_state(self) -> Optional[DailyState]:
        """Return in-memory daily state or None."""
        return self._last_daily_state

    def save_trade_leg(self, leg: TradeLeg, cluster_id: str, signal_id: str, entry_tf: str = ""):
        """Log trade leg execution."""
        log.info(
            "Trade leg recorded: cluster=%s leg=%s dir=%s entry=%.5f exit=%s pnl=%.2f status=%s",
            cluster_id[:8] if cluster_id else "",
            leg.leg_id[:8] if leg.leg_id else "",
            leg.direction.value,
            leg.entry_price,
            f"{leg.exit_price:.5f}" if leg.exit_price else "open",
            leg.pnl,
            leg.status.value,
        )

    def append_trade_csv(self, trade_data: dict):
        """Append completed trade cluster or leg record to human-readable CSV (safe fail-soft)."""
        try:
            path = Path(self.trade_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not path.exists()
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=trade_data.keys())
                if write_header:
                    writer.writeheader()
                writer.writerow(trade_data)
        except Exception as e:
            log.warning("Non-critical: could not write trade to CSV (file may be open in Excel): %s", e)

    def close(self):
        """No-op close for zero-DB architecture."""
        pass
