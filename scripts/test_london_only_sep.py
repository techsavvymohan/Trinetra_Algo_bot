import sys, json
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(".").resolve()
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

SEP_START = datetime(2026, 9, 1, tzinfo=timezone.utc)
SEP_END   = datetime(2026, 9, 19, 23, 59, 59, tzinfo=timezone.utc)

with open("data/native_true_jun_sep_xauusd.json") as f: base = json.load(f)
with open("data/fetched_18sep2026_xauusd.json") as f: overlay = json.load(f)
result = {}
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
        result[tf] = bd if bd else od; continue
    keys = [k for k in sorted_bars[0].keys() if k != "time"]
    merged = {"tf": tf, "time": [b["time"] for b in sorted_bars]}
    for k in keys:
        merged[k] = [b.get(k, 0.0) for b in sorted_bars]
    result[tf] = merged

def run(cutoff_hour, label):
    cfg = Config.load()
    cfg.trading.backtest_initial_balance    = 10000.0
    cfg.trading.backtest_apply_friction     = True
    cfg.trading.backtest_commission_per_lot = 6.0
    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD",
                            start_date=SEP_START, end_date=SEP_END)
    orig_gen = engine._generate_signal
    def filtered_gen(hierarchy_result, data_all, price, current_time=None):
        if current_time and current_time.hour >= cutoff_hour:
            return None
        return orig_gen(hierarchy_result, data_all, price, current_time)
    if cutoff_hour < 24:
        engine._generate_signal = filtered_gen
    res = engine.run(result)
    trades = []
    if hasattr(engine, "_clusters"):
        for cluster in engine._clusters:
            for leg in cluster.legs:
                if leg.status == TradeStatus.CLOSED and leg.exit_price:
                    pnl = getattr(leg, "pnl", 0.0) or 0.0
                    trades.append(pnl)
    wins   = sum(1 for p in trades if p > 0.01)
    losses = sum(1 for p in trades if p < -0.01)
    pnl    = res.get("total_pnl", 0.0)
    wr     = res.get("win_rate", 0.0)
    status = "GREEN" if pnl > 0 else "RED"
    print(f"  [{label:22}]  Trades={len(trades):>3}  WR={wr:>5.1f}%  {wins}W/{losses}L  PnL=${pnl:>8.2f}  [{status}]")

print("\nXAUUSD Sep 1-19 — Session Cutoff Comparison:")
print(f"  {'Strategy':<24}  {'Trades':>6}  {'WR':>7}  W/L   {'PnL':>10}  Status")
print("  " + "-"*65)
run(24, "No cutoff (current)")
run(13, "London only < 13 UTC")
run(12, "London only < 12 UTC")
run(11, "London only < 11 UTC")
run(10, "London only < 10 UTC")
