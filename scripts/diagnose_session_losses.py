"""Find WHICH session (London vs NY) generates June/July losses"""
import sys, json
from datetime import datetime
from pathlib import Path
BASE_DIR = Path(r"e:/XAUUSD digger bot")
sys.path.insert(0, str(BASE_DIR))
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection

with open(r"e:/XAUUSD digger bot/data/genuine_jan_aug_2026_xauusd.json") as f:
    raw_data = json.load(f)

cfg = Config.load()
cfg.trading.backtest_initial_balance = 10000.0
cfg.trading.backtest_apply_friction = True
cfg.trading.backtest_commission_per_lot = 6.0
engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
engine.run(raw_data)

NAMES = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",7:"Jul",8:"Aug"}

# London: 07:45-10:30 UTC, NY: 13:30-16:30 UTC
def get_session(dt):
    h, m = dt.hour, dt.minute
    if (h == 7 and m >= 45) or (8 <= h < 10) or (h == 10 and m <= 30):
        return "LONDON"
    elif (h == 13 and m >= 30) or (14 <= h < 16) or (h == 16 and m <= 30):
        return "NY"
    return "OTHER"

print("\n" + "="*95)
print("SESSION-LEVEL BREAKDOWN (London vs NY) by Month")
print("="*95)
print(f"{'Month':<6} {'LON_W':>6} {'LON_L':>6} {'LON_Net':>10} | {'NY_W':>6} {'NY_L':>6} {'NY_Net':>10} | {'Verdict'}")
print("-"*95)

for m in range(1, 9):
    lon = {"wins": 0, "losses": 0, "net": 0.0}
    ny  = {"wins": 0, "losses": 0, "net": 0.0}
    oth = {"wins": 0, "losses": 0, "net": 0.0}

    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                if dt.month != m:
                    continue
                pnl = getattr(leg, "pnl", 0.0) or 0.0
                sess = get_session(dt)
                bucket = lon if sess == "LONDON" else (ny if sess == "NY" else oth)
                bucket["net"] += pnl
                if pnl > 0.01:
                    bucket["wins"] += 1
                elif pnl < -0.01:
                    bucket["losses"] += 1

    lon_prob = "OK" if lon["net"] >= 0 else "BAD"
    ny_prob  = "OK" if ny["net"] >= 0 else "BAD"
    verdict = "LON problem" if lon["net"] < -100 else ("NY problem" if ny["net"] < -100 else "Both OK")
    print(f"{NAMES[m]:<6} {lon['wins']:>6} {lon['losses']:>6} ${lon['net']:>9.2f} [{lon_prob}] | "
          f"{ny['wins']:>6} {ny['losses']:>6} ${ny['net']:>9.2f} [{ny_prob}] | {verdict}")

print("="*95)
