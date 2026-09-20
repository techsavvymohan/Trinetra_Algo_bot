import sys, os, json
from datetime import datetime
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(".").resolve()
sys.path.insert(0, str(BASE_DIR))

from scripts.backtest_full_year_2026 import merge_three_datasets, extract_trades, compute_stats, START_DATE, END_DATE
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

xau_data = merge_three_datasets(
    "data/genuine_jan_aug_2026_xauusd.json",
    "data/native_true_jun_sep_xauusd.json",
    "data/fetched_18sep2026_xauusd.json"
)

def run_xau(cutoff_h):
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = 10000.0
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0
    cfg.trading.xau_session_cutoff_hour = cutoff_h

    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD", start_date=START_DATE, end_date=END_DATE)
    res = engine.run(xau_data)
    trades = extract_trades(engine, "XAUUSD")

    by_m = defaultdict(list)
    for t in trades:
        m = t["open_time"].strftime("%Y-%m")
        by_m[m].append(t)

    print(f"\n================ CUTOFF HOUR = {cutoff_h} ================")
    print(f"Total: {len(trades)} trades | PnL=${res.get('total_pnl', 0.0):.2f} | WR={res.get('win_rate', 0.0):.1f}% | DD={res.get('max_drawdown_pct', 0.0):.2f}%")
    for m in sorted(by_m.keys()):
        s = compute_stats(by_m[m])
        print(f"  {m}: ${s['net_pnl']:>9.2f} | {s['trades']:>3} trades | {s['wins']}W/{s['losses']}L | WR={s['win_rate']:>5.1f}%")

if __name__ == "__main__":
    run_xau(24)
