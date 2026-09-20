import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine


def run_experiment_with_filter(name, lon_start_h=7, lon_start_m=45, ny_end_h=15, ny_end_m=45, skip_friday=False, full_tp=False):
    with open("data/genuine_recent_xauusd.json") as f:
        data = json.load(f)

    cfg = Config()
    cfg.trading.symbol = "XAUUSD"
    cfg.trading.symbols = ["XAUUSD"]
    cfg.trading.daily_loss_limit_pct = 50.0
    cfg.trading.max_dd_limit_pct = 50.0
    cfg.trading.enable_profit_compounding = True
    cfg.trading.backtest_apply_friction = True
    if full_tp:
        cfg.trading.enable_split_tranche_runner = False
        cfg.trading.xau_target_r = 2.0

    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")

    # Custom session filter function
    def custom_is_in_session(current_time):
        if current_time is None:
            return False
        if skip_friday and current_time.weekday() == 4:
            return False
        h = current_time.hour
        m = current_time.minute

        # London window
        in_lon = False
        if (h > lon_start_h or (h == lon_start_h and m >= lon_start_m)) and (h < 10 or (h == 10 and m <= 30)):
            in_lon = True

        # NY window
        in_ny = False
        if (h > 13 or (h == 13 and m >= 30)) and (h < ny_end_h or (h == ny_end_h and m <= ny_end_m)):
            in_ny = True

        return in_lon or in_ny

    # Subclass or monkey patch the session check in engine.run
    # In engine.run, let's inject custom_is_in_session via a wrapper
    orig_run = engine.run

    # Patch is_in_xau_london_killzone and session logic on cfg.trading
    cfg.trading.is_in_xau_london_killzone = lambda t: (t.hour > lon_start_h or (t.hour == lon_start_h and t.minute >= lon_start_m)) and (t.hour < 10 or (t.hour == 10 and t.minute <= 30))
    cfg.trading.xau_london_close_cutoff_hour = ny_end_h
    cfg.trading.xau_london_close_cutoff_min = ny_end_m
    if skip_friday:
        cfg.trading.friday_skip_ny_session = True

    res = engine.run(data)
    pnl = res.get("total_pnl", 0.0)
    trades = res.get("total_trades", 0)
    wr = res.get("win_rate", 0.0)
    pf = res.get("profit_factor", 0.0)
    dd = res.get("max_drawdown_pct", 0.0)

    print(f"{name:<55} | ${pnl:>9.2f} | {trades:>6} | {wr:>6.1f}% | {pf:>5.2f} | {dd:>6.2f}%")
    return res


if __name__ == "__main__":
    print("=" * 95)
    print("  TESTING GOLD OPTIMIZATIONS (July 8 - September 18, 2026)")
    print("=" * 95)
    print(f"{'Experiment':<55} | {'PnL ($)':>10} | {'Trades':>6} | {'WR (%)':>7} | {'PF':>5} | {'MaxDD':>7}")
    print("-" * 95)

    run_experiment_with_filter("1. Baseline (Current Settings)")
    run_experiment_with_filter("2. Start London at 08:00 UTC (Avoid 07:45 Trap)", lon_start_h=8, lon_start_m=0)
    run_experiment_with_filter("3. NY Cutoff at 14:45 UTC (Avoid Late NY Chop)", ny_end_h=14, ny_end_m=45)
    run_experiment_with_filter("4. Skip Friday Entire Day (Friday Filter)", skip_friday=True)
    run_experiment_with_filter("5. Combined Timing (08:00 London + 14:45 NY Cutoff)", lon_start_h=8, lon_start_m=0, ny_end_h=14, ny_end_m=45)
    run_experiment_with_filter("6. Combined Timing + Friday Skip", lon_start_h=8, lon_start_m=0, ny_end_h=14, ny_end_m=45, skip_friday=True)
    print("-" * 95)
