import sys
from pathlib import Path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime, timezone
import MetaTrader5 as mt5
from xauusd_bot.config import Config
from xauusd_bot.broker.mt5_connector import MT5Connector

cfg = Config()
connector = MT5Connector(cfg.mt5)
if not connector.connect():
    print("Failed to connect via MT5Connector")
    sys.exit(1)

symbol = "USTECH100M"
mt5.symbol_select(symbol, True)
info = mt5.symbol_info(symbol)
term = mt5.terminal_info()
print(f"Connected! Terminal build: {term.build}, MaxBars: {getattr(term, 'maxbars', 'N/A')}")

for dt1, dt2 in [
    (datetime(2026, 1, 5, 10, 0), datetime(2026, 1, 5, 20, 0)),
    (datetime(2026, 3, 5, 10, 0), datetime(2026, 3, 5, 20, 0)),
    (datetime(2026, 5, 5, 10, 0), datetime(2026, 5, 5, 20, 0)),
    (datetime(2026, 6, 15, 10, 0), datetime(2026, 6, 15, 20, 0)),
]:
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, dt1, dt2)
    print(f"Range {dt1.date()}: {len(rates) if rates is not None else 0} bars")

mt5.shutdown()
