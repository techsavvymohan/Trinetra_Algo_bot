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
                "sl_dist": abs(sig.entry_price - sig.sl_price),
                "h1_bias": sig.h1_bias.value if isinstance(sig.h1_bias, Bias) else str(sig.h1_bias),
                "h4_bias": sig.h4_bias.value if isinstance(sig.h4_bias, Bias) else str(sig.h4_bias),
                "direction": sig.direction.value,
            }
        return sig

eng = FeatureEngine(cfg, 10000.0, "XAUUSD")
eng.run(data_xau)

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
                "direction": leg.direction.value,
                "pnl_base": pnl,
                "win": 1 if pnl > 0 else 0,
                "score": sig.get("score", 0),
                "sl_dist": sig.get("sl_dist", 0.0),
                "h1_bias": sig.get("h1_bias", "neutral"),
            })

print(f"Total trades: {len(trades)}")

# Test several A+ candidate definitions
candidates = [
    (
        "Candidate 1: NY Core (13-15 UTC) + SL >= 6.0",
        lambda t: (13 <= t["hour_utc"] <= 15) and (t["sl_dist"] >= 6.0)
    ),
    (
        "Candidate 2: NY Core (13-15 UTC) + (H1 != 'bullish')",
        lambda t: (13 <= t["hour_utc"] <= 15) and (t["h1_bias"] != "bullish")
    ),
    (
        "Candidate 3: High-Quality Sessions (NY Core OR 07/09 UTC) + SL >= 6.0",
        lambda t: (t["hour_utc"] in (7, 9, 10, 13, 14, 15)) and (t["sl_dist"] >= 6.0)
    ),
    (
        "Candidate 4: All except London 08:00 UTC chop",
        lambda t: t["hour_utc"] != 8
    ),
    (
        "Candidate 5: NY Core (13-15 UTC) all setups",
        lambda t: 13 <= t["hour_utc"] <= 15
    ),
]

for title, pred in candidates:
    a_plus = [t for t in trades if pred(t)]
    a_norm = [t for t in trades if not pred(t)]
    
    wr_plus = sum(t["win"] for t in a_plus) / len(a_plus) * 100 if a_plus else 0
    pnl_plus = sum(t["pnl_base"] for t in a_plus)
    
    wr_norm = sum(t["win"] for t in a_norm) / len(a_norm) * 100 if a_norm else 0
    pnl_norm = sum(t["pnl_base"] for t in a_norm)
    
    # Simulate: A+ gets 2.60x, A gets 1.00x, Tuesday gets 0.43x
    sim_trades = []
    for t in trades:
        scale = 2.60 if pred(t) else 1.00
        if t["weekday"] == 1:
            scale *= 0.43
        sim_trades.append({
            "close_time": t["close_time"],
            "pnl": t["pnl_base"] * scale,
        })
    
    sorted_sim = sorted(sim_trades, key=lambda x: x["close_time"])
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
            
    tot_pnl = sum(st["pnl"] for st in sim_trades)
    roi = tot_pnl / 10000.0 * 100
    wins = [st["pnl"] for st in sim_trades if st["pnl"] > 0]
    losses = [abs(st["pnl"]) for st in sim_trades if st["pnl"] < 0]
    pf = sum(wins) / sum(losses) if losses else 99.0

    print(f"\n{'='*75}")
    print(f"  {title}")
    print(f"{'='*75}")
    print(f"  Grade A+ (Unicorn: 2.60x): {len(a_plus):3d} trades | Win Rate: {wr_plus:.1f}% | Base PnL: ${pnl_plus:,.2f}")
    print(f"  Grade A  (Normal:  1.00x): {len(a_norm):3d} trades | Win Rate: {wr_norm:.1f}% | Base PnL: ${pnl_norm:,.2f}")
    print(f"  --> TOTAL ROI: +{roi:.1f}% (${tot_pnl:,.2f}) | PF: {pf:.2f} | Max DD: {max_dd_pct:.2f}% (${max_dd:,.2f})")
