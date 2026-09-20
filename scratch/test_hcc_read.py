# pyrefly: ignore [missing-import]
import MetaTrader5 as mt5
from datetime import datetime, timezone

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error())
    exit(1)

symbol = "USTECH100M"
# Check symbol info and chart
info = mt5.symbol_info(symbol)
print(f"Symbol {symbol}: visible={info.visible}, select={mt5.symbol_select(symbol, True)}")

# Check terminal info
term = mt5.terminal_info()
print(f"Terminal build: {term.build}, connected: {term.connected}, maxbars: {getattr(term, 'maxbars', 'N/A')}")

# Try copy_rates_range with datetime in local time vs UTC
for dt1, dt2 in [
    (datetime(2026, 1, 5, 10, 0), datetime(2026, 1, 5, 20, 0)),
    (datetime(2026, 2, 5, 10, 0), datetime(2026, 2, 5, 20, 0)),
    (datetime(2026, 3, 5, 10, 0), datetime(2026, 3, 5, 20, 0)),
    (datetime(2026, 4, 5, 10, 0), datetime(2026, 4, 5, 20, 0)),
    (datetime(2026, 5, 5, 10, 0), datetime(2026, 5, 5, 20, 0)),
    (datetime(2026, 6, 15, 10, 0), datetime(2026, 6, 15, 20, 0)),
]:
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, dt1, dt2)
    print(f"Range {dt1.date()}: {len(rates) if rates is not None else 0} bars, err: {mt5.last_error()}")

mt5.shutdown()
