"""Targeted Diagnostic Script to Find the Best Solution for Overfitting.

1. Diagnose NAS100 September losses (Inspect all 19 trades, exit reasons, time of day).
2. Diagnose NAS100 Jan-May trade scarcity (Why only 4 trades? Session filter vs H1 trend vs FVG).
3. Diagnose Gold Friday trades (Why did Friday lose -$48k when re-enabled? Exit reasons, times).
4. Test candidate solutions:
   - NAS100 plateau parameters (BE 1.20R - 1.30R, Stagnation 35-45 bars).
   - NAS100 September regime filter (e.g., ADX/ATR trend strength or session hours).
   - Gold Friday dynamic risk & early cutoff (e.g., 0.5x risk, 13:30 UTC cutoff).
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
    cfg = Config.load()
    data_nas = load_stitched_nas100()
    data_gold = load_stitched_xauusd()

    print("=" * 80)
    print("1. DIAGNOSING NAS100 SEPTEMBER TRADES")
    print("=" * 80)
    engine_nas = BacktestEngine(cfg, initial_balance=100000.0, symbol="USTECH100M")
    res_nas = engine_nas.run(data_nas)

    sept_trades = []
    for c in engine_nas._clusters:
        for leg in c.legs:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if dt.month == 9 and dt.year == 2026:
                sept_trades.append((dt, leg.direction, leg.entry_price, leg.exit_price, leg.pnl, leg.exit_reason))

    print(f"Total September Trades: {len(sept_trades)}")
    for t in sept_trades:
        print(f"  {t[0].strftime('%Y-%m-%d %H:%M')} | {t[1]:<4} | Entry: {t[2]:.2f} | Exit: {t[3]:.2f} | PnL: ${t[4]:>8.2f} | Reason: {t[5]}")

    print("\n" + "=" * 80)
    print("2. DIAGNOSING NAS100 JAN-MAY LOW TRADE COUNT")
    print("=" * 80)
    # Check what happens if we test Jan-May without session restrictions or H1 trend filter
    for test_name, mod_cfg in [
        ("Base (Afternoon only 15:45-20:00, H1 Trend=True)", cfg),
        ("Allow Full NY Session (13:35-20:00, H1 Trend=True)", lambda: None),
        ("Afternoon only, H1 Trend=False", lambda: None),
        ("Full NY Session, H1 Trend=False", lambda: None),
    ]:
        c = Config.load()
        if "Full NY Session" in test_name:
            c.trading.nas_session_start_hour = 13
            c.trading.nas_killzone_morning_start_min = 35
            c.trading.nas_london_close_pause_start_hour = 24  # disable pause
        if "H1 Trend=False" in test_name:
            c.trading.nas_require_h1_trend = False
        
        # Test on Jan-May only
        dt_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        dt_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)
        eng = BacktestEngine(c, initial_balance=100000.0, symbol="USTECH100M", start_date=dt_start, end_date=dt_end)
        r = eng.run(data_nas)
        print(f"  {test_name:<50} -> Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Net PnL: ${r.get('total_pnl', 0):>10,.2f}")

    print("\n" + "=" * 80)
    print("3. DIAGNOSING GOLD FRIDAY TRADES & TESTING SOLUTIONS")
    print("=" * 80)
    # What caused the Friday losses?
    c_fri = Config.load()
    c_fri.trading.xau_friday_trade_enabled = True
    eng_fri = BacktestEngine(c_fri, initial_balance=100000.0, symbol="XAUUSD")
    r_fri = eng_fri.run(data_gold)

    fri_trades = []
    for c in eng_fri._clusters:
        for leg in c.legs:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if dt.weekday() == 4:
                fri_trades.append((dt, leg.direction, leg.entry_price, leg.exit_price, leg.pnl, leg.exit_reason))

    print(f"Total Friday Trades: {len(fri_trades)}")
    for t in fri_trades:
        print(f"  {t[0].strftime('%Y-%m-%d %H:%M')} | {t[1]:<4} | Entry: {t[2]:.2f} | Exit: {t[3]:.2f} | PnL: ${t[4]:>8.2f} | Reason: {t[5]}")

    # Now let's test Friday with earlier cutoff (e.g. 13:00 UTC vs 14:00 UTC) and reduced risk
    print("\nTesting Friday Solutions:")
    for friday_cutoff_hour in [12, 13, 14]:
        for friday_risk_scale in [0.30, 0.50, 0.70]:
            # Simulate impact on Friday trades
            filtered_trades = [t for t in fri_trades if t[0].hour < friday_cutoff_hour]
            net_pnl = sum(t[4] * friday_risk_scale for t in filtered_trades)
            wins = [t for t in filtered_trades if t[4] > 0]
            wr = (len(wins) / len(filtered_trades) * 100) if filtered_trades else 0.0
            print(f"  Cutoff < {friday_cutoff_hour}:00 UTC | Risk: {friday_risk_scale:.2f}x | Trades: {len(filtered_trades):>2} | WR: {wr:>5.1f}% | Friday PnL: ${net_pnl:>9,.2f}")

    print("\n" + "=" * 80)
    print("4. TESTING BEST SOLUTION MATRIX FOR NAS100 & PORTFOLIO")
    print("=" * 80)
    # Test combinations of BE trigger (1.20R, 1.30R), Stagnation (35, 40, 45), and September fix
    for be_r in [1.10, 1.20, 1.25, 1.30]:
        for stag in [30, 35, 40, 45]:
            c_test = Config.load()
            c_test.trading.nas_breakeven_trigger_r = be_r
            c_test.trading.nas_stagnation_bars = stag
            eng = BacktestEngine(c_test, initial_balance=100000.0, symbol="USTECH100M")
            r = eng.run(data_nas)
            # check sept pnl
            s_pnl = sum(leg.pnl for cl in eng._clusters for leg in cl.legs if hasattr(leg, 'open_time') and (leg.open_time.month if hasattr(leg.open_time, 'month') else datetime.fromisoformat(str(leg.open_time)).month) == 9)
            print(f"  BE: {be_r:.2f}R | Stag: {stag}b | Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Total PnL: ${r.get('total_pnl', 0):>9,.2f} | Sept PnL: ${s_pnl:>8,.2f} | MaxDD: {r.get('max_drawdown_pct', 0):>5.2f}%")

if __name__ == "__main__":
    main()
