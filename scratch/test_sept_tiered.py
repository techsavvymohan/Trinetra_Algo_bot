import json
import sys, os
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, TradeStatus, Bias

with open("data/genuine_recent_xauusd.json") as f:
    data_all = json.load(f)

# Filter from 2026-09-01 to 2026-09-18
sept_data = {}
for tf, tdata in data_all.items():
    if not isinstance(tdata, dict) or "time" not in tdata:
        sept_data[tf] = tdata
        continue
    times = tdata["time"]
    idx_start = next((i for i, t in enumerate(times) if str(t) >= "2026-09-01"), None)
    if idx_start is not None:
        sept_data[tf] = {k: v[idx_start:] if isinstance(v, list) else v for k, v in tdata.items()}
    else:
        sept_data[tf] = tdata

print(f"Sept M1 bars: {len(sept_data.get('M1', {}).get('time', []))}")

cfg = Config.load()
cfg.trading.symbol = "XAUUSD"
cfg.trading.enable_conviction_sizing = False

class FeatureEngine(BacktestEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signal_cache = {}

    def _generate_signal(self, hierarchy_result, data_all, price, current_time=None):
        sig = super()._generate_signal(hierarchy_result, data_all, price, current_time=current_time)
        if sig:
            self.signal_cache[sig.id] = {
                "signal": sig,
                "score": sig.score,
                "sl_dist": abs(sig.entry_price - sig.sl_price),
                "h1_bias": sig.h1_bias.value if isinstance(sig.h1_bias, Bias) else str(sig.h1_bias),
                "direction": sig.direction.value,
            }
        return sig

eng = FeatureEngine(cfg, 10000.0, "XAUUSD")
eng.run(sept_data)

trades = []
for c in eng._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
            sig = eng.signal_cache.get(c.signal_id, {})
            pnl = getattr(leg, "pnl", 0.0) or 0.0
            ot = leg.open_time
            if not isinstance(ot, datetime):
                ot = datetime.fromisoformat(str(ot))
            trades.append({
                "open_time": ot,
                "close_time": leg.close_time or ot,
                "weekday": ot.weekday(),
                "hour_utc": ot.hour,
                "pnl_base": pnl,
                "win": 1 if pnl > 0 else 0,
                "h1_bias": sig.get("h1_bias", "neutral"),
                "sl_dist": sig.get("sl_dist", 0.0),
            })

print(f"Total Sept 1-18 trades: {len(trades)}")

def pred(t):
    return (13 <= t["hour_utc"] <= 15) and (t["h1_bias"] != "bullish")

# 1. Baseline Option C: All FVG @ 2.60x
sim_base = []
for t in trades:
    scale = 2.60
    if t["weekday"] == 1:
        scale *= 0.43
    sim_base.append({"close_time": t["close_time"], "pnl": t["pnl_base"] * scale})

# 2. Tiered Conviction: A+ @ 2.60x, A @ 1.00x
sim_tiered = []
for t in trades:
    scale = 2.60 if pred(t) else 1.00
    if t["weekday"] == 1:
        scale *= 0.43
    sim_tiered.append({"close_time": t["close_time"], "pnl": t["pnl_base"] * scale})

for name, sim in [("Baseline Option C (All @ 2.60x)", sim_base), ("Tiered Conviction (A+ @ 2.60x, A @ 1.00x)", sim_tiered)]:
    sorted_sim = sorted(sim, key=lambda x: x["close_time"])
    peak = 10000.0
    eq = 10000.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for st in sorted_sim:
        eq += st["pnl"]
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = (dd / peak) * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
    tot = sum(st["pnl"] for st in sim)
    roi = tot / 10000.0 * 100
    wins = [st["pnl"] for st in sim if st["pnl"] > 0]
    losses = [abs(st["pnl"]) for st in sim if st["pnl"] < 0]
    pf = sum(wins) / sum(losses) if losses else 99.0
    wr = len(wins) / len(sim) * 100 if sim else 0
    print(f"\n{name}:")
    print(f"  Trades: {len(sim)} | WR: {wr:.1f}% | Net PnL: ${tot:,.2f} (ROI: +{roi:.1f}%) | PF: {pf:.2f} | Max DD: {max_dd_pct:.2f}% (${max_dd:,.2f})")
