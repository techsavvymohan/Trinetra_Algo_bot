"""Institutional Overfitting & Curve-Fitting Comprehensive Audit.

Tests 5 Essential Pillars of Quantitative Robustness:
1. Data Integrity & Sampling Distribution (Coverage check & density audit).
2. Walk-Forward Validation (WFV) & Walk-Forward Efficiency (WFE) (Pardo Criterion >= 50%).
3. Monte Carlo Path Resampling (15,000 iterations) for Tail Risk & Path Dependency.
4. Parameter Sensitivity & Cliff-Edge Analysis (Perturbations of ±10% to ±30%).
5. Calendar / Day-of-Week Rule Ablation (Friday filter & Tuesday cushion audit).
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.backtesting.validation import run_monte_carlo, run_walk_forward_validation

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

def run_audit():
    print("=" * 90)
    print("      INSTITUTIONAL QUANTITATIVE OVERFITTING & ROBUSTNESS AUDIT")
    print("=" * 90)

    # -------------------------------------------------------------
    # 1. DATA SAMPLING & COVERAGE AUDIT
    # -------------------------------------------------------------
    print("\n[PILLAR 1] DATA SAMPLING & DISTRIBUTION INTEGRITY")
    print("-" * 90)
    data_gold = load_stitched_xauusd()
    data_nas = load_stitched_nas100()

    for sym, d in [("XAUUSD (Gold)", data_gold), ("USTECH100M (Nasdaq)", data_nas)]:
        m1 = d["M1"]
        print(f"Dataset: {sym:<20} | Bars: {len(m1['time']):,} | Range: {m1['time'][0]} to {m1['time'][-1]}")

    # -------------------------------------------------------------
    # BASELINE BACKTEST EXECUTION
    # -------------------------------------------------------------
    cfg = Config.load()
    
    # Run Gold Baseline
    engine_gold = BacktestEngine(cfg, initial_balance=100000.0, symbol="XAUUSD")
    res_gold = engine_gold.run(data_gold)
    gold_pnls = [leg.pnl for c in engine_gold._clusters for leg in c.legs if hasattr(leg, 'pnl')]

    # Run Nasdaq Baseline
    engine_nas = BacktestEngine(cfg, initial_balance=100000.0, symbol="USTECH100M")
    res_nas = engine_nas.run(data_nas)
    nas_pnls = [leg.pnl for c in engine_nas._clusters for leg in c.legs if hasattr(leg, 'pnl')]

    print("\n[BASELINE PERFORMANCE SUMMARY]")
    print(f"  XAUUSD:   {len(gold_pnls)} trades | Win Rate: {res_gold.get('win_rate', 0):.1f}% | Net PnL: ${res_gold.get('total_pnl', 0):,.2f} | PF: {res_gold.get('profit_factor', 0):.2f}")
    print(f"  NAS100:   {len(nas_pnls)} trades | Win Rate: {res_nas.get('win_rate', 0):.1f}% | Net PnL: ${res_nas.get('total_pnl', 0):,.2f} | PF: {res_nas.get('profit_factor', 0):.2f}")

    # Check trade distribution by month
    print("\n[TRADE DISTRIBUTION BY MONTH]")
    def get_monthly_dist(engine):
        dist = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for c in engine._clusters:
            for leg in c.legs:
                dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                m = dt.strftime("%Y-%m")
                dist[m]["trades"] += 1
                if leg.pnl > 0:
                    dist[m]["wins"] += 1
                dist[m]["pnl"] += leg.pnl
        return dist

    dist_gold = get_monthly_dist(engine_gold)
    dist_nas = get_monthly_dist(engine_nas)

    all_months = sorted(set(list(dist_gold.keys()) + list(dist_nas.keys())))
    print(f"{'Month':<10} | {'XAU Trades':<11} | {'XAU WR':<8} | {'XAU PnL':<12} | {'NAS Trades':<11} | {'NAS WR':<8} | {'NAS PnL':<12}")
    print("-" * 88)
    for m in all_months:
        g = dist_gold[m]
        n = dist_nas[m]
        g_wr = (g['wins'] / g['trades'] * 100) if g['trades'] > 0 else 0.0
        n_wr = (n['wins'] / n['trades'] * 100) if n['trades'] > 0 else 0.0
        print(f"{m:<10} | {g['trades']:>11} | {g_wr:>7.1f}% | ${g['pnl']:>10,.2f} | {n['trades']:>11} | {n_wr:>7.1f}% | ${n['pnl']:>10,.2f}")

    # -------------------------------------------------------------
    # 2. WALK-FORWARD VALIDATION (WFV)
    # -------------------------------------------------------------
    print("\n[PILLAR 2] WALK-FORWARD VALIDATION (WFV) & EFFICIENCY (WFE)")
    print("-" * 90)
    wfv_windows_gold = [
        {"name": "W1 (Q1)", "is_start": "2026-01-01", "is_end": "2026-02-28", "oos_start": "2026-03-01", "oos_end": "2026-03-31"},
        {"name": "W2 (Apr)", "is_start": "2026-02-01", "is_end": "2026-03-31", "oos_start": "2026-04-01", "oos_end": "2026-04-30"},
        {"name": "W3 (May)", "is_start": "2026-03-01", "is_end": "2026-04-30", "oos_start": "2026-05-01", "oos_end": "2026-05-31"},
        {"name": "W4 (Jun)", "is_start": "2026-04-01", "is_end": "2026-05-31", "oos_start": "2026-06-01", "oos_end": "2026-06-30"},
        {"name": "W5 (Jul)", "is_start": "2026-05-01", "is_end": "2026-06-30", "oos_start": "2026-07-01", "oos_end": "2026-07-31"},
        {"name": "W6 (Aug)", "is_start": "2026-06-01", "is_end": "2026-07-31", "oos_start": "2026-08-01", "oos_end": "2026-08-31"},
        {"name": "W7 (Sep)", "is_start": "2026-07-01", "is_end": "2026-08-31", "oos_start": "2026-09-01", "oos_end": "2026-09-18"},
    ]

    print("Running Walk-Forward Validation for XAUUSD...")
    wfv_gold = run_walk_forward_validation(data_gold, cfg, symbol="XAUUSD", initial_balance=100000.0, windows=wfv_windows_gold)
    wfv_gold.print_dashboard()

    print("Running Walk-Forward Validation for NAS100 (Jun-Sep dense period)...")
    wfv_windows_nas = [
        {"name": "W1 (Jul)", "is_start": "2026-05-01", "is_end": "2026-06-30", "oos_start": "2026-07-01", "oos_end": "2026-07-31"},
        {"name": "W2 (Aug)", "is_start": "2026-06-01", "is_end": "2026-07-31", "oos_start": "2026-08-01", "oos_end": "2026-08-31"},
        {"name": "W3 (Sep)", "is_start": "2026-07-01", "is_end": "2026-08-31", "oos_start": "2026-09-01", "oos_end": "2026-09-18"},
    ]
    wfv_nas = run_walk_forward_validation(data_nas, cfg, symbol="USTECH100M", initial_balance=100000.0, windows=wfv_windows_nas)
    wfv_nas.print_dashboard()

    # -------------------------------------------------------------
    # 3. MONTE CARLO BOOTSTRAP (15,000 SIMULATIONS)
    # -------------------------------------------------------------
    print("\n[PILLAR 3] MONTE CARLO BOOTSTRAP RESAMPLING (15,000 RUNS)")
    print("-" * 90)
    mc_gold = run_monte_carlo(gold_pnls, initial_capital=100000.0, num_sims=15000)
    mc_gold.print_dashboard("MONTE CARLO EMPIRICAL STRESS TEST — XAUUSD")

    mc_nas = run_monte_carlo(nas_pnls, initial_capital=100000.0, num_sims=15000)
    mc_nas.print_dashboard("MONTE CARLO EMPIRICAL STRESS TEST — NAS100")

    # Combined Portfolio Monte Carlo
    combined_pnls = gold_pnls + nas_pnls
    mc_combined = run_monte_carlo(combined_pnls, initial_capital=100000.0, num_sims=15000)
    mc_combined.print_dashboard("MONTE CARLO EMPIRICAL STRESS TEST — DUAL-ENGINE PORTFOLIO")

    # -------------------------------------------------------------
    # 4. PARAMETER SENSITIVITY & CLIFF-EDGE ANALYSIS
    # -------------------------------------------------------------
    print("\n[PILLAR 4] PARAMETER SENSITIVITY & CLIFF-EDGE ANALYSIS")
    print("-" * 90)

    # A. Gold Displacement ATR Multiplier Sensitivity (Base: 0.60)
    print("\n>>> Sensitivity A: Gold Displacement ATR Multiplier (Base: 0.60)")
    for mult in [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80]:
        c = Config.load()
        c.trading.xau_displacement_atr_mult = mult
        eng = BacktestEngine(c, initial_balance=100000.0, symbol="XAUUSD")
        r = eng.run(data_gold)
        print(f"  ATR Mult: {mult:.2f} | Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Net PnL: ${r.get('total_pnl', 0):>10,.2f} | MaxDD: {r.get('max_drawdown_pct', 0):>5.2f}%")

    # B. Gold Conviction Scale A+ Sensitivity (Base: 2.60)
    print("\n>>> Sensitivity B: Gold Conviction Scale A+ (Base: 2.60)")
    for scale in [1.00, 1.50, 2.00, 2.60, 3.00, 3.50]:
        c = Config.load()
        c.trading.conviction_scale_a_plus = scale
        eng = BacktestEngine(c, initial_balance=100000.0, symbol="XAUUSD")
        r = eng.run(data_gold)
        print(f"  A+ Scale: {scale:.2f}x | Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Net PnL: ${r.get('total_pnl', 0):>10,.2f} | MaxDD: {r.get('max_drawdown_pct', 0):>5.2f}%")

    # C. Gold London Close Cutoff Minute Sensitivity (Base: 14:45)
    print("\n>>> Sensitivity C: Gold London Close Cutoff Time (Base: 14:45 UTC)")
    for cutoff_min in [0, 15, 30, 45]:
        c = Config.load()
        c.trading.xau_london_close_cutoff_hour = 14
        c.trading.xau_london_close_cutoff_min = cutoff_min
        eng = BacktestEngine(c, initial_balance=100000.0, symbol="XAUUSD")
        r = eng.run(data_gold)
        print(f"  Cutoff: 14:{cutoff_min:02d} | Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Net PnL: ${r.get('total_pnl', 0):>10,.2f} | MaxDD: {r.get('max_drawdown_pct', 0):>5.2f}%")
    for cutoff_min in [0, 30]:
        c = Config.load()
        c.trading.xau_london_close_cutoff_hour = 15
        c.trading.xau_london_close_cutoff_min = cutoff_min
        eng = BacktestEngine(c, initial_balance=100000.0, symbol="XAUUSD")
        r = eng.run(data_gold)
        print(f"  Cutoff: 15:{cutoff_min:02d} | Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Net PnL: ${r.get('total_pnl', 0):>10,.2f} | MaxDD: {r.get('max_drawdown_pct', 0):>5.2f}%")

    # D. Nasdaq Breakeven Trigger R Sensitivity (Base: 1.00R)
    print("\n>>> Sensitivity D: Nasdaq Breakeven Trigger R (Base: 1.00R)")
    for be_r in [0.60, 0.80, 1.00, 1.20, 1.40, 1.50]:
        c = Config.load()
        c.trading.nas_breakeven_trigger_r = be_r
        eng = BacktestEngine(c, initial_balance=100000.0, symbol="USTECH100M")
        r = eng.run(data_nas)
        print(f"  BE Trigger: {be_r:.2f}R | Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Net PnL: ${r.get('total_pnl', 0):>10,.2f} | MaxDD: {r.get('max_drawdown_pct', 0):>5.2f}%")

    # E. Nasdaq Stagnation Bars Sensitivity (Base: 25 bars)
    print("\n>>> Sensitivity E: Nasdaq Stagnation Exit Bars (Base: 25 bars)")
    for stag in [15, 20, 25, 30, 45, 60, 0]:
        c = Config.load()
        c.trading.nas_stagnation_bars = stag
        eng = BacktestEngine(c, initial_balance=100000.0, symbol="USTECH100M")
        r = eng.run(data_nas)
        tag = f"{stag} bars" if stag > 0 else "DISABLED"
        print(f"  Stagnation: {tag:>9} | Trades: {r.get('total_trades', 0):>3} | WinRate: {r.get('win_rate', 0):>5.1f}% | Net PnL: ${r.get('total_pnl', 0):>10,.2f} | MaxDD: {r.get('max_drawdown_pct', 0):>5.2f}%")

    # -------------------------------------------------------------
    # 5. CALENDAR & DAY-OF-WEEK RULE ABLATION
    # -------------------------------------------------------------
    print("\n[PILLAR 5] CALENDAR & DAY-OF-WEEK RULE ABLATION")
    print("-" * 90)

    # Test 1: What happens if Friday trading is enabled on Gold?
    print(">>> Ablation 1: Gold Friday Trading Re-Enabled (xau_friday_trade_enabled = True)")
    c_fri = Config.load()
    c_fri.trading.xau_friday_trade_enabled = True
    eng_fri = BacktestEngine(c_fri, initial_balance=100000.0, symbol="XAUUSD")
    r_fri = eng_fri.run(data_gold)
    
    # Filter trades that opened on Friday
    fri_trades = []
    for cl in eng_fri._clusters:
        for leg in cl.legs:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if dt.weekday() == 4:
                fri_trades.append(leg)
    fri_wins = [t for t in fri_trades if t.pnl > 0]
    fri_pnl = sum(t.pnl for t in fri_trades)
    fri_wr = (len(fri_wins) / len(fri_trades) * 100) if fri_trades else 0.0

    print(f"  Baseline (Friday OFF): Trades: {res_gold.get('total_trades', 0)} | WinRate: {res_gold.get('win_rate', 0):.1f}% | Net PnL: ${res_gold.get('total_pnl', 0):,.2f}")
    print(f"  Ablation (Friday ON):  Trades: {r_fri.get('total_trades', 0)} | WinRate: {r_fri.get('win_rate', 0):.1f}% | Net PnL: ${r_fri.get('total_pnl', 0):,.2f}")
    print(f"  --> Isolated Friday Impact: {len(fri_trades)} trades | WinRate: {fri_wr:.1f}% | Net PnL: ${fri_pnl:,.2f}")

    # Test 2: What happens if Tuesday Special Treatment is Removed?
    print("\n>>> Ablation 2: Tuesday Special Risk Scale Removed (tuesday_reduced_risk = False)")
    c_tue = Config.load()
    c_tue.trading.tuesday_reduced_risk = False
    c_tue.trading.tuesday_risk_scale = 1.00
    c_tue.trading.tuesday_breakeven_trigger_r = 1.50  # Same as normal Gold BE trigger
    eng_tue = BacktestEngine(c_tue, initial_balance=100000.0, symbol="XAUUSD")
    r_tue = eng_tue.run(data_gold)
    print(f"  Baseline (Tuesday Protected): Trades: {res_gold.get('total_trades', 0)} | WinRate: {res_gold.get('win_rate', 0):.1f}% | Net PnL: ${res_gold.get('total_pnl', 0):,.2f} | MaxDD: {res_gold.get('max_drawdown_pct', 0):.2f}%")
    print(f"  Ablation (Tuesday Standard):  Trades: {r_tue.get('total_trades', 0)} | WinRate: {r_tue.get('win_rate', 0):.1f}% | Net PnL: ${r_tue.get('total_pnl', 0):,.2f} | MaxDD: {r_tue.get('max_drawdown_pct', 0):.2f}%")

    print("\n" + "=" * 90)
    print("      AUDIT EXECUTION COMPLETE")
    print("=" * 90)

if __name__ == "__main__":
    run_audit()
