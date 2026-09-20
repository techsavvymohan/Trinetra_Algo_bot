import sys
from pathlib import Path
try:
    from tvDatafeed import TvDatafeed, Interval
    print("tvDatafeed is installed")
except ImportError:
    print("tvDatafeed is NOT installed")
    sys.exit(1)

tv = TvDatafeed()
for sym, exch in [("NDX", "NASDAQ"), ("NAS100", "CAPITALCOM"), ("US100", "FOREXCOM"), ("QQQ", "NASDAQ")]:
    try:
        df = tv.get_hist(sym, exch, interval=Interval.in_1_minute, n_bars=10000)
        if df is not None and not df.empty:
            print(f"TradingView {sym} on {exch}: {len(df)} M1 bars | {df.index[0]} -> {df.index[-1]}")
        else:
            print(f"TradingView {sym} on {exch}: Empty or None")
    except Exception as e:
        print(f"TradingView {sym} on {exch}: Error {e}")
