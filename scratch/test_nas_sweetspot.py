"""Tune NAS100 parameters to maximize alpha and eliminate remaining drags.

Tests:
1. Enable Conviction Sizing (A+ @ 2.40x, A @ 1.0x)
2. Stagnation Exit ablation (40 bars vs disabled vs 25 bars)
3. Start time tuning (13:35 vs 14:00 vs 14:30 UTC after opening fakeouts)
"""
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from scratch.run_combined_xau_nas_full_backtest import load_stitched_nas100, extract_trades

def test_nas_variations():
    data_nas = load_stitched_nas100()

    variations = [
        ("1. Baseline (Current Fixed)", {}),
        ("2. Enable Conviction Sizing (A+ @ 2.40x)", {
            "enable_conviction_sizing": True,
            "conviction_scale_nas_a_plus": 2.40,
            "conviction_scale_a": 1.00,
        }),
        ("3. Conviction Sizing + Disable Stagnation Exit", {
            "enable_conviction_sizing": True,
            "conviction_scale_nas_a_plus": 2.40,
            "conviction_scale_a": 1.00,
            "nas_stagnation_bars": 999,
        }),
        ("4. Conviction + Stagnation 45 bars + Start 14:15 UTC", {
            "enable_conviction_sizing": True,
            "conviction_scale_nas_a_plus": 2.40,
            "conviction_scale_a": 1.00,
            "nas_stagnation_bars": 45,
            "nas_killzone_morning_start_min": 15,
            "nas_session_start_hour": 14,
        }),
        ("5. Conviction + Start 15:45 UTC (Pure Afternoon Trend Continuation)", {
            "enable_conviction_sizing": True,
            "conviction_scale_nas_a_plus": 2.40,
            "conviction_scale_a": 1.00,
            "nas_stagnation_bars": 45,
            "nas_session_start_hour": 15,
            "nas_killzone_morning_start_min": 45,
        }),
    ]

    for name, overrides in variations:
        cfg = Config.load()
        cfg.trading.symbol = "USTECH100M"
        cfg.trading.symbols = ["USTECH100M"]
        cfg.trading.backtest_apply_friction = True
        cfg.trading.backtest_commission_per_lot = 6.0
        for k, v in overrides.items():
            if hasattr(cfg.trading, k):
                setattr(cfg.trading, k, v)

        eng = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M")
        res = eng.run(data_nas)
        trades = extract_trades(eng, "USTECH100M")

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]
        pnl = sum(t["pnl"] for t in trades)
        wr = (len(wins) / len(trades) * 100) if trades else 0.0
        pf = res.get("profit_factor", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)

        print(f"\n{'='*75}")
        print(f"  {name}")
        print(f"{'='*75}")
        print(f"  Trades     : {len(trades)}")
        print(f"  Win Rate   : {wr:.1f}% ({len(wins)}W / {len(losses)}L)")
        print(f"  Net Profit : ${pnl:,.2f}")
        print(f"  Profit Fac : {pf:.2f}")
        print(f"  Max DD     : {dd:.2f}%")

if __name__ == "__main__":
    test_nas_variations()
