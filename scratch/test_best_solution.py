"""Verify the Best Comprehensive Solution Across XAUUSD + NAS100 (Jan 1 - Sep 18, 2026).

Pillars of the Best Solution:
1. NAS100: Centered on the robust parameter plateau (BE 1.25R, Stagnation 40 bars, Expiry 15 bars, Afternoon 15:45-20:00 UTC).
2. XAUUSD: Principled Friday rule (skip Friday London 07:45-09:30 UTC, 0.50x risk on Friday NY, exit by 15:00 UTC).
3. Risk: Dynamic Fractional Kelly maintained without cliff-edge parameters.
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

def to_naive_dt(t):
    if isinstance(t, str):
        t_clean = t.replace("T", " ")
        if "+" in t_clean:
            t_clean = t_clean.split("+")[0]
        if "Z" in t_clean:
            t_clean = t_clean.replace("Z", "")
        return datetime.fromisoformat(t_clean)
    elif hasattr(t, "replace"):
        return t.replace(tzinfo=None)
    return t

def load_stitched_xauusd():
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        d1 = json.load(f)["M1"]
    with open("data/genuine_recent_xauusd.json") as f:
        d2 = json.load(f)["M1"]

    t1 = [to_naive_dt(t) for t in d1["time"]]
    split_dt = datetime(2026, 9, 1, 0, 0, 0)
    end_dt = datetime(2026, 9, 18, 23, 59, 59)
    mask1 = [t < split_dt for t in t1]

    stitched = {
        "time": [t for t, k in zip(t1, mask1) if k],
        "open": [v for v, k in zip(d1["open"], mask1) if k],
        "high": [v for v, k in zip(d1["high"], mask1) if k],
        "low": [v for v, k in zip(d1["low"], mask1) if k],
        "close": [v for v, k in zip(d1["close"], mask1) if k],
        "tick_volume": [v for v, k in zip(d1["tick_volume"], mask1) if k],
        "spread": [v for v, k in zip(d1.get("spread", [0.12]*len(t1)), mask1) if k],
    }

    t2 = [to_naive_dt(t) for t in d2["time"]]
    mask2 = [(t >= split_dt and t <= end_dt) for t in t2]

    stitched["time"].extend([t for t, k in zip(t2, mask2) if k])
    stitched["open"].extend([v for v, k in zip(d2["open"], mask2) if k])
    stitched["high"].extend([v for v, k in zip(d2["high"], mask2) if k])
    stitched["low"].extend([v for v, k in zip(d2["low"], mask2) if k])
    stitched["close"].extend([v for v, k in zip(d2["close"], mask2) if k])
    stitched["tick_volume"].extend([v for v, k in zip(d2.get("tick_volume", d2.get("volume", [100]*len(t2))), mask2) if k])
    stitched["spread"].extend([v for v, k in zip(d2.get("spread", [0.12]*len(t2)), mask2) if k])

    return {"M1": stitched}

def load_stitched_nas100():
    with open("data/genuine_jan_aug_2026_nas100.json") as f:
        d1 = json.load(f)["M1"]
    with open("data/genuine_recent_nas100.json") as f:
        d2 = json.load(f)["M1"]

    t1 = [to_naive_dt(t) for t in d1["time"]]
    split_dt = datetime(2026, 8, 18, 0, 0, 0)
    end_dt = datetime(2026, 9, 18, 23, 59, 59)
    mask1 = [t < split_dt for t in t1]

    stitched = {
        "time": [t for t, k in zip(t1, mask1) if k],
        "open": [v for v, k in zip(d1["open"], mask1) if k],
        "high": [v for v, k in zip(d1["high"], mask1) if k],
        "low": [v for v, k in zip(d1["low"], mask1) if k],
        "close": [v for v, k in zip(d1["close"], mask1) if k],
        "tick_volume": [v for v, k in zip(d1["tick_volume"], mask1) if k],
        "spread": [v for v, k in zip(d1.get("spread", [1.0]*len(t1)), mask1) if k],
    }

    t2 = [to_naive_dt(t) for t in d2["time"]]
    mask2 = [(t >= split_dt and t <= end_dt) for t in t2]

    stitched["time"].extend([t for t, k in zip(t2, mask2) if k])
    stitched["open"].extend([v for v, k in zip(d2["open"], mask2) if k])
    stitched["high"].extend([v for v, k in zip(d2["high"], mask2) if k])
    stitched["low"].extend([v for v, k in zip(d2["low"], mask2) if k])
    stitched["close"].extend([v for v, k in zip(d2["close"], mask2) if k])
    stitched["tick_volume"].extend([v for v, k in zip(d2.get("tick_volume", d2.get("volume", [100]*len(t2))), mask2) if k])
    stitched["spread"].extend([v for v, k in zip(d2.get("spread", [1.0]*len(t2)), mask2) if k])

    return {"M1": stitched}

def main():
    print("=" * 80)
    print("TESTING BEST COMPREHENSIVE SOLUTION (ANTIFRAGILE PORTFOLIO)")
    print("=" * 80)

    data_gold = load_stitched_xauusd()
    data_nas = load_stitched_nas100()

    # Configure Best Solution Parameters
    cfg = Config.load()
    
    # 1. NAS100 Antifragile Plateau Configuration
    cfg.trading.nas_breakeven_trigger_r = 1.25      # Centered on 1.20R-1.30R plateau
    cfg.trading.nas_stagnation_bars = 40           # Centered on 35-45 bar plateau
    cfg.trading.nas_fvg_expiry_bars = 15           # 15 M1 bars patience for retest
    cfg.trading.nas_session_start_hour = 15        # Focus on pristine afternoon continuation
    cfg.trading.nas_killzone_morning_start_min = 45 # 15:45 UTC
    cfg.trading.nas_london_close_pause_start_hour = 24 # no pause needed after 15:45

    # Run NAS100 with Best Solution
    eng_nas = BacktestEngine(cfg, initial_balance=100000.0, symbol="USTECH100M")
    res_nas = eng_nas.run(data_nas)

    # 2. XAUUSD Flagship Configuration
    eng_gold = BacktestEngine(cfg, initial_balance=100000.0, symbol="XAUUSD")
    res_gold = eng_gold.run(data_gold)

    # Print Results
    print("\n[OPTIMIZED NAS100 RESULTS]")
    print(f"  Trades:        {res_nas.get('total_trades', 0)}")
    print(f"  Win Rate:      {res_nas.get('win_rate', 0):.1f}%")
    print(f"  Net PnL:       ${res_nas.get('total_pnl', 0):,.2f}")
    print(f"  Profit Factor: {res_nas.get('profit_factor', 0):.2f}")
    print(f"  Max Drawdown:  {res_nas.get('max_drawdown_pct', 0):.2f}%")

    print("\n[FLAGSHIP XAUUSD RESULTS]")
    print(f"  Trades:        {res_gold.get('total_trades', 0)}")
    print(f"  Win Rate:      {res_gold.get('win_rate', 0):.1f}%")
    print(f"  Net PnL:       ${res_gold.get('total_pnl', 0):,.2f}")
    print(f"  Profit Factor: {res_gold.get('profit_factor', 0):.2f}")
    print(f"  Max Drawdown:  {res_gold.get('max_drawdown_pct', 0):.2f}%")

    # Monthly breakdown for NAS100
    nas_monthly = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for c in eng_nas._clusters:
        for leg in c.legs:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            m = dt.strftime("%Y-%m")
            nas_monthly[m]["trades"] += 1
            if leg.pnl > 0:
                nas_monthly[m]["wins"] += 1
            nas_monthly[m]["pnl"] += leg.pnl

    print("\n[OPTIMIZED NAS100 MONTHLY BREAKDOWN]")
    print(f"{'Month':<10} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL':<12}")
    print("-" * 50)
    for m in sorted(nas_monthly.keys()):
        tr = nas_monthly[m]["trades"]
        wr = (nas_monthly[m]["wins"] / tr * 100) if tr > 0 else 0.0
        pnl = nas_monthly[m]["pnl"]
        print(f"{m:<10} | {tr:>8} | {wr:>9.1f}% | ${pnl:>10,.2f}")

    total_combined_pnl = res_gold.get('total_pnl', 0) + res_nas.get('total_pnl', 0)
    print("\n" + "=" * 80)
    print(f"TOTAL DUAL-ENGINE PORTFOLIO NET PNL: ${total_combined_pnl:,.2f}")
    print("=" * 80)

if __name__ == "__main__":
    main()
