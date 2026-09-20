import sys, json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(".").resolve()
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

def run_test(cutoff_hour):
    print(f"\n==========================================")
    print(f"TESTING WITH CUTOFF_HOUR = {cutoff_hour}")
    print(f"==========================================")
    
    # 1. Jan-Aug 2026 XAUUSD
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_jan_aug = json.load(f)
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = 10000.0
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0
    
    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
    orig_gen = engine._generate_signal
    def filtered_gen(hierarchy_result, data_all, price, current_time=None):
        if current_time and current_time.hour >= cutoff_hour:
            return None
        return orig_gen(hierarchy_result, data_all, price, current_time)
    if cutoff_hour < 24:
        engine._generate_signal = filtered_gen
    res1 = engine.run(data_jan_aug)
    print(f"Jan-Aug 2026: Trades={res1.get('total_trades')} WR={res1.get('win_rate'):.1f}% PnL=${res1.get('total_pnl'):.2f} MaxDD={res1.get('max_drawdown_pct'):.2f}%")

    # 2. Jun-Sep 2026 OOS XAUUSD
    with open("data/native_true_jun_sep_xauusd.json") as f:
        data_jun_sep = json.load(f)
    engine2 = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
    if cutoff_hour < 24:
        engine2._generate_signal = filtered_gen
    res2 = engine2.run(data_jun_sep)
    print(f"Jun-Sep 2026: Trades={res2.get('total_trades')} WR={res2.get('win_rate'):.1f}% PnL=${res2.get('total_pnl'):.2f} MaxDD={res2.get('max_drawdown_pct'):.2f}%")

if __name__ == "__main__":
    run_test(24)
    run_test(13)
