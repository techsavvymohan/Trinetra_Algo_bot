import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import json
from datetime import datetime
from collections import defaultdict
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
res = engine.run(raw_data)

weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

tuesday_trades = []
friday_trades = []

for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(leg.open_time)
            w_day = weekday_names[dt.weekday()]
            trade_info = {
                'open_time': dt.strftime('%Y-%m-%d %H:%M'),
                'direction': leg.direction.value,
                'entry': leg.entry_price,
                'exit': leg.exit_price,
                'pnl': getattr(leg, 'pnl', 0.0),
                'reason': getattr(leg.exit_reason, 'value', str(leg.exit_reason)),
                'hour': dt.hour,
            }
            if w_day == 'Tuesday':
                tuesday_trades.append(trade_info)
            elif w_day == 'Friday':
                friday_trades.append(trade_info)

print(f"Total Tuesday trades: {len(tuesday_trades)}")
tue_loss = [t for t in tuesday_trades if t['pnl'] < 0]
print(f"Tuesday losses: {len(tue_loss)} trades, Total loss: ${sum(t['pnl'] for t in tue_loss):.2f}")
tue_hours = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0})
for t in tuesday_trades:
    h = t['hour']
    tue_hours[h]['count'] += 1
    tue_hours[h]['pnl'] += t['pnl']
    if t['pnl'] > 0:
        tue_hours[h]['wins'] += 1
    elif t['pnl'] < 0:
        tue_hours[h]['losses'] += 1

print("\nTuesday by Hour (UTC):")
print(f"{'Hour (UTC)':<12} | {'Trades':<6} | {'Wins':<5} | {'Losses':<6} | {'Net PnL':<12}")
print("-" * 50)
for h in sorted(tue_hours.keys()):
    st = tue_hours[h]
    print(f"{h:02d}:00 UTC    | {st['count']:<6} | {st['wins']:<5} | {st['losses']:<6} | ${st['pnl']:>10.2f}")

print(f"\nTotal Friday trades: {len(friday_trades)}")
fri_loss = [t for t in friday_trades if t['pnl'] < 0]
print(f"Friday losses: {len(fri_loss)} trades, Total loss: ${sum(t['pnl'] for t in fri_loss):.2f}")
fri_hours = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0})
for t in friday_trades:
    h = t['hour']
    fri_hours[h]['count'] += 1
    fri_hours[h]['pnl'] += t['pnl']
    if t['pnl'] > 0:
        fri_hours[h]['wins'] += 1
    elif t['pnl'] < 0:
        fri_hours[h]['losses'] += 1

print("\nFriday by Hour (UTC):")
print(f"{'Hour (UTC)':<12} | {'Trades':<6} | {'Wins':<5} | {'Losses':<6} | {'Net PnL':<12}")
print("-" * 50)
for h in sorted(fri_hours.keys()):
    st = fri_hours[h]
    print(f"{h:02d}:00 UTC    | {st['count']:<6} | {st['wins']:<5} | {st['losses']:<6} | ${st['pnl']:>10.2f}")
