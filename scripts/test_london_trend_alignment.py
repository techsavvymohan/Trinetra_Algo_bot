import sys, os, json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, Bias, TradeDirection

with open('data/genuine_jan_aug_2026_xauusd.json', 'r') as f:
    raw_data = json.load(f)

# Slices of H1
h1 = raw_data['H1']
h1_times = [datetime.fromisoformat(t) if isinstance(t, str) else t for t in h1['time']]
h1_closes = h1['close']

def get_h1_dir_at(dt):
    # Find last closed H1 bar before dt
    import bisect
    idx = bisect.bisect_right(h1_times, dt) - 1
    if idx < 50:
        return None
    # 9 and 50 EMA on H1 close
    cl = h1_closes[max(0, idx-60):idx+1]
    k9 = 2.0 / 10.0
    k50 = 2.0 / 51.0
    e9 = e50 = cl[0]
    for p in cl[1:]:
        e9 = p * k9 + e9 * (1 - k9)
        e50 = p * k50 + e50 * (1 - k50)
    if e9 > e50:
        return TradeDirection.BUY
    elif e9 < e50:
        return TradeDirection.SELL
    return None

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
                h1_dir = get_h1_dir_at(dt)
                aligned = (leg.direction == h1_dir)
                pnl = getattr(leg, 'pnl', 0.0) or 0.0
                lon_trades.append({
                    'month': dt.month,
                    'dt': dt,
                    'dir': leg.direction,
                    'h1_dir': h1_dir,
                    'aligned': aligned,
                    'pnl': pnl,
                    'is_win': pnl > 0.01,
                })

print(f"Total London trades: {len(lon_trades)}")

aligned_trades = [t for t in lon_trades if t['aligned']]
counter_trades = [t for t in lon_trades if not t['aligned']]

print("\n" + "="*80)
print("LONDON PERFORMANCE: H1 TREND ALIGNED vs COUNTER-TREND")
print("="*80)
for label, group in [("H1 Aligned (With-Trend)", aligned_trades), ("H1 Counter-Trend / Neutral", counter_trades)]:
    w = [t for t in group if t['is_win']]
    l = [t for t in group if not t['is_win']]
    net = sum(t['pnl'] for t in group)
    wr = len(w)/len(group)*100 if group else 0
    print(f"{label:<30} Trades={len(group):<4} Wins={len(w):<4} Loss={len(l):<4} WinRate={wr:>6.1f}% NetPnL=${net:>10.2f}")

print("\n" + "="*80)
print("JUNE & JULY BREAKDOWN:")
print("="*80)
for m in (6, 7):
    m_name = "June" if m == 6 else "July"
    m_aligned = [t for t in aligned_trades if t['month'] == m]
    m_counter = [t for t in counter_trades if t['month'] == m]
    
    w_al = [t for t in m_aligned if t['is_win']]
    net_al = sum(t['pnl'] for t in m_aligned)
    wr_al = len(w_al)/len(m_aligned)*100 if m_aligned else 0
    
    w_co = [t for t in m_counter if t['is_win']]
    net_co = sum(t['pnl'] for t in m_counter)
    wr_co = len(w_co)/len(m_counter)*100 if m_counter else 0
    
    print(f"{m_name} H1-Aligned: Trades={len(m_aligned):<3} Wins={len(w_al):<3} WR={wr_al:>5.1f}% NetPnL=${net_al:>9.2f}")
    print(f"{m_name} Counter-Tr : Trades={len(m_counter):<3} Wins={len(w_co):<3} WR={wr_co:>5.1f}% NetPnL=${net_co:>9.2f}")
