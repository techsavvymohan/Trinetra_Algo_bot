import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine


def test_gold_exit_variations():
    with open("data/genuine_recent_xauusd.json") as f:
        data = json.load(f)

    # Base timing: 08:00 London + 14:45 NY Cutoff
    experiments = [
        ("Combined Timing (08:00 Lon, 14:45 NY) - Current Exits", {
            "xau_target_r": 2.0, "xau_breakeven_trigger_r": 1.50,
            "enable_split_tranche_runner": True, "partial_tp_tranche1_r": 1.0, "partial_tp_tranche1_pct": 25.0,
        }),
        ("Breakeven at 1.0R (Early Risk Free)", {
            "xau_target_r": 2.0, "xau_breakeven_trigger_r": 1.00, "xau_breakeven_buffer_r": 0.10,
            "enable_split_tranche_runner": True, "partial_tp_tranche1_r": 1.0, "partial_tp_tranche1_pct": 25.0,
        }),
        ("Breakeven at 1.2R (Balanced Protection)", {
            "xau_target_r": 2.0, "xau_breakeven_trigger_r": 1.20, "xau_breakeven_buffer_r": 0.10,
            "enable_split_tranche_runner": True, "partial_tp_tranche1_r": 1.0, "partial_tp_tranche1_pct": 25.0,
        }),
        ("Target 1.5R + Breakeven at 1.0R (High Hit Rate Scalp)", {
            "xau_target_r": 1.5, "xau_breakeven_trigger_r": 1.00, "xau_breakeven_buffer_r": 0.10,
            "enable_split_tranche_runner": False,
        }),
        ("Target 2.0R Full (No Partial Tranche) + BE at 1.0R", {
            "xau_target_r": 2.0, "xau_breakeven_trigger_r": 1.00, "xau_breakeven_buffer_r": 0.10,
            "enable_split_tranche_runner": False,
        }),
        ("Target 2.0R Full + BE at 1.2R", {
            "xau_target_r": 2.0, "xau_breakeven_trigger_r": 1.20, "xau_breakeven_buffer_r": 0.10,
            "enable_split_tranche_runner": False,
        }),
        ("Target 2.5R Full + BE at 1.2R (Big Winner Runner)", {
            "xau_target_r": 2.5, "xau_breakeven_trigger_r": 1.20, "xau_breakeven_buffer_r": 0.10,
            "enable_split_tranche_runner": False,
        }),
    ]

    print("=" * 105)
    print("  TESTING GOLD EXIT & TARGET CONFIGURATIONS (July 8 - September 18, 2026)")
    print("  Session Timing: 08:00 UTC London Open | 14:45 UTC NY Cutoff")
    print("=" * 105)
    print(f"{'Experiment':<60} | {'PnL ($)':>10} | {'Trades':>6} | {'WR (%)':>7} | {'PF':>5} | {'MaxDD':>7}")
    print("-" * 105)

    for name, params in experiments:
        cfg = Config()
        cfg.trading.symbol = "XAUUSD"
        cfg.trading.symbols = ["XAUUSD"]
        cfg.trading.daily_loss_limit_pct = 50.0
        cfg.trading.max_dd_limit_pct = 50.0
        cfg.trading.enable_profit_compounding = True
        cfg.trading.backtest_apply_friction = True

        # Timing hooks
        cfg.trading.is_in_xau_london_killzone = lambda t: t.hour >= 8 and (t.hour < 10 or (t.hour == 10 and t.minute <= 30))
        cfg.trading.xau_london_close_cutoff_hour = 14
        cfg.trading.xau_london_close_cutoff_min = 45

        for k, v in params.items():
            setattr(cfg.trading, k, v)

        engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
        res = engine.run(data)

        pnl = res.get("total_pnl", 0.0)
        trades = res.get("total_trades", 0)
        wr = res.get("win_rate", 0.0)
        pf = res.get("profit_factor", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)

        print(f"{name:<60} | ${pnl:>9.2f} | {trades:>6} | {wr:>6.1f}% | {pf:>5.2f} | {dd:>6.2f}%")

    print("-" * 105)


if __name__ == "__main__":
    test_gold_exit_variations()
