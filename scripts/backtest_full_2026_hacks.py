#!/usr/bin/env python3
"""
Full 2026 Institutional Backtest: January 1, 2026 - September 24, 2026
DOES NOT MODIFY ANY PRODUCTION FILES.
Runs comparison on genuine broker data (over 500,000 M1 bars combined):
1. Baseline (Current Production Bot)
2. With Hack (2.2x ATR Stop-Hunt Buffer + 50% Tranche @ 1.2R)
"""

import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import copy

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection, ExitReason

FULL_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 24, 23, 59, 59, tzinfo=timezone.utc)


def load_full_data():
    xau_path = BASE_DIR / "data" / "full_2026_xauusd.json"
    nas_path = BASE_DIR / "data" / "full_2026_nas100.json"
    print(f"Reading {xau_path}...")
    with open(xau_path, "r", encoding="utf-8") as f:
        xau_data = json.load(f)
    print(f"Reading {nas_path}...")
    with open(nas_path, "r", encoding="utf-8") as f:
        nas_data = json.load(f)
    return xau_data, nas_data


def extract_trades_and_stats(engine, res):
    trades = []
    if hasattr(engine, "_clusters"):
        for cluster in engine._clusters:
            for leg in cluster.legs:
                if leg.status == TradeStatus.CLOSED and leg.exit_price:
                    dt_open = (
                        leg.open_time
                        if isinstance(leg.open_time, datetime)
                        else datetime.fromisoformat(str(leg.open_time))
                    )
                    dt_close = (
                        leg.close_time
                        if isinstance(leg.close_time, datetime)
                        else (datetime.fromisoformat(str(leg.close_time)) if leg.close_time else None)
                    )
                    pnl = getattr(leg, "pnl", 0.0) or 0.0
                    trades.append({
                        "open_time": dt_open,
                        "close_time": dt_close,
                        "symbol": getattr(leg, "symbol", engine.symbol),
                        "direction": getattr(leg.direction, "name", str(leg.direction)),
                        "entry_price": getattr(leg, "entry_price", 0.0),
                        "exit_price": getattr(leg, "exit_price", 0.0),
                        "lots": getattr(leg, "lot_size", 0.0),
                        "pnl": pnl,
                        "exit_reason": getattr(leg.exit_reason, "name", str(leg.exit_reason)),
                    })
    trades.sort(key=lambda t: t["open_time"])
    pnl = res.get("total_pnl", sum(t["pnl"] for t in trades))
    wins = sum(1 for t in trades if t["pnl"] > 0.01)
    losses = sum(1 for t in trades if t["pnl"] < -0.01)
    wr = (wins / len(trades) * 100) if trades else 0.0
    pf = res.get("profit_factor", 0.0)
    max_dd = res.get("max_drawdown_pct", res.get("max_drawdown", 0.0))
    return {
        "pnl": pnl,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "profit_factor": pf,
        "max_dd": max_dd,
    }


def run_full_year_sim(name: str, xau_data: dict, nas_data: dict,
                      atr_buffer_mult: float = 0.0,
                      t1_pct: float = 25.0,
                      t1_r: float = 1.5):
    print(f"\n================================================================================")
    print(f"  EXECUTING FULL 2026 RUN: {name}")
    print(f"  Evaluation Window: Jan 1, 2026 - Sep 24, 2026 (Both XAUUSD & USTECH100M)")
    print(f"================================================================================")
    
    results = {}
    for sym, raw_data in [("XAUUSD", xau_data), ("USTECH100M", nas_data)]:
        print(f"  -> Processing {sym} ({len(raw_data['M1']['time'])} M1 bars)...")
        cfg = Config.load()
        cfg.trading.backtest_initial_balance = 10000.0
        cfg.trading.backtest_apply_friction = True
        cfg.trading.backtest_commission_per_lot = 6.0
        cfg.trading.partial_tp_tranche1_pct = t1_pct
        cfg.trading.partial_tp_tranche1_r = t1_r

        engine = BacktestEngine(
            cfg,
            initial_balance=10000.0,
            symbol=sym,
            start_date=FULL_START,
            end_date=FULL_END,
        )

        # In-memory hook for Hack 1 (Stop-Hunt ATR Buffer)
        orig_detect = engine.trigger.detect_xau_scalp_sequence
        def patched_detect(*args, **kwargs):
            seq = orig_detect(*args, **kwargs)
            if seq and atr_buffer_mult > 0.0:
                m1_atr = kwargs.get("m1_atr", 1.0)
                ep = seq["entry_price"]
                direction = seq["direction"]
                pad = max(m1_atr * atr_buffer_mult, 4.0 if ep > 5000 else 0.8)
                if direction == TradeDirection.BUY:
                    new_sl = seq["sweep_low"] - pad
                    risk = ep - new_sl
                    if risk > 0:
                        seq["sl_price"] = round(new_sl, 1 if ep > 5000 else 2)
                        seq["tp_price"] = round(ep + (risk * kwargs.get("target_r", 2.0)), 1 if ep > 5000 else 2)
                else:
                    new_sl = seq["sweep_high"] + pad
                    risk = new_sl - ep
                    if risk > 0:
                        seq["sl_price"] = round(new_sl, 1 if ep > 5000 else 2)
                        seq["tp_price"] = round(ep - (risk * kwargs.get("target_r", 2.0)), 1 if ep > 5000 else 2)
            return seq

        if atr_buffer_mult > 0.0:
            engine.trigger.detect_xau_scalp_sequence = patched_detect

        raw_copy = copy.deepcopy(raw_data)
        res = engine.run(raw_copy)
        results[sym] = extract_trades_and_stats(engine, res)
        pnl = results[sym]["pnl"]
        print(f"     [DONE] {sym}: Net PnL = {'+' if pnl >= 0 else ''}${pnl:,.2f} | Trades = {len(results[sym]['trades'])} | WR = {results[sym]['win_rate']:.1f}% | MaxDD = {results[sym]['max_dd']:.2f}%")

    comb_trades = sorted(results["XAUUSD"]["trades"] + results["USTECH100M"]["trades"], key=lambda t: t["open_time"])
    tot_pnl = sum(t["pnl"] for t in comb_trades)
    tot_wins = sum(1 for t in comb_trades if t["pnl"] > 0.01)
    tot_losses = sum(1 for t in comb_trades if t["pnl"] < -0.01)
    tot_wr = (tot_wins / len(comb_trades) * 100) if comb_trades else 0.0

    # Monthly breakdown
    monthly = defaultdict(lambda: {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0})
    for t in comb_trades:
        m_key = t["open_time"].strftime("%Y-%m")
        monthly[m_key]["pnl"] += t["pnl"]
        monthly[m_key]["trades"] += 1
        if t["pnl"] > 0.01:
            monthly[m_key]["wins"] += 1
        elif t["pnl"] < -0.01:
            monthly[m_key]["losses"] += 1

    return {
        "name": name,
        "pnl": tot_pnl,
        "trades": comb_trades,
        "wins": tot_wins,
        "losses": tot_losses,
        "win_rate": tot_wr,
        "by_sym": results,
        "monthly": dict(monthly),
    }


def main():
    print("=" * 80)
    print("  TRINETRA QUANT PROFIT DIGGER BOT: FULL 2026 BACKTEST ENGINE")
    print("  Period: January 1, 2026 - September 24, 2026 (9 Full Months)")
    print("  Zero production files modified.")
    print("=" * 80)

    xau_data, nas_data = load_full_data()

    # 1. Baseline
    base_res = run_full_year_sim(
        name="1. Baseline (Current Production)",
        xau_data=xau_data,
        nas_data=nas_data,
        atr_buffer_mult=0.0,
        t1_pct=25.0,
        t1_r=1.5,
    )

    # 2. Hack 1 alone (2.2x ATR Buffer, standard tranches)
    hack1_res = run_full_year_sim(
        name="2. Hack 1 Alone (2.2x ATR Buffer, Standard Tranches)",
        xau_data=xau_data,
        nas_data=nas_data,
        atr_buffer_mult=2.2,
        t1_pct=25.0,
        t1_r=1.5,
    )

    # 3. With Hack 1 + 2 (2.2x ATR Buffer + 50% Tranche @ 1.2R)
    hack_res = run_full_year_sim(
        name="3. Hack 1 + 2 (2.2x ATR Buffer + 50% Tranche @ 1.2R)",
        xau_data=xau_data,
        nas_data=nas_data,
        atr_buffer_mult=2.2,
        t1_pct=50.0,
        t1_r=1.2,
    )

    # Final Combined Comparison
    print("\n" + "=" * 80)
    print("  COMPLETE 2026 PERFORMANCE COMPARISON (JAN 1 - SEP 24, 2026)")
    print("=" * 80)
    print(f"  {'Metric':<20} | {'Baseline (Current)':<18} | {'Hack 1 Alone':<18} | {'Hack 1 + Hack 2':<18}")
    print("  " + "-" * 82)
    print(f"  {'Net PnL ($)':<20} | {'+' if base_res['pnl'] >= 0 else ''}${base_res['pnl']:<17,.2f} | {'+' if hack1_res['pnl'] >= 0 else ''}${hack1_res['pnl']:<17,.2f} | {'+' if hack_res['pnl'] >= 0 else ''}${hack_res['pnl']:<17,.2f}")
    print(f"  {'Final Balance ($)':<20} | ${10000.0 + base_res['pnl']:<17,.2f} | ${10000.0 + hack1_res['pnl']:<17,.2f} | ${10000.0 + hack_res['pnl']:<17,.2f}")
    print(f"  {'Total Trades':<20} | {len(base_res['trades']):<18} | {len(hack1_res['trades']):<18} | {len(hack_res['trades']):<18}")
    print(f"  {'Win Rate (%)':<20} | {base_res['win_rate']:<17.1f}% | {hack1_res['win_rate']:<17.1f}% | {hack_res['win_rate']:<17.1f}%")
    print(f"  {'Wins / Losses':<20} | {base_res['wins']}W / {base_res['losses']}L{' ':<10} | {hack1_res['wins']}W / {hack1_res['losses']}L{' ':<10} | {hack_res['wins']}W / {hack_res['losses']}L{' ':<10}")
    print("=" * 80)

    # Monthly breakdown comparison
    all_months = sorted(set(list(base_res["monthly"].keys()) + list(hack_res["monthly"].keys())))
    print("\n" + "=" * 80)
    print("  MONTH-BY-MONTH PROFIT BREAKDOWN (2026)")
    print("=" * 80)
    print(f"  {'Month':<10} | {'Base PnL ($)':<15} | {'Base WR':<10} | {'Hack PnL ($)':<15} | {'Hack WR':<10} | {'Monthly Gain'}")
    print("  " + "-" * 78)
    for m in all_months:
        b_m = base_res["monthly"].get(m, {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0})
        h_m = hack_res["monthly"].get(m, {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0})
        b_wr = (b_m["wins"] / b_m["trades"] * 100) if b_m["trades"] else 0.0
        h_wr = (h_m["wins"] / h_m["trades"] * 100) if h_m["trades"] else 0.0
        m_diff = h_m["pnl"] - b_m["pnl"]
        print(f"  {m:<10} | {'+' if b_m['pnl'] >= 0 else ''}${b_m['pnl']:<14,.2f} | {b_wr:>7.1f}%  | {'+' if h_m['pnl'] >= 0 else ''}${h_m['pnl']:<14,.2f} | {h_wr:>7.1f}%  | {'+' if m_diff >= 0 else ''}${m_diff:,.2f}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
