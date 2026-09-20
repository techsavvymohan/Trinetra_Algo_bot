import sys, os, json
from datetime import datetime
from pathlib import Path

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

m1 = raw_data['M1']
times = [datetime.fromisoformat(t) if isinstance(t, str) else t for t in m1['time']]
highs = m1['high']
lows = m1['low']
closes = m1['close']

# Function to get Asian session (00:00 to 06:00 UTC) range for a given date
def get_asian_range(trade_date):
    ash_h = []
    ash_l = []
    for t, h, l in zip(times, highs, lows):
        if t.date() == trade_date.date() and 0 <= t.hour < 6:
            ash_h.append(h)
            ash_l.append(l)
    if ash_h and ash_l:
        return max(ash_h) - min(ash_l), max(ash_h), min(ash_l)
    return 0.0, 0.0, 0.0

lon_trades = []
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if is_london(dt):
                rng, ah, al = get_asian_range(dt)
                pnl = getattr(leg, 'pnl', 0.0) or 0.0
                lon_trades.append({
                    'month': dt.month,
                    'dt': dt,
                    'dir': leg.direction.value,
                    'pnl': pnl,
                    'is_win': pnl > 0.01,
                    'asian_range': rng,
                    'asian_high': ah,
                    'asian_low': al,
                    'entry': leg.entry_price,
                    'sl_dist': abs(leg.entry_price - leg.sl_price),
                })

print(f"Total London trades analyzed: {len(lon_trades)}")

# Compare Asian Range between Wins and Losses
wins = [t for t in lon_trades if t['is_win']]
losses = [t for t in lon_trades if not t['is_win']]

avg_rng_win = sum(t['asian_range'] for t in wins)/len(wins) if wins else 0
avg_rng_loss = sum(t['asian_range'] for t in losses)/len(losses) if losses else 0
print(f"Avg Asian Range for Wins  : ${avg_rng_win:.2f}")
print(f"Avg Asian Range for Losses: ${avg_rng_loss:.2f}")

print("\nAsian Range by Month (Wins vs Losses):")
print(f"{'Month':<6} {'Win_Count':<10} {'AvgRng_Win':>12} {'Loss_Count':<11} {'AvgRng_Loss':>12}")
print("-" * 60)
NAMES = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',7:'Jul',8:'Aug'}
for m in range(1, 9):
    m_w = [t for t in wins if t['month'] == m]
    m_l = [t for t in losses if t['month'] == m]
    rw = sum(t['asian_range'] for t in m_w)/len(m_w) if m_w else 0
    rl = sum(t['asian_range'] for t in m_l)/len(m_l) if m_l else 0
    print(f"{NAMES[m]:<6} {len(m_w):<10} ${rw:>11.2f} {len(m_l):<11} ${rl:>11.2f}")

# Asian range buckets
print("\nPerformance by Asian Range Bucket:")
print(f"{'Bucket':<15} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'WinRate':>8} {'Net PnL':>12}")
print("-" * 60)
buckets = [
    ("< $10 (Tight)", lambda r: r < 10.0),
    ("$10 - $20", lambda r: 10.0 <= r < 20.0),
    ("$20 - $30", lambda r: 20.0 <= r < 30.0),
    ("$30 - $40", lambda r: 30.0 <= r < 40.0),
    ("> $40 (Blown)", lambda r: r >= 40.0),
]
for b_name, b_fn in buckets:
    bt = [t for t in lon_trades if b_fn(t['asian_range'])]
    bw = [t for t in bt if t['is_win']]
    bl = [t for t in bt if not t['is_win']]
    wr = len(bw)/len(bt)*100 if bt else 0
    net = sum(t['pnl'] for t in bt)
    print(f"{b_name:<15} {len(bt):<8} {len(bw):<6} {len(bl):<6} {wr:>7.1f}% ${net:>11.2f}")
