"""Investigating the exact causes of trade reduction and testing their elimination.

Tests:
1. Baseline (Current: 197 trades, $116k)
2. Remove Retest Requirement (xau_require_retest = False -> Direct MT5 Limit Fill)
3. Extend NY Session to 17:00 UTC (xau_london_close_cutoff_hour = 17)
4. Combine Direct Limit Fill + Extended NY Session
5. Lower Displacement Thresholds (min_atr_mult=0.50, min_body_ratio=0.50)
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from scratch.run_full_jan_sep_2026_backtest import load_and_stitch_real_data


def test_frequency_boosters():
    data = load_and_stitch_real_data()

    experiments = [
        ("1. Baseline (Current)", {}),
        ("2. Direct MT5 Limit Fill (xau_require_retest=False)", {"xau_require_retest": False}),
        ("3. Extend NY to 17:00 UTC (cutoff=17:00)", {"xau_london_close_cutoff_hour": 17, "xau_london_close_cutoff_min": 0}),
        ("4. Direct Limit Fill + Extend NY to 17:00 UTC", {"xau_require_retest": False, "xau_london_close_cutoff_hour": 17, "xau_london_close_cutoff_min": 0}),
        ("5. Relax Displacement (ATR 0.50, Body 0.55)", {"xau_displacement_min_atr_mult": 0.50, "xau_displacement_min_body_ratio": 0.55}),
    ]

    for name, overrides in experiments:
        cfg = Config.load()
        cfg.trading.symbol = "XAUUSD"
        cfg.trading.symbols = ["XAUUSD"]
        cfg.trading.enable_conviction_sizing = True
        cfg.trading.conviction_scale_a_plus = 2.60
        cfg.trading.conviction_scale_a = 1.00
        for k, v in overrides.items():
            if hasattr(cfg.trading, k):
                setattr(cfg.trading, k, v)

        engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
        res = engine.run(data)

        trades = res.get("total_trades", 0)
        pnl = res.get("total_pnl", 0.0)
        wr = res.get("win_rate", 0.0)
        pf = res.get("profit_factor", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)
        ablation = res.get("ablation", {})

        print(f"\n{'='*75}")
        print(f"  {name}")
        print(f"{'='*75}")
        print(f"  Total Trades:     {trades}")
        print(f"  Win Rate:         {wr:.2f}%")
        print(f"  Net Profit:       ${pnl:,.2f}")
        print(f"  Profit Factor:    {pf:.2f}")
        print(f"  Max Drawdown:     {dd:.2f}%")
        print(f"  Ablation: Placed={ablation.get('orders_placed', 0)}, Filled={ablation.get('orders_filled', 0)}, Expired={ablation.get('orders_expired', 0)}")


if __name__ == "__main__":
    test_frequency_boosters()
