import json
import sys, os
from datetime import datetime
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, TradeStatus, Bias

with open("data/genuine_jan_aug_2026_xauusd.json") as f:
    data_xau = json.load(f)

# Run once with 1.0x to collect all trades and their properties
cfg = Config.load()
cfg.trading.symbol = "XAUUSD"
cfg.trading.enable_conviction_sizing = False

class SignalCollectorEngine(BacktestEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signal_cache = {}

    def _generate_signal(self, hierarchy_result, data_all, price, current_time=None):
        sig = super()._generate_signal(hierarchy_result, data_all, price, current_time=current_time)
        if sig:
            self.signal_cache[sig.id] = {
                "signal": sig,
                "h1_bias": sig.h1_bias.value if isinstance(sig.h1_bias, Bias) else str(sig.h1_bias),
                "h4_bias": sig.h4_bias.value if isinstance(sig.h4_bias, Bias) else str(sig.h4_bias),
                "direction": sig.direction,
                "score": sig.score,
                "entry_price": sig.entry_price,
            }
        return sig

eng = SignalCollectorEngine(cfg, 10000.0, "XAUUSD")
eng.run(data_xau)

# Match trades with their signals
matched_trades = []
for c in eng._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
            sig_info = eng.signal_cache.get(c.signal_id, {})
            h1 = sig_info.get("h1_bias", "neutral")
            h4 = sig_info.get("h4_bias", "neutral")
            d = leg.direction
            
            # Trend alignment
            h1_aligned = (d == TradeDirection.BUY and h1 == "bullish") or (d == TradeDirection.SELL and h1 == "bearish")
            h1_neutral = h1 == "neutral"
            h4_aligned = (d == TradeDirection.BUY and h4 == "bullish") or (d == TradeDirection.SELL and h4 == "bearish")
            trend_aligned = h1_aligned or (h1_neutral and h4_aligned)
            
            pnl = getattr(leg, "pnl", 0.0) or 0.0
            matched_trades.append({
                "open_time": leg.open_time,
                "close_time": leg.close_time or leg.open_time,
                "direction": d.value,
                "h1_bias": h1,
                "h4_bias": h4,
                "h1_aligned": h1_aligned,
                "trend_aligned": trend_aligned,
                "pnl_base": pnl,
                "win": 1 if pnl > 0 else 0,
            })

print(f"Total trades matched: {len(matched_trades)}")

# Compare definitions
for title, pred in [
    ("Strict H1 Aligned Only", lambda t: t["h1_aligned"]),
    ("H1 Aligned OR (H1 Neutral & H4 Aligned)", lambda t: t["trend_aligned"]),
]:
    a_plus = [t for t in matched_trades if pred(t)]
    a_normal = [t for t in matched_trades if not pred(t)]
    
    wr_plus = sum(t["win"] for t in a_plus) / len(a_plus) * 100 if a_plus else 0
    pnl_plus = sum(t["pnl_base"] for t in a_plus)
    
    wr_norm = sum(t["win"] for t in a_normal) / len(a_normal) * 100 if a_normal else 0
    pnl_norm = sum(t["pnl_base"] for t in a_normal)
    
    print(f"\n--- {title} ---")
    print(f"  Grade A+ (Unicorn):  {len(a_plus):3d} trades | WR: {wr_plus:.1f}% | Base PnL: ${pnl_plus:,.2f}")
    print(f"  Grade A  (Normal):   {len(a_normal):3d} trades | WR: {wr_norm:.1f}% | Base PnL: ${pnl_norm:,.2f}")

    # Now simulate with sizing: A+ gets 2.60x, A gets 1.00x
    sim_trades = []
    for t in matched_trades:
        scale = 2.60 if pred(t) else 1.00
        # Check tuesday
        ot = t["open_time"]
        if hasattr(ot, "weekday") and ot.weekday() == 1:
            scale *= 0.43
        sim_pnl = t["pnl_base"] * scale
        sim_trades.append({
            "close_time": t["close_time"],
            "pnl": sim_pnl,
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
    print(f"  --> Tiered Outcome: ROI: +{roi:.1f}% (${tot_pnl:,.2f}) | PF: {pf:.2f} | Max DD: {max_dd_pct:.2f}% (${max_dd:,.2f})")
