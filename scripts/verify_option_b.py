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

trades = []
weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(leg.open_time)
            trades.append({
                'dt': dt,
                'wday': weekday_names[dt.weekday()],
                'pnl': getattr(leg, 'pnl', 0.0),
                'lot': leg.lot_size,
                'reason': getattr(leg.exit_reason, 'value', str(leg.exit_reason))
            })

print("\n" + "="*75)
print("  OPTION B VERIFICATION: XAUUSD BACKTEST (Jan - Aug 2026)")
print("  Rules: Friday NY Skip (London Only) + Tuesday 1.5% Conservative Risk")
print("="*75)
print(f"  * Initial Balance   : ${res['initial_balance']:,.2f}")
print(f"  * Final Balance     : ${res['final_balance']:,.2f}")
print(f"  * Net Profit (PnL)  : +${res['total_pnl']:,.2f} (+{res['return_pct']}%)")
print(f"  * Total Trades      : {res['total_trades']}")
print(f"  * Win Rate          : {res['win_rate']}% ({res['wins']}W / {res['losses']}L)")
print(f"  * Profit Factor     : {res['profit_factor']}")
print(f"  * Max Drawdown      : {res['max_drawdown_pct']}%")
print(f"  * Expectancy        : ${res.get('expectancy', 'N/A')} per trade")

# Weekday breakdown
w_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'gross_win': 0.0, 'gross_loss': 0.0})
for t in trades:
    w = w_stats[t['wday']]
    w['trades'] += 1
    w['pnl'] += t['pnl']
    if t['pnl'] > 0:
        w['wins'] += 1
        w['gross_win'] += t['pnl']
    elif t['pnl'] < 0:
        w['losses'] += 1
        w['gross_loss'] += abs(t['pnl'])

print("\n" + "-"*75)
print("  DAY OF WEEK PERFORMANCE (OPTION B)")
print("-"*75)
print(f"{'Day':<12} | {'Trades':<6} | {'Wins':<5} | {'Losses':<6} | {'WinRate':<7} | {'Net PnL':<12} | {'Profit Factor'}")
print("-" * 75)
for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
    if day in w_stats:
        st = w_stats[day]
        tr = st['trades']
        wn = st['wins']
        ls = st['losses']
        wr = (wn / tr * 100) if tr else 0.0
        pnl = st['pnl']
        pf = (st['gross_win'] / st['gross_loss']) if st['gross_loss'] > 0 else (999.0 if st['gross_win'] > 0 else 0.0)
        print(f"{day:<12} | {tr:<6} | {wn:<5} | {ls:<6} | {wr:>6.1f}% | ${pnl:>10.2f} | {pf:>6.2f}")

# Monthly breakdown
m_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'gross_win': 0.0, 'gross_loss': 0.0})
for t in trades:
    m_key = t['dt'].strftime('%Y-%m (%b)')
    m = m_stats[m_key]
    m['trades'] += 1
    m['pnl'] += t['pnl']
    if t['pnl'] > 0:
        m['wins'] += 1
        m['gross_win'] += t['pnl']
    elif t['pnl'] < 0:
        m['losses'] += 1
        m['gross_loss'] += abs(t['pnl'])

print("\n" + "-"*75)
print("  MONTHLY PERFORMANCE (OPTION B)")
print("-"*75)
print(f"{'Month':<16} | {'Trades':<6} | {'Wins':<5} | {'WinRate':<7} | {'Net PnL':<12} | {'Profit Factor'}")
print("-" * 65)
for m_key in sorted(m_stats.keys()):
    st = m_stats[m_key]
    tr = st['trades']
    wn = st['wins']
    wr = (wn / tr * 100) if tr else 0.0
    pnl = st['pnl']
    pf = (st['gross_win'] / st['gross_loss']) if st['gross_loss'] > 0 else (999.0 if st['gross_win'] > 0 else 0.0)
    print(f"{m_key:<16} | {tr:<6} | {wn:<5} | {wr:>6.1f}% | ${pnl:>10.2f} | {pf:>6.2f}")
