#!/usr/bin/env python3
"""
Dynamic Regime Backtest: Full 2026 (Jan 1, 2026 - Sep 24, 2026)
DOES NOT MODIFY ANY PRODUCTION FILES.

Tests User's Strategy:
1. Stop-Hunt ATR Buffer (Hack 1): Always ON (2.2x ATR buffer)
2. Dynamic Tranche Regime Switching:
   - When ADX >= 25 (or CHOP < 50): TRENDING -> 25% @ 1.5R + 75% Big Runner
   - When CHOP >= 50 (or ADX < 25): SIDEWAYS  -> 50% @ 1.2R + BE Ratchet
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
from xauusd_bot.models import TradeStatus, TradeDirection, ExitReason, TradeLeg
from xauusd_bot.indicators.quant_indicators import choppiness_index, adx

FULL_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 24, 23, 59, 59, tzinfo=timezone.utc)


def load_full_data():
    xau_path = BASE_DIR / "data" / "full_2026_xauusd.json"
    nas_path = BASE_DIR / "data" / "full_2026_nas100.json"
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


def run_dynamic_sim(name: str, xau_data: dict, nas_data: dict, mode: str = "dynamic"):
    """
    mode:
      - 'baseline': no atr buffer, static 25% @ 1.5R
      - 'fixed_chop': 2.2x atr buffer, static 50% @ 1.2R
      - 'dynamic': 2.2x atr buffer, dynamic regime (ADX>=25 -> 25%@1.5R, CHOP>=50 -> 50%@1.2R)
    """
    print(f"\n================================================================================")
    print(f"  RUNNING: {name}")
    print(f"================================================================================")

    results = {}
    for sym, raw_data in [("XAUUSD", xau_data), ("USTECH100M", nas_data)]:
        print(f"  -> Processing {sym}...")
        cfg = Config.load()
        cfg.trading.backtest_initial_balance = 10000.0
        cfg.trading.backtest_apply_friction = True
        cfg.trading.backtest_commission_per_lot = 6.0
        cfg.trading.xau_partial_close_enabled = True

        engine = BacktestEngine(
            cfg,
            initial_balance=10000.0,
            symbol=sym,
            start_date=FULL_START,
            end_date=FULL_END,
        )

        # Apply Stop-Hunt ATR Buffer if mode is not baseline
        if mode in ("fixed_chop", "dynamic"):
            orig_detect = engine.trigger.detect_xau_scalp_sequence
            def patched_detect(*args, **kwargs):
                seq = orig_detect(*args, **kwargs)
                if seq:
                    m1_atr = kwargs.get("m1_atr", 1.0)
                    ep = seq["entry_price"]
                    direction = seq["direction"]
                    pad = max(m1_atr * 2.2, 4.0 if ep > 5000 else 0.8)
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
            engine.trigger.detect_xau_scalp_sequence = patched_detect

        # Dynamic Regime Hook for Partial Exits
        if mode == "dynamic":
            orig_manage = engine._manage_backtest_exits

            def patched_manage(cluster, data_all, idx, price):
                # Classify regime at M15 level
                m15 = data_all.get("M15")
                is_chop = False
                if m15 and len(m15.close) >= 20:
                    c_val = choppiness_index(m15.high, m15.low, m15.close, 14)
                    a_val = adx(m15.high, m15.low, m15.close, 14)
                    # ADX >= 25 is Trending; CHOP >= 50 or ADX < 25 is Sideways/Chop
                    if a_val is not None and a_val >= 25.0:
                        is_chop = False
                    elif c_val is not None and c_val >= 50.0:
                        is_chop = True
                    elif a_val is not None and a_val < 25.0:
                        is_chop = True

                # Dynamic target R and close percentage
                target_r = 1.20 if is_chop else 1.50
                close_pct = 0.50 if is_chop else 0.25

                # Intercept partial close check
                if getattr(engine.cfg.trading, "xau_partial_close_enabled", False):
                    cluster_id = cluster.cluster_id
                    if not getattr(cluster, "partial_tp1_hit", False) and cluster_id not in engine.partial_close._tp_hit:
                        avg_entry = cluster.avg_entry_price()
                        r_dist = cluster.r_distance() if hasattr(cluster, "r_distance") else 0.0
                        if r_dist <= 0 and cluster.collective_sl:
                            r_dist = abs(avg_entry - cluster.collective_sl)
                        if r_dist > 0 and avg_entry > 0:
                            move_r = (price - avg_entry) / r_dist if cluster.direction == TradeDirection.BUY else (avg_entry - price) / r_dist
                            if move_r >= target_r:
                                cluster.partial_tp1_hit = True
                                engine.partial_close._tp_hit.add(cluster_id)
                                new_closed_legs = []
                                for leg in cluster.legs:
                                    if leg.status == TradeStatus.OPEN:
                                        part_lot = round(leg.lot_size * close_pct, 2)
                                        if part_lot > 0 and (leg.lot_size - part_lot) >= 0.01:
                                            closed_part = TradeLeg(
                                                direction=leg.direction,
                                                entry_price=leg.entry_price,
                                                lot_size=part_lot,
                                                symbol=getattr(leg, "symbol", engine.symbol),
                                                sl_price=leg.sl_price,
                                                tp_price=price,
                                                open_time=leg.open_time,
                                                status=TradeStatus.CLOSED,
                                                exit_price=price,
                                                exit_reason="partial_tp",
                                            )
                                            new_closed_legs.append(closed_part)
                                            leg.lot_size = round(leg.lot_size - part_lot, 2)
                                cluster.legs.extend(new_closed_legs)
                                cluster.breakeven_activated = True
                                cluster.collective_sl = cluster.avg_entry_price()

                # Call original exit manager for stagnation / BE / trail
                return orig_manage(cluster, data_all, idx, price)

            engine._manage_backtest_exits = patched_manage
        elif mode == "fixed_chop":
            cfg.trading.partial_tp_tranche1_pct = 50.0
            cfg.trading.partial_tp_tranche1_r = 1.2
            engine.partial_close.close_pct = 50.0
            engine.partial_close.take_profit_r = 1.2

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
    print("  TRINETRA DYNAMIC REGIME BACKTEST (JAN 1, 2026 - SEP 24, 2026)")
    print("  Comparing: Baseline vs Fixed Chop vs Dynamic Regime Switching")
    print("  Zero production files modified.")
    print("=" * 80)

    xau_data, nas_data = load_full_data()

    # 1. Baseline
    base_res = run_dynamic_sim("1. Baseline (Current Production)", xau_data, nas_data, mode="baseline")

    # 2. Fixed Chop Mode
    chop_res = run_dynamic_sim("2. Fixed Chop Hack (Static 50% @ 1.2R)", xau_data, nas_data, mode="fixed_chop")

    # 3. Dynamic Regime Switching
    dyn_res = run_dynamic_sim("3. Dynamic Regime Switching (ADX/CHOP Adaptive)", xau_data, nas_data, mode="dynamic")

    # Final Combined Comparison
    print("\n" + "=" * 80)
    print("  COMPLETE 2026 PERFORMANCE COMPARISON (JAN 1 - SEP 24, 2026)")
    print("=" * 80)
    print(f"  {'Metric':<20} | {'1. Baseline':<17} | {'2. Fixed Chop':<17} | {'3. Dynamic Regime':<17}")
    print("  " + "-" * 78)
    print(f"  {'Net PnL ($)':<20} | {'+' if base_res['pnl'] >= 0 else ''}${base_res['pnl']:<16,.2f} | {'+' if chop_res['pnl'] >= 0 else ''}${chop_res['pnl']:<16,.2f} | {'+' if dyn_res['pnl'] >= 0 else ''}${dyn_res['pnl']:<16,.2f}")
    print(f"  {'Final Balance ($)':<20} | ${10000.0 + base_res['pnl']:<16,.2f} | ${10000.0 + chop_res['pnl']:<16,.2f} | ${10000.0 + dyn_res['pnl']:<16,.2f}")
    print(f"  {'Total Trades':<20} | {len(base_res['trades']):<17} | {len(chop_res['trades']):<17} | {len(dyn_res['trades']):<17}")
    print(f"  {'Win Rate (%)':<20} | {base_res['win_rate']:<16.1f}% | {chop_res['win_rate']:<16.1f}% | {dyn_res['win_rate']:<16.1f}%")
    print(f"  {'Wins / Losses':<20} | {base_res['wins']}W / {base_res['losses']}L{' ':<9} | {chop_res['wins']}W / {chop_res['losses']}L{' ':<9} | {dyn_res['wins']}W / {dyn_res['losses']}L{' ':<9}")
    print("=" * 80)

    # Monthly breakdown comparison
    all_months = sorted(set(list(base_res["monthly"].keys()) + list(chop_res["monthly"].keys()) + list(dyn_res["monthly"].keys())))
    print("\n" + "=" * 80)
    print("  MONTH-BY-MONTH PROFIT COMPARISON (2026)")
    print("=" * 80)
    print(f"  {'Month':<10} | {'Baseline PnL':<15} | {'Fixed Chop PnL':<15} | {'Dynamic Regime PnL':<18} | {'Best Strategy'}")
    print("  " + "-" * 78)
    for m in all_months:
        b_pnl = base_res["monthly"].get(m, {}).get("pnl", 0.0)
        c_pnl = chop_res["monthly"].get(m, {}).get("pnl", 0.0)
        d_pnl = dyn_res["monthly"].get(m, {}).get("pnl", 0.0)
        
        best_name = "Dynamic Regime" if d_pnl >= max(b_pnl, c_pnl) else ("Baseline" if b_pnl >= c_pnl else "Fixed Chop")
        print(f"  {m:<10} | {'+' if b_pnl >= 0 else ''}${b_pnl:<14,.2f} | {'+' if c_pnl >= 0 else ''}${c_pnl:<14,.2f} | {'+' if d_pnl >= 0 else ''}${d_pnl:<17,.2f} | {best_name}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
