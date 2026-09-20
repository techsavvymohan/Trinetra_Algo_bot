import sys, os, json
from datetime import datetime
from pathlib import Path
import bisect

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection

with open('data/genuine_jan_aug_2026_xauusd.json', 'r') as f:
    raw_data = json.load(f)

h1 = raw_data['H1']
h1_times = [datetime.fromisoformat(t) if isinstance(t, str) else t for t in h1['time']]
h1_closes = h1['close']

def get_h1_emadiff(dt):
    idx = bisect.bisect_right(h1_times, dt) - 1
    if idx < 50:
        return 0.0, 0.0, None
    cl = h1_closes[max(0, idx-60):idx+1]
    k9 = 2.0 / 10.0
    k50 = 2.0 / 51.0
    e9 = e50 = cl[0]
    for p in cl[1:]:
        e9 = p * k9 + e9 * (1 - k9)
        e50 = p * k50 + e50 * (1 - k50)
    d = TradeDirection.BUY if e9 > e50 else TradeDirection.SELL
    return e9, e50, d

cfg = Config.load()
cfg.trading.backtest_initial_balance = 10000.0
cfg.trading.backtest_apply_friction = True
cfg.trading.backtest_commission_per_lot = 6.0
engine = BacktestEngine(cfg, initial_balance=10000.0, symbol='XAUUSD')
engine.run(raw_data)

def is_london(dt):
    h, m = dt.hour, dt.minute
    return (h == 7 and m >= 45) or (8 <= h < 10) or (h == 10 and m <= 30)

print(f"{'Date/Time':<17} {'Dir':<5} {'H1_Dir':<7} {'H1_e9':>8} {'H1_e50':>8} {'Entry':>8} {'SL':>8} {'PnL':>9} {'Reason'}")
print("-" * 85)
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if is_london(dt) and dt.month in (6, 7):
                e9, e50, h1_d = get_h1_emadiff(dt)
                pnl = getattr(leg, 'pnl', 0.0) or 0.0
                reason = getattr(leg.exit_reason, 'value', str(leg.exit_reason))
                print(f"{dt.strftime('%Y-%m-%d %H:%M'):<17} {leg.direction.value:<5} {str(h1_d.value if h1_d else 'None'):<7} {e9:>8.1f} {e50:>8.1f} {leg.entry_price:>8.2f} {leg.sl_price:>8.2f} ${pnl:>8.2f} {reason}")
