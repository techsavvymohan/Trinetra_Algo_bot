"""
Backtest experiment comparing:
1. Baseline Option C: All FVG trades at 2.60x conviction scale.
2. Tiered Conviction:
   - Grade A+ (Trend-aligned + Strong displacement): 2.60x
   - Grade A (Normal / Counter-trend): 1.00x base risk
   - Grade B/C: 1.00x / 0.60x
Runs on genuine Jan-Aug 2026 XAUUSD data.
"""
import os
import sys
import json
import math
import copy
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, TradeStatus, Bias

def run_test(data_xau, name: str, tiered: bool = False, min_disp_atr: float = 0.70, min_disp_body: float = 0.65):
    cfg = Config.load()
    cfg.trading.symbol = "XAUUSD"
    cfg.trading.symbols = ["XAUUSD"]
    cfg.trading.enable_conviction_sizing = True

    # Subclass or monkey-patch engine to test tiered conviction
    class TieredBacktestEngine(BacktestEngine):
        def _generate_signal(self, hierarchy_result: dict, data_all: dict, price: float, current_time=None):
            sig = super()._generate_signal(hierarchy_result, data_all, price, current_time=current_time)
            if sig is None:
                return None
            
            if tiered and sig.grade in (SignalGrade.A, SignalGrade.A_PLUS):
                # Check HTF trend alignment
                h1_b = sig.h1_bias
                h4_b = sig.h4_bias
                h1_val = h1_b.value if isinstance(h1_b, Bias) else str(h1_b)
                h4_val = h4_b.value if isinstance(h4_b, Bias) else str(h4_b)

                trend_aligned = False
                if sig.direction == TradeDirection.BUY:
                    if h1_val == "bullish" or (h1_val == "neutral" and h4_val == "bullish"):
                        trend_aligned = True
                elif sig.direction == TradeDirection.SELL:
                    if h1_val == "bearish" or (h1_val == "neutral" and h4_val == "bearish"):
                        trend_aligned = True

                if trend_aligned:
                    sig.grade = SignalGrade.A_PLUS
                else:
                    sig.grade = SignalGrade.A
            return sig

        def _execute_backtest_order(self, signal, account, data_all, idx, price, current_time=None):
            cluster = super()._execute_backtest_order(signal, account, data_all, idx, price, current_time=current_time)
            if cluster:
                cluster.signal = signal
                for leg in cluster.legs:
                    leg._signal_grade = signal.grade
            return cluster

    if tiered:
        cfg.trading.conviction_scale_a_plus = 2.60
        cfg.trading.conviction_scale_a = 1.00
        # Patch get_conviction_scale on this instance
        orig_get_scale = cfg.trading.get_conviction_scale
        def patched_scale(sig_or_grade, is_tuesday=False):
            grade = getattr(sig_or_grade, "grade", sig_or_grade)
            if grade == SignalGrade.A_PLUS:
                scale = getattr(cfg.trading, "conviction_scale_a_plus", 2.60)
            elif grade == SignalGrade.A:
                scale = getattr(cfg.trading, "conviction_scale_a", 1.00)
            elif grade == SignalGrade.B:
                scale = getattr(cfg.trading, "conviction_scale_b", 1.00)
            else:
                scale = getattr(cfg.trading, "conviction_scale_c", 0.60)
            if is_tuesday:
                scale *= getattr(cfg.trading, "tuesday_risk_scale", 0.43)
            return scale
        cfg.trading.get_conviction_scale = patched_scale
    else:
        cfg.trading.conviction_scale_a = 2.60

    engine = TieredBacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
    res = engine.run(data_xau)

    # Extract trades
    trades = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
                pnl = getattr(leg, "pnl", 0.0) or 0.0
                trades.append({
                    "open_time": leg.open_time,
                    "close_time": leg.close_time or leg.open_time,
                    "direction": leg.direction.value,
                    "entry_price": leg.entry_price,
                    "exit_price": leg.exit_price,
                    "lot_size": leg.lot_size,
                    "pnl": pnl,
                    "grade": getattr(leg, "_signal_grade", SignalGrade.A),
                    "exit_reason": leg.exit_reason.value if hasattr(leg.exit_reason, "value") else str(leg.exit_reason),
                })

    n = len(trades)
    if n == 0:
        print(f"{name}: 0 trades!")
        return None

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
    total_pnl = sum(t["pnl"] for t in trades)
    wr = len(wins) / n * 100
    gross_win = sum(wins)
    gross_loss = sum(losses)
    pf = gross_win / gross_loss if gross_loss > 0 else 999.0

    # Max Drawdown
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

    # Count by grade
    grades_count = {}
    for t in trades:
        g = t["grade"].value if hasattr(t["grade"], "value") else str(t["grade"])
        grades_count[g] = grades_count.get(g, 0) + 1

    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    print(f"  Total Trades:     {n}")
    print(f"  Trades by Grade:  {grades_count}")
    print(f"  Win Rate:         {wr:.2f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Net Profit:       ${total_pnl:,.2f} (ROI: +{roi:.1f}%)")
    print(f"  Profit Factor:    {pf:.2f}")
    print(f"  Max Drawdown:     ${max_dd:,.2f} ({max_dd_pct:.2f}%)")
    print(f"  Avg Win / Loss:   ${(np.mean(wins) if wins else 0):,.2f} / ${(np.mean(losses) if losses else 0):,.2f}")
    return {
        "name": name,
        "trades": n,
        "grades": grades_count,
        "win_rate": wr,
        "net_pnl": total_pnl,
        "roi": roi,
        "profit_factor": pf,
        "max_dd_pct": max_dd_pct,
    }

def main():
    print("Loading data...")
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)
    print("Data loaded successfully.")

    # 1. Baseline Option C (all FVG at 2.60x)
    res_base = run_test(data_xau, "Baseline Option C (All FVG @ 2.60x)", tiered=False)

    # 2. Tiered Conviction: HTF Trend Aligned -> A+ (2.60x), Counter-Trend -> A (1.00x)
    res_tiered = run_test(data_xau, "Tiered Conviction (A+ @ 2.60x, A @ 1.00x)", tiered=True)

if __name__ == "__main__":
    main()
