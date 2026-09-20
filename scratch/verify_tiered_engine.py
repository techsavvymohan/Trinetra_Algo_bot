import json
import sys, os
from datetime import datetime
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, TradeStatus

with open("data/genuine_jan_aug_2026_xauusd.json") as f:
    data_xau = json.load(f)

cfg = Config.load()
cfg.trading.symbol = "XAUUSD"
cfg.trading.symbols = ["XAUUSD"]

print(f"Conviction Scale A+: {cfg.trading.conviction_scale_a_plus}")
print(f"Conviction Scale A:  {cfg.trading.conviction_scale_a}")
print(f"NY Core Only for A+: {cfg.trading.xau_a_plus_ny_core_only}")
print(f"Block H1 Bullish:    {cfg.trading.xau_a_plus_block_h1_bullish}")

eng = BacktestEngine(cfg, 10000.0, "XAUUSD")
res = eng.run(data_xau)

trades = []
for c in eng._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
            pnl = getattr(leg, "pnl", 0.0) or 0.0
            grade = getattr(leg, "_signal_grade", SignalGrade.A)
            trades.append({
                "open_time": leg.open_time,
                "close_time": leg.close_time or leg.open_time,
                "direction": leg.direction.value,
                "pnl": pnl,
                "grade": grade.value if hasattr(grade, "value") else str(grade),
                "lot_size": leg.lot_size,
            })

n = len(trades)
wins = [t["pnl"] for t in trades if t["pnl"] > 0]
losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
total_pnl = sum(t["pnl"] for t in trades)
wr = len(wins) / n * 100 if n else 0
gross_win = sum(wins)
gross_loss = sum(losses)
pf = gross_win / gross_loss if gross_loss > 0 else 999.0

# Max DD
sorted_t = sorted(trades, key=lambda x: x["close_time"])
peak = 10000.0
eq = 10000.0
max_dd = 0.0
max_dd_pct = 0.0
for t in sorted_t:
    eq += t["pnl"]
    if eq > peak:
        peak = eq
    dd = peak - eq
    dd_pct = (dd / peak) * 100 if peak > 0 else 0
    if dd > max_dd:
        max_dd = dd
    if dd_pct > max_dd_pct:
        max_dd_pct = dd_pct

roi = (total_pnl / 10000.0) * 100

grades_count = {}
for t in trades:
    g = t["grade"]
    grades_count[g] = grades_count.get(g, 0) + 1

print("\n" + "=" * 70)
print("  VERIFIED TIERED CONVICTION BACKTEST RESULTS (Jan - Aug 2026)")
print("=" * 70)
print(f"  Total Trades:     {n}")
print(f"  Trades by Grade:  {grades_count}")
print(f"  Win Rate:         {wr:.2f}% ({len(wins)}W / {len(losses)}L)")
print(f"  Net Profit:       ${total_pnl:,.2f} (ROI: +{roi:.1f}%)")
print(f"  Profit Factor:    {pf:.2f}")
print(f"  Max Drawdown:     ${max_dd:,.2f} ({max_dd_pct:.2f}%)")

# Breakdown by Grade
for g in ["A+", "A"]:
    sub = [t for t in trades if t["grade"] == g]
    if sub:
        sub_wins = [t["pnl"] for t in sub if t["pnl"] > 0]
        sub_losses = [abs(t["pnl"]) for t in sub if t["pnl"] < 0]
        sub_wr = len(sub_wins) / len(sub) * 100
        sub_pnl = sum(t["pnl"] for t in sub)
        sub_pf = sum(sub_wins) / sum(sub_losses) if sub_losses else 99.0
        print(f"\n  Grade {g}:")
        print(f"    Trades: {len(sub)} | WR: {sub_wr:.1f}% | Net PnL: ${sub_pnl:,.2f} | PF: {sub_pf:.2f} | Avg Lot: {np.mean([t['lot_size'] for t in sub]):.2f}")
