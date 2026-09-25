#!/usr/bin/env python3
"""
Diagnostic Backtest Simulator: Sep 21 - Sep 25, 2026
DOES NOT MODIFY ANY PRODUCTION FILES.
Tests proposed institutional hacks in-memory on genuine broker data:
- Hack 1: Stop-Hunt ATR Volatility Buffer on SL
- Hack 2: Front-Loaded Chop-Regime Tranche (50% @ 1.2R)
- Hack 3: Combination (Hack 1 + Hack 2)
- Hack 4: Early Adverse Momentum Bailout (-0.35R cut)
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
import copy

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection, ExitReason
from xauusd_bot.indicators.atr import atr

SEP_START = datetime(2026, 9, 21, 0, 0, 0, tzinfo=timezone.utc)
SEP_END = datetime(2026, 9, 25, 23, 59, 59, tzinfo=timezone.utc)


def load_cached_data():
    xau_path = BASE_DIR / "data" / "fetched_sep21_25_2026_xauusd.json"
    nas_path = BASE_DIR / "data" / "fetched_sep21_25_2026_nas100.json"
    with open(xau_path, "r", encoding="utf-8") as f:
        xau_data = json.load(f)
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
                        "direction": getattr(leg.direction, "name", str(leg.direction)),
                        "entry_price": getattr(leg, "entry_price", 0.0),
                        "exit_price": getattr(leg, "exit_price", 0.0),
                        "sl_price": getattr(leg, "sl_price", 0.0),
                        "tp_price": getattr(leg, "tp_price", 0.0),
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


def run_experiment(name: str, xau_data: dict, nas_data: dict,
                   atr_buffer_mult: float = 0.0,
                   t1_pct: float = 25.0,
                   t1_r: float = 1.5,
                   early_cut_r: float = 0.0):
    """Run backtest for both symbols with specific parameter variations in memory."""
    results = {}
    for sym, raw_data in [("XAUUSD", xau_data), ("USTECH100M", nas_data)]:
        cfg = Config.load()
        cfg.trading.backtest_initial_balance = 10000.0
        cfg.trading.backtest_apply_friction = True
        cfg.trading.backtest_commission_per_lot = 6.0
        cfg.trading.partial_tp_tranche1_pct = t1_pct
        cfg.trading.partial_tp_tranche1_r = t1_r

        # Create engine
        engine = BacktestEngine(
            cfg,
            initial_balance=10000.0,
            symbol=sym,
            start_date=SEP_START,
            end_date=SEP_END,
        )

        # In-memory hook for Hack 1 (Stop-Hunt ATR Buffer)
        orig_detect = engine.trigger.detect_xau_scalp_sequence
        def patched_detect(*args, **kwargs):
            seq = orig_detect(*args, **kwargs)
            if seq and atr_buffer_mult > 0.0:
                m1_d = kwargs.get("m1_data")
                m1_atr = kwargs.get("m1_atr", 1.0)
                ep = seq["entry_price"]
                direction = seq["direction"]
                # Dynamic ATR buffer: Nasdaq ATR or Gold ATR scaled
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

        # In-memory hook for Hack 4 (Early Adverse Cut)
        if early_cut_r < 0.0:
            orig_manage_exits = engine._manage_backtest_exits
            def patched_manage_exits(cluster, data_all, idx, price):
                # Check adverse momentum: if open for >= 4 bars and drawdown <= early_cut_r (e.g. -0.35R)
                bars = getattr(cluster, "_bars_open", 0)
                if cluster.status == TradeStatus.OPEN and bars >= 4:
                    r_dist = cluster.r_distance()
                    if r_dist > 0:
                        cur_r = (price - cluster.avg_entry_price()) / r_dist if cluster.direction == TradeDirection.BUY else (cluster.avg_entry_price() - price) / r_dist
                        if cur_r <= early_cut_r and not getattr(cluster, "breakeven_activated", False):
                            # Early momentum cut
                            for leg in cluster.legs:
                                if leg.status == TradeStatus.OPEN:
                                    leg.status = TradeStatus.CLOSED
                                    leg.exit_price = price
                                    leg.exit_reason = ExitReason.STAGNATION
                            cluster.status = TradeStatus.CLOSED
                            return [{"action": "early_adverse_cut", "price": price}]
                return orig_manage_exits(cluster, data_all, idx, price)
            engine._manage_backtest_exits = patched_manage_exits

        # Run engine
        raw_copy = copy.deepcopy(raw_data)
        res = engine.run(raw_copy)
        results[sym] = extract_trades_and_stats(engine, res)

    # Combined stats
    comb_trades = sorted(results["XAUUSD"]["trades"] + results["USTECH100M"]["trades"], key=lambda t: t["open_time"])
    tot_pnl = sum(t["pnl"] for t in comb_trades)
    tot_wins = sum(1 for t in comb_trades if t["pnl"] > 0.01)
    tot_losses = sum(1 for t in comb_trades if t["pnl"] < -0.01)
    wr = (tot_wins / len(comb_trades) * 100) if comb_trades else 0.0
    return {
        "name": name,
        "pnl": tot_pnl,
        "trades": comb_trades,
        "wins": tot_wins,
        "losses": tot_losses,
        "win_rate": wr,
        "by_sym": results,
    }


def main():
    print("=" * 80)
    print("  DIAGNOSTIC BACKTEST EXPERIMENT ON GENUINE MT5 DATA (SEP 21 - SEP 25, 2026)")
    print("  ZERO PRODUCTION FILES ARE MODIFIED.")
    print("=" * 80)

    xau_data, nas_data = load_cached_data()

    experiments = [
        {"name": "1. Baseline (Current Production)", "atr_buffer_mult": 0.0, "t1_pct": 25.0, "t1_r": 1.5, "early_cut_r": 0.0},
        {"name": "2. Hack 1 (Stop-Hunt ATR Buffer 1.5x)", "atr_buffer_mult": 1.5, "t1_pct": 25.0, "t1_r": 1.5, "early_cut_r": 0.0},
        {"name": "3. Hack 2 (Front-Loaded Tranche 50% @ 1.2R)", "atr_buffer_mult": 0.0, "t1_pct": 50.0, "t1_r": 1.2, "early_cut_r": 0.0},
        {"name": "4. Hack 1 + Hack 2 (1.5x Buffer + 50% Tranche)", "atr_buffer_mult": 1.5, "t1_pct": 50.0, "t1_r": 1.2, "early_cut_r": 0.0},
        {"name": "5. Hack 1 + Hack 2 (2.2x Buffer + 50% Tranche)", "atr_buffer_mult": 2.2, "t1_pct": 50.0, "t1_r": 1.2, "early_cut_r": 0.0},
    ]

    all_exp_results = []
    for exp in experiments:
        print(f"\n>>> Running: {exp['name']}...")
        res = run_experiment(
            exp["name"],
            xau_data,
            nas_data,
            atr_buffer_mult=exp["atr_buffer_mult"],
            t1_pct=exp["t1_pct"],
            t1_r=exp["t1_r"],
            early_cut_r=exp["early_cut_r"],
        )
        all_exp_results.append(res)
        pnl_str = f"{'+' if res['pnl'] >= 0 else ''}${res['pnl']:,.2f}"
        print(f"    --> Net PnL: {pnl_str:>10} | Trades: {len(res['trades'])} ({res['wins']}W / {res['losses']}L) | Win Rate: {res['win_rate']:.1f}%")

    print("\n" + "=" * 80)
    print("  SUMMARY COMPARISON TABLE (SEP 21 - SEP 25, 2026)")
    print("=" * 80)
    print(f"  {'Configuration':<42} | {'Net PnL':<11} | {'Trades':<8} | {'Win Rate':<9} | {'Diff vs Base'}")
    print("  " + "-" * 78)
    base_pnl = all_exp_results[0]["pnl"]
    for r in all_exp_results:
        diff = r["pnl"] - base_pnl
        diff_str = f"{'+' if diff >= 0 else ''}${diff:,.2f}" if r != all_exp_results[0] else "BASELINE"
        pnl_str = f"{'+' if r['pnl'] >= 0 else ''}${r['pnl']:,.2f}"
        t_str = f"{len(r['trades'])} ({r['wins']}W/{r['losses']}L)"
        print(f"  {r['name']:<42} | {pnl_str:>11} | {t_str:>8} | {r['win_rate']:>8.1f}% | {diff_str:>12}")
    print("=" * 80)

    # Detailed trade breakdown for best configuration
    best = max(all_exp_results, key=lambda x: x["pnl"])
    print(f"\n>>> Detailed Trade Log for Best Configuration: '{best['name']}':")
    print(f"  {'Open Time':<17} | {'Sym':<10} | {'Dir':<4} | {'Lots':<6} | {'Entry':<10} | {'Exit':<10} | {'PnL ($)':<9} | {'Exit Reason'}")
    print("  " + "-" * 85)
    for t in best["trades"]:
        d_str = t["open_time"].strftime("%b %d %H:%M")
        sym = "USTECH" if t["entry_price"] > 5000 else "XAUUSD"
        pnl_str = f"{'+' if t['pnl'] >= 0 else ''}{t['pnl']:.2f}"
        print(f"  {d_str:<17} | {sym:<10} | {t['direction']:<4} | {t['lots']:<6.2f} | {t['entry_price']:<10.2f} | {t['exit_price']:<10.2f} | {pnl_str:>9} | {t['exit_reason']}")
    print("=" * 85 + "\n")


if __name__ == "__main__":
    main()
