import sys, os, json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

with open('data/genuine_jan_aug_2026_xauusd.json', 'r') as f:
    raw_data = json.load(f)

cfg = Config.load()
cfg.trading.backtest_initial_balance = 10000.0
cfg.trading.backtest_apply_friction = True
cfg.trading.backtest_commission_per_lot = 6.0

engine = BacktestEngine(cfg, initial_balance=10000.0, symbol='XAUUSD')
engine.run(raw_data)

def is_london(dt):
    h, m = dt.hour, dt.minute
    return (h == 7 and m >= 45) or (8 <= h < 10) or (h == 10 and m <= 30)

lon_trades = []
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if is_london(dt):
                lon_trades.append({
                    'month': dt.month,
                    'dt': dt,
                    'dir': leg.direction.value,
                    'pnl': getattr(leg, 'pnl', 0.0) or 0.0,
                    'entry': leg.entry_price,
                    'sl': leg.sl_price,
                    'tp': leg.tp_price,
                    'exit': leg.exit_price,
                    'reason': getattr(leg.exit_reason, 'value', str(leg.exit_reason)),
                    'lot': leg.lot_size,
                })

print(f"Total London trades: {len(lon_trades)}")
print("\n" + "="*80)
print(f"{'Month':<6} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'WinRate':>8} {'Net PnL':>12}")
print("="*80)
NAMES = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',7:'Jul',8:'Aug'}
for m in range(1, 9):
    mt = [t for t in lon_trades if t['month'] == m]
    w = [t for t in mt if t['pnl'] > 0.01]
    l = [t for t in mt if t['pnl'] < -0.01]
    wr = len(w)/len(mt)*100 if mt else 0
    net = sum(t['pnl'] for t in mt)
    print(f"{NAMES[m]:<6} {len(mt):<8} {len(w):<6} {len(l):<6} {wr:>7.1f}% ${net:>11.2f}")

print("\n" + "="*80)
print("INSPECT ALL LOSING LONDON TRADES IN JUNE & JULY:")
print("="*80)
print(f"{'Date/Time':<17} {'Dir':<5} {'Entry':>8} {'SL':>8} {'TP':>8} {'Exit':>8} {'PnL':>10} {'Reason'}")
print("-"*80)
for t in lon_trades:
    if t['month'] in (6, 7) and t['pnl'] < -0.01:
        print(f"{t['dt'].strftime('%Y-%m-%d %H:%M'):<17} {t['dir']:<5} {t['entry']:>8.2f} {t['sl']:>8.2f} {t['tp']:>8.2f} {t['exit']:>8.2f} ${t['pnl']:>9.2f} {t['reason']}")
