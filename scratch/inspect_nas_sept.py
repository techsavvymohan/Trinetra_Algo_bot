"""Inspect the 14 September trades of NAS100."""
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from scratch.run_combined_xau_nas_full_backtest import load_stitched_nas100, extract_trades

def inspect_sep():
    data_nas = load_stitched_nas100()

    cfg = Config.load()
    cfg.trading.symbol = "USTECH100M"
    cfg.trading.symbols = ["USTECH100M"]
    cfg.trading.backtest_apply_friction = True
    cfg.trading.enable_conviction_sizing = True
    cfg.trading.conviction_scale_nas_a_plus = 2.40
    cfg.trading.conviction_scale_a = 1.00
    cfg.trading.nas_session_start_hour = 15
    cfg.trading.nas_killzone_morning_start_min = 45
    cfg.trading.nas_stagnation_bars = 45
    cfg.trading.backtest_commission_per_lot = 0.0

    eng = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M")
    res = eng.run(data_nas)
    trades = extract_trades(eng, "USTECH100M")

    sep_trades = [t for t in trades if t["open_time"].strftime("%Y-%m") == "2026-09"]
    print("="*80)
    print(f"  NAS100 SEPTEMBER 2026 TRADES ({len(sep_trades)})")
    print("="*80)
    for t in sep_trades:
        print(f"  {t['open_time']} | Dir: {t['direction']:<4} | Entry: {t['entry_price']:.1f} | Exit: {t['exit_price']:.1f} | PnL: ${t['pnl']:>8.2f} | Reason: {t['exit_reason']}")

if __name__ == "__main__":
    inspect_sep()
