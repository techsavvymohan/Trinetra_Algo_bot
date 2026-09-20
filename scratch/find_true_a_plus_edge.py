import json
import sys, os
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, TradeStatus, Bias

with open("data/genuine_jan_aug_2026_xauusd.json") as f:
    data_xau = json.load(f)

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
                "regime": sig.regime.value if hasattr(sig.regime, "value") else str(sig.regime),
                "setup_type": getattr(sig, "setup_type", "UNKNOWN"),
                "entry_price": sig.entry_price,
                "sl_dist": abs(sig.entry_price - sig.sl_price),
                "h1_bias": sig.h1_bias.value if isinstance(sig.h1_bias, Bias) else str(sig.h1_bias),
                "h4_bias": sig.h4_bias.value if isinstance(sig.h4_bias, Bias) else str(sig.h4_bias),
                "direction": sig.direction.value,
            }
        return sig

eng = FeatureEngine(cfg, 10000.0, "XAUUSD")
eng.run(data_xau)

rows = []
for c in eng._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
            sig = eng.signal_cache.get(c.signal_id, {})
            pnl = getattr(leg, "pnl", 0.0) or 0.0
            ot = leg.open_time
            if not isinstance(ot, datetime):
                ot = datetime.fromisoformat(str(ot))
            
            rows.append({
                "open_time": ot,
                "weekday": ot.weekday(),
                "hour_utc": ot.hour,
                "direction": leg.direction.value,
                "pnl": pnl,
                "win": 1 if pnl > 0 else 0,
                "score": sig.get("score", 0),
                "sl_dist": sig.get("sl_dist", 0.0),
                "h1_bias": sig.get("h1_bias", "neutral"),
                "regime": sig.get("regime", "unknown"),
                "exit_reason": leg.exit_reason.value if hasattr(leg.exit_reason, "value") else str(leg.exit_reason),
            })

df = pd.DataFrame(rows)
print(f"Total trades: {len(df)}")
print(f"Overall Win Rate: {df['win'].mean()*100:.1f}% | Total PnL: ${df['pnl'].sum():,.2f}")

print("\n--- BY SESSION HOUR (UTC) ---")
for h, grp in df.groupby("hour_utc"):
    wr = grp["win"].mean() * 100
    pnl = grp["pnl"].sum()
    print(f"Hour {h:02d}:00 UTC: {len(grp):2d} trades | WR: {wr:.1f}% | PnL: ${pnl:,.2f}")

print("\n--- BY DAY OF WEEK ---")
days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
for d, grp in df.groupby("weekday"):
    wr = grp["win"].mean() * 100
    pnl = grp["pnl"].sum()
    print(f"{days[d]}: {len(grp):2d} trades | WR: {wr:.1f}% | PnL: ${pnl:,.2f}")

print("\n--- BY DIRECTION ---")
for d, grp in df.groupby("direction"):
    wr = grp["win"].mean() * 100
    pnl = grp["pnl"].sum()
    print(f"{d.upper()}: {len(grp):2d} trades | WR: {wr:.1f}% | PnL: ${pnl:,.2f}")

print("\n--- BY STOP LOSS DISTANCE (RISK) ---")
df["sl_bin"] = pd.qcut(df["sl_dist"], 3, labels=["Tight SL", "Medium SL", "Wide SL"])
for b, grp in df.groupby("sl_bin"):
    wr = grp["win"].mean() * 100
    pnl = grp["pnl"].sum()
    print(f"{b}: {len(grp):2d} trades | WR: {wr:.1f}% | PnL: ${pnl:,.2f} | Avg SL: {grp['sl_dist'].mean():.2f}")

print("\n--- BY H1 BIAS ---")
for b, grp in df.groupby("h1_bias"):
    wr = grp["win"].mean() * 100
    pnl = grp["pnl"].sum()
    print(f"{b}: {len(grp):2d} trades | WR: {wr:.1f}% | PnL: ${pnl:,.2f}")
