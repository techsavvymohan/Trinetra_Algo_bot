import json
import sys
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine


def resample_m1_to_m15(m1_dict):
    """Accurately resample M1 bars into M15 bars without lookahead."""
    times_m1 = m1_dict["time"]
    opens_m1 = m1_dict["open"]
    highs_m1 = m1_dict["high"]
    lows_m1 = m1_dict["low"]
    closes_m1 = m1_dict["close"]
    vols_m1 = m1_dict["tick_volume"]
    spreads_m1 = m1_dict["spread"]

    m15_times, m15_opens, m15_highs, m15_lows, m15_closes, m15_vols, m15_spreads = [], [], [], [], [], [], []

    # Group M1 bars by 15-minute intervals
    cur_bucket = None
    b_open = b_high = b_low = b_close = b_vol = b_spread = None

    for i in range(len(times_m1)):
        t_raw = times_m1[i]
        if isinstance(t_raw, str):
            dt = datetime.fromisoformat(t_raw)
        else:
            dt = datetime.fromtimestamp(t_raw, tz=timezone.utc)

        # 15-minute floor bucket
        bucket_minute = (dt.minute // 15) * 15
        bucket_dt = dt.replace(minute=bucket_minute, second=0, microsecond=0)

        if cur_bucket != bucket_dt:
            if cur_bucket is not None:
                m15_times.append(cur_bucket.isoformat())
                m15_opens.append(b_open)
                m15_highs.append(b_high)
                m15_lows.append(b_low)
                m15_closes.append(b_close)
                m15_vols.append(b_vol)
                m15_spreads.append(b_spread)
            cur_bucket = bucket_dt
            b_open = opens_m1[i]
            b_high = highs_m1[i]
            b_low = lows_m1[i]
            b_close = closes_m1[i]
            b_vol = vols_m1[i]
            b_spread = spreads_m1[i]
        else:
            b_high = max(b_high, highs_m1[i])
            b_low = min(b_low, lows_m1[i])
            b_close = closes_m1[i]
            b_vol += vols_m1[i]
            b_spread = spreads_m1[i]

    if cur_bucket is not None:
        m15_times.append(cur_bucket.isoformat())
        m15_opens.append(b_open)
        m15_highs.append(b_high)
        m15_lows.append(b_low)
        m15_closes.append(b_close)
        m15_vols.append(b_vol)
        m15_spreads.append(b_spread)

    return {
        "tf": "M15",
        "time": m15_times,
        "open": m15_opens,
        "high": m15_highs,
        "low": m15_lows,
        "close": m15_closes,
        "tick_volume": m15_vols,
        "spread": m15_spreads,
    }


def run_experiment_on_symbol(symbol: str, data_path: str):
    print("=" * 90)
    print(f"  MULTI-TIMEFRAME ABLATION EXPERIMENT: {symbol}")
    print(f"  Data: {data_path}")
    print("=" * 90)

    with open(data_path) as f:
        full_data = json.load(f)

    scenarios = [
        ("Full MTF (M1, M5, M15, H1, H4)", ["M1", "M5", "M15", "H1", "H4"]),
        ("Without M5 (M1, M15, H1, H4)", ["M1", "M15", "H1", "H4"]),
        ("Without M5 & H4 (M1, M15, H1)", ["M1", "M15", "H1"]),
        ("Only M1 + M15 (Clean 2-TF)", ["M1", "M15"]),
        ("Pure M1 with Auto-Resampled M15", ["M1_ONLY_RESAMPLED"]),
    ]

    results_table = []

    for name, tfs in scenarios:
        cfg = Config()
        cfg.trading.symbol = symbol
        cfg.trading.symbols = [symbol]
        cfg.trading.enable_profit_compounding = True
        cfg.trading.backtest_apply_friction = True

        if tfs == ["M1_ONLY_RESAMPLED"]:
            m15_resampled = resample_m1_to_m15(full_data["M1"])
            test_data = {"M1": full_data["M1"], "M15": m15_resampled}
        else:
            test_data = {tf: full_data[tf] for tf in tfs if tf in full_data}

        engine = BacktestEngine(cfg, initial_balance=10000.0, symbol=symbol)
        res = engine.run(test_data)

        results_table.append({
            "Scenario": name,
            "PnL": res.get("total_pnl", 0.0),
            "Trades": res.get("total_trades", 0),
            "Wins": res.get("wins", 0),
            "Losses": res.get("losses", 0),
            "WinRate": res.get("win_rate", 0.0),
            "PF": res.get("profit_factor", 0.0),
            "MaxDD": res.get("max_drawdown_pct", 0.0),
        })

    print(f"{'Scenario':<36} | {'PnL ($)':>10} | {'Trades':>6} | {'Win Rate':>8} | {'PF':>5} | {'MaxDD':>7}")
    print("-" * 90)
    for r in results_table:
        print(f"{r['Scenario']:<36} | ${r['PnL']:>9.2f} | {r['Trades']:>6} | {r['WinRate']:>7.1f}% | {r['PF']:>5.2f} | {r['MaxDD']:>6.2f}%")
    print("-" * 90)
    return results_table


if __name__ == "__main__":
    nas_results = run_experiment_on_symbol("USTECH100M", "data/genuine_recent_nas100.json")
    print("\n")
    xau_results = run_experiment_on_symbol("XAUUSD", "data/genuine_recent_xauusd.json")
