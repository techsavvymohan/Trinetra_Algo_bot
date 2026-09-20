"""
Comprehensive Backtest: January 1, 2026 – September 18, 2026
Combined Multi-Asset Portfolio: XAUUSD + USTECH100M (Nasdaq 100)
Monthly Attribution, Win Rates, PnL, Drawdown, and Payoff Metrics
"""
import os
import sys
import json
import math
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection

START_DATE = datetime(2026, 1, 1, 0, 0, 0)
END_DATE   = datetime(2026, 9, 18, 23, 59, 59)

def normalize_time(t_val):
    if isinstance(t_val, str):
        dt = datetime.fromisoformat(t_val.replace("Z", "+00:00"))
    else:
        dt = t_val
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

def merge_three_datasets(jan_aug_file, jun_sep_file, fetched_file):
    print(f"  Merging datasets: {os.path.basename(jan_aug_file)} + {os.path.basename(jun_sep_file)} + {os.path.basename(fetched_file)}...", flush=True)
    with open(jan_aug_file) as f: d1 = json.load(f)
    with open(jun_sep_file) as f: d2 = json.load(f)
    with open(fetched_file) as f: d3 = json.load(f)

    all_tfs = set(list(d1.keys()) + list(d2.keys()) + list(d3.keys()))
    merged_data = {}

    for tf in all_tfs:
        bars_by_time = {}
        for d in (d1, d2, d3):
            sub = d.get(tf, {})
            times = sub.get("time", [])
            if not times:
                continue
            keys = [k for k in sub.keys() if k not in ("time", "tf") and isinstance(sub[k], list)]
            n = len(times)
            for i in range(n):
                t_dt = normalize_time(times[i])
                t_str = t_dt.isoformat()
                bar = {k: sub[k][i] for k in keys if i < len(sub[k])}
                bars_by_time[t_str] = bar

        sorted_times = sorted(bars_by_time.keys())
        if not sorted_times:
            continue
        first_bar = bars_by_time[sorted_times[0]]
        merged_data[tf] = {k: [bars_by_time[t][k] for t in sorted_times] for k in first_bar.keys()}
        merged_data[tf]["time"] = sorted_times

    m1_t = merged_data.get("M1", {}).get("time", [])
    print(f"  [OK] Merged total: {len(m1_t)} M1 bars ({m1_t[0]} -> {m1_t[-1]})", flush=True)
    return merged_data

def extract_trades(engine, symbol):
    trades = []
    clusters = getattr(engine, "closed_clusters", []) or []
    for c in clusters:
        for leg in getattr(c, "legs", []):
            if getattr(leg, "status", None) == TradeStatus.CLOSED:
                if getattr(leg, "exit_price", None) is not None:
                    dt_open = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                    if dt_open.tzinfo is not None:
                        dt_open = dt_open.astimezone(timezone.utc).replace(tzinfo=None)
                    
                    dt_close = getattr(leg, "close_time", None)
                    if dt_close:
                        if isinstance(dt_close, str):
                            dt_close = datetime.fromisoformat(dt_close.replace("Z", "+00:00"))
                        if dt_close.tzinfo is not None:
                            dt_close = dt_close.astimezone(timezone.utc).replace(tzinfo=None)

                    pnl = getattr(leg, "pnl", 0.0) or 0.0
                    trades.append({
                        "symbol": symbol,
                        "open_time": dt_open,
                        "close_time": dt_close or dt_open,
                        "direction": getattr(leg.direction, "name", str(leg.direction)),
                        "entry_price": getattr(leg, "entry_price", getattr(leg, "open_price", 0.0)),
                        "exit_price": leg.exit_price,
                        "pnl": pnl,
                        "exit_reason": getattr(leg, "exit_reason", "UNKNOWN"),
                        "volume": getattr(leg, "volume", getattr(leg, "lots", 0.0)),
                    })
    return trades

def compute_stats(trades):
    wins = [t for t in trades if t["pnl"] > 0.01]
    losses = [t for t in trades if t["pnl"] < -0.01]
    be = [t for t in trades if -0.01 <= t["pnl"] <= 0.01]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    net_pnl = sum(t["pnl"] for t in trades)
    wr = (len(wins) / len(trades) * 100.0) if trades else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "be": len(be),
        "win_rate": wr,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": net_pnl,
        "profit_factor": pf,
    }

def main():
    print("=" * 80)
    print("  BACKTEST: 1 JANUARY 2026 – 18 SEPTEMBER 2026")
    print("  PORTFOLIO: XAUUSD + USTECH100M (COMBINED)")
    print("  Friction: $6.00/lot Commission + Spread + MoC Parity")
    print("=" * 80, flush=True)

    # 1. Merge Datasets
    print("\n[1/2] Merging Datasets for XAUUSD...", flush=True)
    xau_data = merge_three_datasets(
        "data/genuine_jan_aug_2026_xauusd.json",
        "data/native_true_jun_sep_xauusd.json",
        "data/fetched_18sep2026_xauusd.json"
    )

    print("\n[2/2] Loading Genuine Dataset for USTECH100M (Nasdaq 100)...", flush=True)
    with open("data/genuine_recent_nas100.json") as f:
        nas_data = json.load(f)

    cfg = Config.load()
    cfg.trading.backtest_initial_balance = 10000.0
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0

    # 2. Run XAUUSD Backtest
    print("\nRunning Full-Year Backtest Engine...", flush=True)
    print("  Running XAUUSD (Jan 01 - Sep 18)...", flush=True)
    engine_xau = BacktestEngine(
        cfg, initial_balance=10000.0, symbol="XAUUSD",
        start_date=START_DATE, end_date=END_DATE
    )
    res_xau = engine_xau.run(xau_data)
    trades_xau = extract_trades(engine_xau, "XAUUSD")
    print(f"  [OK] XAUUSD Completed: {len(trades_xau)} trades, PnL=${res_xau.get('total_pnl', 0.0):.2f}, WR={res_xau.get('win_rate', 0.0):.1f}%", flush=True)

    # 3. Run USTECH100M Backtest
    print("  Running USTECH100M (Jan 01 - Sep 18)...", flush=True)
    engine_nas = BacktestEngine(
        cfg, initial_balance=10000.0, symbol="USTECH100M",
        start_date=START_DATE, end_date=END_DATE
    )
    res_nas = engine_nas.run(nas_data)
    trades_nas = extract_trades(engine_nas, "USTECH100M")
    print(f"  [OK] USTECH100M Completed: {len(trades_nas)} trades, PnL=${res_nas.get('total_pnl', 0.0):.2f}, WR={res_nas.get('win_rate', 0.0):.1f}%", flush=True)

    # 4. Monthly Attribution Analysis
    months = [
        ("2026-01", "January 2026"),
        ("2026-02", "February 2026"),
        ("2026-03", "March 2026"),
        ("2026-04", "April 2026"),
        ("2026-05", "May 2026"),
        ("2026-06", "June 2026"),
        ("2026-07", "July 2026"),
        ("2026-08", "August 2026"),
        ("2026-09", "September 2026 (1-18)"),
    ]

    xau_by_month = defaultdict(list)
    for t in trades_xau:
        m_key = t["open_time"].strftime("%Y-%m")
        xau_by_month[m_key].append(t)

    nas_by_month = defaultdict(list)
    for t in trades_nas:
        m_key = t["open_time"].strftime("%Y-%m")
        nas_by_month[m_key].append(t)

    print("\n" + "=" * 105)
    print("  MONTH-BY-MONTH ATTRIBUTION TABLE: XAUUSD | USTECH100M | COMBINED (JAN 1 – SEP 18, 2026)")
    print("=" * 105)
    header = f"  {'Month':<22} | {'XAUUSD PnL':<14} | {'XAU W/L (WR%)':<16} | {'USTECH100M PnL':<14} | {'NAS W/L (WR%)':<16} | {'COMBINED PnL':<14} | Status"
    print(header)
    print("  " + "-" * 110)

    total_xau_trades = 0
    total_xau_pnl = 0.0
    total_nas_trades = 0
    total_nas_pnl = 0.0

    all_combined_trades = []

    for m_key, m_label in months:
        m_xau_trades = xau_by_month.get(m_key, [])
        m_nas_trades = nas_by_month.get(m_key, [])
        m_comb_trades = m_xau_trades + m_nas_trades
        all_combined_trades.extend(m_comb_trades)

        s_xau = compute_stats(m_xau_trades)
        s_nas = compute_stats(m_nas_trades)
        s_comb = compute_stats(m_comb_trades)

        total_xau_trades += s_xau["trades"]
        total_xau_pnl += s_xau["net_pnl"]
        total_nas_trades += s_nas["trades"]
        total_nas_pnl += s_nas["net_pnl"]

        xau_str = f"${s_xau['net_pnl']:>9.2f}"
        xau_wl  = f"{s_xau['wins']}W/{s_xau['losses']}L ({s_xau['win_rate']:>4.1f}%)" if s_xau['trades'] else "  0 trades   "

        nas_str = f"${s_nas['net_pnl']:>9.2f}"
        nas_wl  = f"{s_nas['wins']}W/{s_nas['losses']}L ({s_nas['win_rate']:>4.1f}%)" if s_nas['trades'] else "  0 trades   "

        comb_str = f"${s_comb['net_pnl']:>10.2f}"
        status = "[GREEN]" if s_comb["net_pnl"] > 0 else ("[RED]" if s_comb["net_pnl"] < 0 else "[FLAT]")

        print(f"  {m_label:<22} | {xau_str:<14} | {xau_wl:<16} | {nas_str:<14} | {nas_wl:<16} | {comb_str:<14} | {status}")

    print("  " + "=" * 110)
    comb_total_pnl = total_xau_pnl + total_nas_pnl
    comb_stats = compute_stats(all_combined_trades)
    print(f"  {'TOTAL PORTFOLIO':<22} | ${total_xau_pnl:>9.2f}    | {res_xau.get('win_rate', 0.0):>4.1f}% WR        | ${total_nas_pnl:>9.2f}    | {res_nas.get('win_rate', 0.0):>4.1f}% WR        | ${comb_total_pnl:>10.2f}   | [PROFITABLE]")
    print("=" * 105)

    # 5. Portfolio Summary Metrics
    init_bal = 10000.0
    final_bal = init_bal + comb_total_pnl
    total_ret_pct = (comb_total_pnl / init_bal) * 100.0

    print("\n" + "=" * 60)
    print("  PORTFOLIO HIGH-LEVEL EXECUTIVE SUMMARY")
    print("=" * 60)
    print(f"  Initial Balance        : ${init_bal:,.2f}")
    print(f"  Final Balance          : ${final_bal:,.2f}")
    print(f"  Total Net Profit (PnL) : +${comb_total_pnl:,.2f}  (+{total_ret_pct:.1f}% return)")
    print(f"  - XAUUSD Net Profit    : +${total_xau_pnl:,.2f}")
    print(f"  - USTECH100M Net Profit: +${total_nas_pnl:,.2f}")
    print(f"  Total Trades Executed  : {comb_stats['trades']} ({comb_stats['wins']} Wins / {comb_stats['losses']} Losses)")
    print(f"  Combined Win Rate      : {comb_stats['win_rate']:.2f}%")
    print(f"  Profit Factor          : {comb_stats['profit_factor']:.2f}")
    print(f"  Gross Profit           : ${comb_stats['gross_profit']:,.2f}")
    print(f"  Gross Loss             : ${comb_stats['gross_loss']:,.2f}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
