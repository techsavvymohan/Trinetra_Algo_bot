import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

with open("data/genuine_jan_aug_2026_nas100.json") as f:
    data_nas = json.load(f)

cfg = Config.load()
cfg.trading.symbol = "USTECH100M"
cfg.trading.symbols = ["USTECH100M"]

print("Config for NAS:")
print("  nas_session_start_hour:", getattr(cfg.trading, "nas_session_start_hour", None))
print("  nas_session_start_minute:", getattr(cfg.trading, "nas_session_start_minute", None))
print("  nas_session_end_hour:", getattr(cfg.trading, "nas_session_end_hour", None))
print("  strategy_trigger_type:", getattr(cfg.trading, "strategy_trigger_type", None))
print("  xau_ecosystem_mode:", getattr(cfg.trading, "xau_ecosystem_mode", None))
print("  tuesday_trade_enabled:", getattr(cfg.trading, "tuesday_trade_enabled", None))

# Let's inspect where trades happened
engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M")
res = engine.run(data_nas)

trades = []
for c in engine._clusters:
    for leg in c.legs:
        trades.append((leg.open_time, leg.direction, leg.entry_price, leg.exit_price, leg.pnl))

print(f"Total trades: {len(trades)}")
trades_by_month = defaultdict(list)
for t in trades:
    dt = t[0] if isinstance(t[0], datetime) else datetime.fromisoformat(str(t[0]))
    trades_by_month[dt.strftime("%Y-%m")].append(t)

for m in sorted(trades_by_month.keys()):
    print(f"  {m}: {len(trades_by_month[m])} trades")
    for tr in trades_by_month[m][:5]:
        print(f"    {tr[0]} dir={tr[1]} entry={tr[2]} exit={tr[3]} pnl={tr[4]}")
