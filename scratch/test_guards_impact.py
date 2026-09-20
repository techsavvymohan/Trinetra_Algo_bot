import sys, json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(".").resolve()
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

SEP_START = datetime(2026, 9, 1, tzinfo=timezone.utc)
SEP_END   = datetime(2026, 9, 19, 23, 59, 59, tzinfo=timezone.utc)

# Load sep data
with open("data/native_true_jun_sep_xauusd.json") as f: base = json.load(f)
with open("data/fetched_18sep2026_xauusd.json") as f: overlay = json.load(f)
sep_data = {}
for tf in set(list(base.keys()) + list(overlay.keys())):
    bd = base.get(tf, {})
    od = overlay.get(tf, {})
    combined = {}
    for i, t in enumerate(bd.get("time", [])):
        bar = {k: bd[k][i] for k in bd if k != "tf" and isinstance(bd[k], list)}
        bar["time"] = t; combined[t] = bar
    for i, t in enumerate(od.get("time", [])):
        bar = {k: od[k][i] for k in od if k != "tf" and isinstance(od[k], list)}
        bar["time"] = t; combined[t] = bar
    sorted_bars = sorted(combined.values(), key=lambda b: b["time"])
    if not sorted_bars:
        sep_data[tf] = bd if bd else od; continue
    keys = [k for k in sorted_bars[0].keys() if k != "time"]
    merged = {"tf": tf, "time": [b["time"] for b in sorted_bars]}
    for k in keys:
        merged[k] = [b.get(k, 0.0) for b in sorted_bars]
    sep_data[tf] = merged

with open("data/genuine_jan_aug_2026_xauusd.json") as f:
    jan_aug_data = json.load(f)

def eval_config(name, cfg_fn):
    print(f"\n--- Testing: {name} ---", flush=True)
    # Sep 1-19
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = 10000.0
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0
    cfg_fn(cfg)
    
    eng_sep = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD", start_date=SEP_START, end_date=SEP_END)
    r_sep = eng_sep.run(sep_data)
    print(f"  Sep 1-19: Trades={r_sep.get('total_trades')} WR={r_sep.get('win_rate'):.1f}% PnL=${r_sep.get('total_pnl'):.2f} MaxDD={r_sep.get('max_drawdown_pct'):.2f}%", flush=True)

    eng_ja = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
    r_ja = eng_ja.run(jan_aug_data)
    print(f"  Jan-Aug:  Trades={r_ja.get('total_trades')} WR={r_ja.get('win_rate'):.1f}% PnL=${r_ja.get('total_pnl'):.2f} MaxDD={r_ja.get('max_drawdown_pct'):.2f}%", flush=True)

# Test 1: Baseline
eval_config("Baseline", lambda c: None)

# Test 2: H4 bias guard
def set_h4(c):
    c.trading.xau_h4_bias_guard = True
eval_config("H4 Bias Guard = True", set_h4)

# Test 3: London Close Wall at 14:00 (instead of 15:45)
def set_wall_14(c):
    c.trading.xau_london_close_cutoff_hour = 14
    c.trading.xau_london_close_cutoff_min = 0
eval_config("London Close Cutoff = 14:00 UTC", set_wall_14)
