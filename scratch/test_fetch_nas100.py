import sys
from datetime import datetime, timezone
from pathlib import Path
try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 not installed")
    sys.exit(1)

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
from xauusd_bot.config import Config

cfg = Config()
mt5_cfg = cfg.mt5
init_kwargs = {}
if mt5_cfg.path and Path(mt5_cfg.path).exists():
    init_kwargs["path"] = mt5_cfg.path
if mt5_cfg.login:
    init_kwargs["login"] = mt5_cfg.login
if mt5_cfg.password:
    init_kwargs["password"] = mt5_cfg.password
if mt5_cfg.server:
    init_kwargs["server"] = mt5_cfg.server

if not mt5.initialize(**init_kwargs):
    if not mt5.initialize():
        print(f"Failed to initialize MT5: {mt5.last_error()}")
        sys.exit(1)

acc = mt5.account_info()
print(f"Connected to MT5: Login {acc.login}, Server {acc.server}")

symbol = "USTECH100M"
if not mt5.symbol_select(symbol, True):
    print(f"Failed to select {symbol}")
    # try other common symbols
    for s in ["NAS100", "US100", "USTEC", "NQ", "USTECH"]:
        if mt5.symbol_select(s, True):
            symbol = s
            print(f"Found alternative: {symbol}")
            break

months = [
    (datetime(2026, 1, 1), datetime(2026, 2, 1), "Jan 2026"),
    (datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb 2026"),
    (datetime(2026, 3, 1), datetime(2026, 4, 1), "Mar 2026"),
    (datetime(2026, 4, 1), datetime(2026, 5, 1), "Apr 2026"),
    (datetime(2026, 5, 1), datetime(2026, 6, 1), "May 2026"),
    (datetime(2026, 6, 1), datetime(2026, 7, 1), "Jun 2026"),
    (datetime(2026, 7, 1), datetime(2026, 8, 1), "Jul 2026"),
    (datetime(2026, 8, 1), datetime(2026, 8, 19), "Aug 2026"),
]

for d1, d2, label in months:
    r = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, d1, d2)
    if r is not None and len(r) > 0:
        t_start = datetime.fromtimestamp(r[0]["time"], tz=timezone.utc)
        t_end = datetime.fromtimestamp(r[-1]["time"], tz=timezone.utc)
        print(f"  [OK] {label}: {len(r):>5} M1 bars | {t_start.strftime('%Y-%m-%d')} -> {t_end.strftime('%Y-%m-%d')}")
    else:
        print(f"  [FAIL] {label}: 0 bars returned (err: {mt5.last_error()})")








mt5.shutdown()
