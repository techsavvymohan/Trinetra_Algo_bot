import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine


def test_solutions():
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)

    # Current Setup (Edge A active)
    cfg_current = Config.load()
    cfg_current.trading.runner_trail_atr_mult = 3.0
    eng_curr = BacktestEngine(cfg_current, initial_balance=10000.0, symbol="XAUUSD")
    res_curr = eng_curr.run(data_xau)

    # Solution 1: Turn off early partial close (No 1.0R 25% dilution, hold full size to 2.0R TP)
    cfg_no_partial = Config.load()
    cfg_no_partial.trading.runner_trail_atr_mult = 3.0
    cfg_no_partial.trading.xau_partial_close_enabled = False
    eng_no_partial = BacktestEngine(cfg_no_partial, initial_balance=10000.0, symbol="XAUUSD")
    res_no_partial = eng_no_partial.run(data_xau)

    # Solution 2: Enable Early Invalidation Exit (Cut losses at -0.5R instead of taking full SL)
    cfg_early_inv = Config.load()
    cfg_early_inv.trading.runner_trail_atr_mult = 3.0
    cfg_early_inv.trading.xau_early_invalidation_exit = True
    eng_early_inv = BacktestEngine(cfg_early_inv, initial_balance=10000.0, symbol="XAUUSD")
    res_early_inv = eng_early_inv.run(data_xau)

    # Solution 3: Both (No early partial + Early invalidation exit)
    cfg_both = Config.load()
    cfg_both.trading.runner_trail_atr_mult = 3.0
    cfg_both.trading.xau_partial_close_enabled = False
    cfg_both.trading.xau_early_invalidation_exit = True
    eng_both = BacktestEngine(cfg_both, initial_balance=10000.0, symbol="XAUUSD")
    res_both = eng_both.run(data_xau)

    print("=" * 105)
    print("  SOLUTIONS TO ASYMMETRIC SL vs PARTIAL TP")
    print("=" * 105)
    print(f"{'Configuration':<42} | {'Net PnL ($)':>14} | {'Win Rate':>10} | {'Max DD ($)':>14} | {'Profit Factor':>13}")
    print("-" * 105)
    print(f"{'Current (Partial Close ON, Early Inv OFF)':<42} | ${res_curr.get('total_pnl', 0):>13,.2f} | {res_curr.get('win_rate', 0):>9.1f}% | ${res_curr.get('max_dd_dollars', 0):>13,.2f} | {res_curr.get('profit_factor', 0):>13.2f}")
    print(f"{'Sol 1: No Early Partial (Full Size to 2.0R)':<42} | ${res_no_partial.get('total_pnl', 0):>13,.2f} | {res_no_partial.get('win_rate', 0):>9.1f}% | ${res_no_partial.get('max_dd_dollars', 0):>13,.2f} | {res_no_partial.get('profit_factor', 0):>13.2f}")
    print(f"{'Sol 2: Early Invalidation Exit (Cut SL early)':<42} | ${res_early_inv.get('total_pnl', 0):>13,.2f} | {res_early_inv.get('win_rate', 0):>9.1f}% | ${res_early_inv.get('max_dd_dollars', 0):>13,.2f} | {res_early_inv.get('profit_factor', 0):>13.2f}")
    print(f"{'Sol 3: Combined (No Partial + Early Invalidation)':<42} | ${res_both.get('total_pnl', 0):>13,.2f} | {res_both.get('win_rate', 0):>9.1f}% | ${res_both.get('max_dd_dollars', 0):>13,.2f} | {res_both.get('profit_factor', 0):>13.2f}")
    print("=" * 105)


if __name__ == "__main__":
    test_solutions()
