#!/usr/bin/env python3
"""
Comprehensive Backtest: CURRENT PRODUCTION BOT STATE
Evaluates 100% unpatched, pure production bot on genuine broker data:
Timeframes: M1, M15, H1 (and M5)
Period: January 1, 2026 - September 24, 2026 (All Available 2026 Bars)
Symbols: XAUUSD (Gold) and USTECH100M (Nasdaq 100)
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
from xauusd_bot.models import TradeStatus

FULL_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 24, 23, 59, 59, tzinfo=timezone.utc)


def load_full_dataset():
    xau_path = BASE_DIR / "data" / "full_2026_xauusd.json"
    nas_path = BASE_DIR / "data" / "full_2026_nas100.json"
    print(">>> Loading genuine MT5 broker datasets (M1, M5, M15, H1)...")
    print(f"  Reading {xau_path}...")
    with open(xau_path, "r", encoding="utf-8") as f:
        xau_data = json.load(f)
    print(f"  Reading {nas_path}...")
    with open(nas_path, "r", encoding="utf-8") as f:
        nas_data = json.load(f)

    for sym, d in [("XAUUSD", xau_data), ("USTECH100M", nas_data)]:
        print(f"  [{sym}] Bar counts:")
        for tf in ["M1", "M15", "H1"]:
            if tf in d:
                t0 = d[tf]["time"][0][:16]
                t1 = d[tf]["time"][-1][:16]
                print(f"    - {tf:<4}: {len(d[tf]['time']):>7} bars ({t0} -> {t1})")
    return xau_data, nas_data


def run_current_state_backtest():
    xau_data, nas_data = load_full_dataset()

    print("\n" + "=" * 80)
    print("  TRINETRA DUAL-ENGINE: CURRENT PRODUCTION BOT STATE BACKTEST")
    print("  Date Range: January 1, 2026 - September 24, 2026")
    print("  Timeframes Active: M1 (Execution/Trigger), M15 (Structure/Swings), H1 (Trend Bias)")
    print("  Starting Balance: $10,000.00 | Friction & Slippage: ENABLED")
    print("=" * 80)

    results = {}
    for sym, raw_data in [("XAUUSD", xau_data), ("USTECH100M", nas_data)]:
        print(f"\n>>> Running current state engine on {sym}...")
        cfg = Config.load()
        cfg.trading.backtest_initial_balance = 10000.0
        cfg.trading.backtest_apply_friction = True
        cfg.trading.backtest_commission_per_lot = 6.0

        # Exact production engine instantiation - zero overrides
        engine = BacktestEngine(
            cfg,
            initial_balance=10000.0,
            symbol=sym,
            start_date=FULL_START,
            end_date=FULL_END,
        )

        raw_copy = copy.deepcopy(raw_data)
        res = engine.run(raw_copy)

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
                            "symbol": getattr(leg, "symbol", sym),
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
        wins = [t for t in trades if t["pnl"] > 0.01]
        losses = [t for t in trades if t["pnl"] < -0.01]
        wr = (len(wins) / len(trades) * 100) if trades else 0.0
        pf = res.get("profit_factor", 0.0)
        max_dd = res.get("max_drawdown_pct", res.get("max_drawdown", 0.0))
        
        avg_win = (sum(t["pnl"] for t in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(t["pnl"] for t in losses) / len(losses)) if losses else 0.0

        # Exit reasons breakdown
        exit_counts = defaultdict(int)
        for t in trades:
            exit_counts[t["exit_reason"]] += 1

        results[sym] = {
            "pnl": pnl,
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": wr,
            "profit_factor": pf,
            "max_dd": max_dd,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "exit_counts": dict(exit_counts),
        }
        print(f"  [DONE] {sym}: Net PnL = {'+' if pnl >= 0 else ''}${pnl:,.2f} | Trades = {len(trades)} | WR = {wr:.1f}% | MaxDD = {max_dd:.2f}%")

    # Combined Portfolio
    all_trades = sorted(results["XAUUSD"]["trades"] + results["USTECH100M"]["trades"], key=lambda t: t["open_time"])
    tot_pnl = sum(t["pnl"] for t in all_trades)
    tot_wins = [t for t in all_trades if t["pnl"] > 0.01]
    tot_losses = [t for t in all_trades if t["pnl"] < -0.01]
    tot_wr = (len(tot_wins) / len(all_trades) * 100) if all_trades else 0.0
    tot_avg_win = (sum(t["pnl"] for t in tot_wins) / len(tot_wins)) if tot_wins else 0.0
    tot_avg_loss = (sum(t["pnl"] for t in tot_losses) / len(tot_losses)) if tot_losses else 0.0

    gross_profit = sum(t["pnl"] for t in tot_wins)
    gross_loss = abs(sum(t["pnl"] for t in tot_losses))
    comb_pf = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

    # Monthly breakdown
    monthly = defaultdict(lambda: {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0, "xau_pnl": 0.0, "nas_pnl": 0.0})
    for t in all_trades:
        m_key = t["open_time"].strftime("%Y-%m")
        monthly[m_key]["pnl"] += t["pnl"]
        monthly[m_key]["trades"] += 1
        if "XAU" in t["symbol"]:
            monthly[m_key]["xau_pnl"] += t["pnl"]
        else:
            monthly[m_key]["nas_pnl"] += t["pnl"]

        if t["pnl"] > 0.01:
            monthly[m_key]["wins"] += 1
        elif t["pnl"] < -0.01:
            monthly[m_key]["losses"] += 1

    # Exit reason distribution
    all_exits = defaultdict(int)
    for t in all_trades:
        all_exits[t["exit_reason"]] += 1

    print("\n" + "=" * 80)
    print("  COMPLETE 2026 BACKTEST AUDIT: CURRENT PRODUCTION BOT")
    print("  Period: January 1, 2026 - September 24, 2026 (9 Full Months)")
    print("=" * 80)
    print(f"  Starting Balance    : $10,000.00")
    print(f"  Final Balance       : ${10000.0 + tot_pnl:,.2f}")
    print(f"  Net Total Profit    : {'+' if tot_pnl >= 0 else ''}${tot_pnl:,.2f} ({tot_pnl / 10000.0 * 100:+.1f}% Total ROI)")
    print(f"  Combined Profit Factor: {comb_pf:.2f}")
    print(f"  Total Closed Trades : {len(all_trades)} ({len(tot_wins)} Wins / {len(tot_losses)} Losses)")
    print(f"  Overall Win Rate    : {tot_wr:.1f}%")
    print(f"  Average Winning Trade: +${tot_avg_win:,.2f}")
    print(f"  Average Losing Trade : ${tot_avg_loss:,.2f}")
    print(f"  Win / Loss Ratio    : {abs(tot_avg_win / tot_avg_loss):.2f} : 1")
    print("-" * 80)
    print(f"  XAUUSD (Gold) Net PnL   : {'+' if results['XAUUSD']['pnl'] >= 0 else ''}${results['XAUUSD']['pnl']:,.2f} | Trades: {len(results['XAUUSD']['trades'])} | WR: {results['XAUUSD']['win_rate']:.1f}% | MaxDD: {results['XAUUSD']['max_dd']:.2f}%")
    print(f"  USTECH100M (Nasdaq) PnL : {'+' if results['USTECH100M']['pnl'] >= 0 else ''}${results['USTECH100M']['pnl']:,.2f} | Trades: {len(results['USTECH100M']['trades'])} | WR: {results['USTECH100M']['win_rate']:.1f}% | MaxDD: {results['USTECH100M']['max_dd']:.2f}%")
    print("=" * 80)

    # Monthly Breakdown Table
    print("\n" + "=" * 80)
    print("  MONTH-BY-MONTH DETAILED AUDIT (2026)")
    print("=" * 80)
    print(f"  {'Month':<10} | {'Net PnL ($)':<14} | {'Win Rate':<9} | {'Trades (W/L)':<14} | {'Gold PnL':<13} | {'Nasdaq PnL'}")
    print("  " + "-" * 78)
    for m in sorted(monthly.keys()):
        d = monthly[m]
        wr = (d["wins"] / d["trades"] * 100) if d["trades"] else 0.0
        pnl_str = f"{'+' if d['pnl'] >= 0 else ''}${d['pnl']:,.2f}"
        t_str = f"{d['trades']} ({d['wins']}W/{d['losses']}L)"
        x_str = f"{'+' if d['xau_pnl'] >= 0 else ''}${d['xau_pnl']:,.2f}"
        n_str = f"{'+' if d['nas_pnl'] >= 0 else ''}${d['nas_pnl']:,.2f}"
        print(f"  {m:<10} | {pnl_str:>14} | {wr:>8.1f}% | {t_str:<14} | {x_str:>13} | {n_str:>13}")
    print("=" * 80)

    # Exit reason distribution
    print("\n" + "=" * 80)
    print("  TRADE EXIT REASONS DISTRIBUTION")
    print("=" * 80)
    for r, count in sorted(all_exits.items(), key=lambda x: -x[1]):
        pct = (count / len(all_trades) * 100) if all_trades else 0.0
        print(f"  - {r:<25}: {count:>4} trades ({pct:>5.1f}%)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_current_state_backtest()
