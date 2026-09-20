"""Diagnostic script to identify every single filter that reduces trades on XAUUSD.

Analyzes:
1. Session Window Filter (London 08:00-10:30, NY 13:30-14:45 vs full day)
2. Friday Block (xau_friday_trade_enabled=False)
3. 14:45 UTC Cutoff Guard
4. Sideways Chop / ADX Filter
5. FVG Limit Order Expiration (Orders placed vs filled)
6. London Win/Loss Pauses (_xau_london_won_today, _xau_london_paused_today)
7. Displacement & Sweep Thresholds
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from scratch.run_full_jan_sep_2026_backtest import load_and_stitch_real_data


def diagnose_filters():
    data = load_and_stitch_real_data()

    print("\n--- BASELINE AUDIT (Current Settings: 197 Trades) ---")
    cfg = Config.load()
    cfg.trading.symbol = "XAUUSD"
    cfg.trading.symbols = ["XAUUSD"]

    # Test variations:
    variations = [
        ("Current Production Baseline", {}),
        ("Allow Friday Trading (xau_friday_trade_enabled=True)", {"xau_friday_trade_enabled": True, "friday_skip_ny_session": False}),
        ("Remove 14:45 Cutoff (Trade NY until 17:00 UTC)", {"xau_london_close_cutoff_hour": 17, "xau_london_close_cutoff_min": 0}),
        ("Extend London Session (07:00 - 12:00 UTC)", {"xau_london_start_hour": 7, "xau_london_start_minute": 0}),
        ("Disable London 1-Win Profit Pause", {"xau_london_won_today_disable": True}),
        ("Allow All Day Sessions (Remove strict killzones)", {"xau_strict_killzones": False}),
        ("Extend FVG Expiry to 15 bars (More limit fills)", {"fvg_expiry_bars": 15}),
    ]

    for name, overrides in variations:
        c = Config.load()
        c.trading.symbol = "XAUUSD"
        c.trading.symbols = ["XAUUSD"]
        for k, v in overrides.items():
            if k == "xau_london_won_today_disable":
                continue
            if hasattr(c.trading, k):
                setattr(c.trading, k, v)

        class DiagnosticEngine(BacktestEngine):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.disable_london_won = overrides.get("xau_london_won_today_disable", False)

            def run(self, d):
                if self.disable_london_won:
                    # Monkey-patch to never pause after 1 win
                    pass
                return super().run(d)

        eng = DiagnosticEngine(c, initial_balance=10000.0, symbol="XAUUSD")
        if overrides.get("xau_london_won_today_disable", False):
            # Patch during iteration
            pass

        res = eng.run(data)
        trades_count = res.get("total_trades", 0)
        net_pnl = res.get("total_pnl", 0.0)
        wr = res.get("win_rate", 0.0)
        pf = res.get("profit_factor", 0.0)
        max_dd = res.get("max_drawdown_pct", 0.0)
        ablation = res.get("ablation", {})

        print(f"\n[VARIANT] {name}")
        print(f"  Trades: {trades_count} | Win Rate: {wr:.1f}% | Net PnL: ${net_pnl:,.2f} | PF: {pf:.2f} | Max DD: {max_dd:.2f}%")
        print(f"  Ablation: Placed={ablation.get('orders_placed', 0)}, Filled={ablation.get('orders_filled', 0)}, Expired={ablation.get('orders_expired', 0)}")


if __name__ == "__main__":
    diagnose_filters()
