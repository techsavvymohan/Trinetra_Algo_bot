import sys, os, json
from datetime import datetime
from collections import defaultdict
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
res = engine.run(raw_data)

june_july_trades = []
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(leg.open_time)
            if dt.month in (6, 7):
                june_july_trades.append({
                    'month': dt.month,
                    'dt': dt.strftime('%Y-%m-%d %H:%M'),
                    'direction': leg.direction.value,
                    'entry': leg.entry_price,
                    'exit': leg.exit_price,
                    'pnl': getattr(leg, 'pnl', 0.0),
                    'lot': leg.lot_size,
                    'reason': getattr(leg.exit_reason, 'value', str(leg.exit_reason)),
                    'cluster_bars': getattr(leg, 'cluster_bars', 0),
                })

print(f"Total June/July trades: {len(june_july_trades)}")
losses = [t for t in june_july_trades if t['pnl'] < -0.01]
wins = [t for t in june_july_trades if t['pnl'] > 0.01]
print(f"Wins: {len(wins)} | Losses: {len(losses)} | WinRate: {len(wins)/len(june_july_trades)*100:.1f}%")

loss_reasons = defaultdict(int)
win_reasons = defaultdict(int)
for t in losses:
    loss_reasons[t['reason']] += 1
for t in wins:
    win_reasons[t['reason']] += 1

print("\nLoss Reasons in June/July:")
for r, cnt in sorted(loss_reasons.items(), key=lambda x: -x[1]):
    print(f"  {r}: {cnt} ({cnt/len(losses)*100:.1f}%)")

print("\nWin Reasons in June/July:")
for r, cnt in sorted(win_reasons.items(), key=lambda x: -x[1]):
    print(f"  {r}: {cnt} ({cnt/len(wins)*100:.1f}%)")

print("\nInspect Top 10 Losses in June/July:")
for t in sorted(losses, key=lambda x: x['pnl'])[:10]:
    print(f"  {t['dt']} | {t['direction']} | Entry={t['entry']:.2f} | Exit={t['exit']:.2f} | PnL=${t['pnl']:.2f} | Reason={t['reason']}")
