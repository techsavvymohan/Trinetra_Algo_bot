"""Diagnostic script to analyze the 167 NAS100 trades from Jan 1 to Sep 18, 2026.

Analyzes:
1. Hourly win rate & PnL (US Open 13:30-15:00 vs Midday 15:00-18:00 vs Late 18:00-20:00)
2. Directional performance (BUY vs SELL)
3. Exit reasons breakdown (SL, TP, Stagnation, etc.)
4. Trade duration / holding time
5. Average Win vs Average Loss (Risk/Reward realized)
6. Impact of H1 / H4 trend alignment
"""
import os
import sys
import json
from collections import defaultdict
from datetime import datetime, timezone
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus
from scratch.run_combined_xau_nas_full_backtest import load_stitched_nas100, extract_trades

def analyze_nas():
    data_nas = load_stitched_nas100()

    cfg_nas = Config.load()
    cfg_nas.trading.symbol = "USTECH100M"
    cfg_nas.trading.symbols = ["USTECH100M"]
    cfg_nas.trading.backtest_apply_friction = True
    cfg_nas.trading.backtest_commission_per_lot = 6.0

    eng_nas = BacktestEngine(cfg_nas, initial_balance=10000.0, symbol="USTECH100M")
    res_nas = eng_nas.run(data_nas)
    trades = extract_trades(eng_nas, "USTECH100M")

    print("\n" + "="*80)
    print(f"  NAS100 DEEP LOSS & MICROSTRUCTURE AUDIT ({len(trades)} TRADES)")
    print("="*80)

    # 1. Basic Stats
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    bes = [t for t in trades if abs(t["pnl"]) <= 0.01]

    tot_pnl = sum(t["pnl"] for t in trades)
    tot_win_pnl = sum(t["pnl"] for t in wins)
    tot_loss_pnl = sum(t["pnl"] for t in losses)
    avg_win = tot_win_pnl / len(wins) if wins else 0.0
    avg_loss = abs(tot_loss_pnl / len(losses)) if losses else 0.0

    print(f"  Total Trades : {len(trades)}")
    print(f"  Win Rate     : {len(wins)/len(trades)*100:.1f}% ({len(wins)}W / {len(losses)}L / {len(bes)}BE)")
    print(f"  Total PnL    : ${tot_pnl:,.2f}")
    print(f"  Gross Profit : ${tot_win_pnl:,.2f}")
    print(f"  Gross Loss   : ${tot_loss_pnl:,.2f}")
    print(f"  Avg Win      : ${avg_win:,.2f}")
    print(f"  Avg Loss     : ${avg_loss:,.2f}")
    print(f"  Payoff Ratio : {avg_win / avg_loss:.2f} (Avg Win / Avg Loss)")
    print(f"  Profit Factor: {tot_win_pnl / abs(tot_loss_pnl):.2f}")

    # 2. Hourly Breakdown
    print("\n" + "-"*80)
    print("  1. PERFORMANCE BY ENTRY HOUR (UTC)")
    print("-"*80)
    hourly = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        h = t["open_time"].hour
        hourly[h]["trades"] += 1
        if t["pnl"] > 0:
            hourly[h]["wins"] += 1
        hourly[h]["pnl"] += t["pnl"]

    for h in sorted(hourly.keys()):
        st = hourly[h]
        wr = (st["wins"] / st["trades"] * 100) if st["trades"] else 0.0
        print(f"  Hour {h:02d}:00 UTC | Trades: {st['trades']:2d} | Wins: {st['wins']:2d} | Win Rate: {wr:5.1f}% | Net PnL: ${st['pnl']:>8.2f}")

    # 3. Exit Reasons Breakdown
    print("\n" + "-"*80)
    print("  2. PERFORMANCE BY EXIT REASON")
    print("-"*80)
    exit_reasons = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for t in trades:
        r = t.get("exit_reason", "UNKNOWN")
        exit_reasons[r]["count"] += 1
        exit_reasons[r]["pnl"] += t["pnl"]

    for r, st in sorted(exit_reasons.items(), key=lambda x: x[1]["pnl"], reverse=True):
        print(f"  {r:<30} | Trades: {st['count']:3d} | Net PnL: ${st['pnl']:>9.2f}")

    # 4. Day of Week Breakdown
    print("\n" + "-"*80)
    print("  3. PERFORMANCE BY DAY OF WEEK")
    print("-"*80)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    day_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        d = days[t["open_time"].weekday()]
        day_stats[d]["trades"] += 1
        if t["pnl"] > 0:
            day_stats[d]["wins"] += 1
        day_stats[d]["pnl"] += t["pnl"]

    for d in days:
        st = day_stats[d]
        wr = (st["wins"] / st["trades"] * 100) if st["trades"] else 0.0
        print(f"  {d:<5} | Trades: {st['trades']:2d} | Wins: {st['wins']:2d} | Win Rate: {wr:5.1f}% | Net PnL: ${st['pnl']:>8.2f}")

if __name__ == "__main__":
    analyze_nas()
