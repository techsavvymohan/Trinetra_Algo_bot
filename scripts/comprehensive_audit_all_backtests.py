import os
import sys
import json
import math
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Ensure root directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection

def analyze_trades(trades, initial_balance=10000.0):
    """Deep analysis of trades by month, day of week, and daily PnL."""
    monthly_stats = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0, "be": 0,
        "gross_profit": 0.0, "gross_loss": 0.0, "net_pnl": 0.0,
        "daily_pnls": defaultdict(float)
    })
    
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday_stats = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0, "be": 0,
        "gross_profit": 0.0, "gross_loss": 0.0, "net_pnl": 0.0,
        "pnls": []
    })
    
    daily_stats = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0, "net_pnl": 0.0
    })

    exit_reasons = defaultdict(int)
    
    for t in trades:
        pnl = t["pnl"]
        exit_reasons[t.get("exit_reason", "UNKNOWN")] += 1
        
        # Determine timestamp
        dt_val = t["close_time"] or t["open_time"]
        if isinstance(dt_val, str):
            dt = datetime.fromisoformat(dt_val)
        else:
            dt = dt_val
            
        m_key = dt.strftime("%Y-%m (%b)")
        d_key = dt.strftime("%Y-%m-%d")
        w_day = weekday_names[dt.weekday()]
        
        # Monthly
        m = monthly_stats[m_key]
        m["trades"] += 1
        m["net_pnl"] += pnl
        m["daily_pnls"][d_key] += pnl
        if pnl > 0.01:
            m["wins"] += 1
            m["gross_profit"] += pnl
        elif pnl < -0.01:
            m["losses"] += 1
            m["gross_loss"] += abs(pnl)
        else:
            m["be"] += 1

        # Weekday
        w = weekday_stats[w_day]
        w["trades"] += 1
        w["net_pnl"] += pnl
        w["pnls"].append(pnl)
        if pnl > 0.01:
            w["wins"] += 1
            w["gross_profit"] += pnl
        elif pnl < -0.01:
            w["losses"] += 1
            w["gross_loss"] += abs(pnl)
        else:
            w["be"] += 1

        # Daily
        d = daily_stats[d_key]
        d["trades"] += 1
        d["net_pnl"] += pnl
        if pnl > 0.01:
            d["wins"] += 1
        elif pnl < -0.01:
            d["losses"] += 1

    return monthly_stats, weekday_stats, daily_stats, exit_reasons


def run_dataset_backtest(file_path: str, symbol: str, initial_balance=10000.0):
    print(f"\n{'='*75}")
    print(f"  BACKTEST EXECUTION: {symbol} — {os.path.basename(file_path)}")
    print(f"{'='*75}")
    
    with open(file_path, "r") as f:
        raw_data = json.load(f)
        
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = initial_balance
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0
    
    engine = BacktestEngine(cfg, initial_balance=initial_balance, symbol=symbol)
    res = engine.run(raw_data)
    
    trades = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                trades.append({
                    "cluster_id": getattr(c, "cluster_id", ""),
                    "symbol": getattr(leg, "symbol", symbol),
                    "direction": leg.direction.value,
                    "open_time": leg.open_time,
                    "close_time": leg.close_time,
                    "entry_price": leg.entry_price,
                    "exit_price": leg.exit_price,
                    "lot_size": leg.lot_size,
                    "pnl": getattr(leg, "pnl", 0.0),
                    "exit_reason": getattr(leg.exit_reason, "value", str(leg.exit_reason)),
                })
                
    m_stats, w_stats, d_stats, exit_reasons = analyze_trades(trades, initial_balance)
    
    return res, trades, m_stats, w_stats, d_stats, exit_reasons


def main():
    print("="*75)
    print("  COMPREHENSIVE BACKTEST SUITE: ALL DATASETS & TIMEFRAMES")
    print("  Mode: Personal Real Account High-Yield Scaling (3.5% Base Risk)")
    print("  Friction: $6.00/lot Commission + Spread + MoC Retest Execution")
    print("="*75)

    datasets = [
        ("data/genuine_jan_aug_2026_xauusd.json", "XAUUSD"),
        ("data/native_true_jun_sep_xauusd.json", "XAUUSD"),
        ("data/genuine_recent_nas100.json", "USTECH100M"),
    ]

    all_results = {}

    for path, sym in datasets:
        if not os.path.exists(path):
            continue
        key = f"{sym} ({os.path.basename(path)})"
        res, trades, m_stats, w_stats, d_stats, exit_reasons = run_dataset_backtest(path, sym, 10000.0)
        all_results[key] = {
            "res": res,
            "trades": trades,
            "m_stats": m_stats,
            "w_stats": w_stats,
            "d_stats": d_stats,
            "exit_reasons": exit_reasons,
        }

    # Print Detailed Breakdowns for the primary Jan-Aug 2026 Gold Dataset
    gold_key = "XAUUSD (genuine_jan_aug_2026_xauusd.json)"
    if gold_key in all_results:
        g = all_results[gold_key]
        res = g["res"]
        m_stats = g["m_stats"]
        w_stats = g["w_stats"]
        d_stats = g["d_stats"]

        print("\n" + "#"*75)
        print("  1. XAUUSD OVERALL PERFORMANCE SUMMARY (Jan - Aug 2026)")
        print("#"*75)
        print(f"  * Initial Balance   : ${res['initial_balance']:,.2f}")
        print(f"  * Final Balance     : ${res['final_balance']:,.2f}")
        print(f"  * Net Profit (PnL)  : +${res['total_pnl']:,.2f} (+{res['return_pct']}%)")
        print(f"  * Total Trades      : {res['total_trades']}")
        print(f"  * Win Rate          : {res['win_rate']}% ({res['wins']}W / {res['losses']}L)")
        print(f"  * Profit Factor     : {res['profit_factor']}")
        print(f"  * Max Drawdown      : {res['max_drawdown_pct']}%")
        print(f"  * Sharpe Ratio      : {res.get('sharpe_ratio', 'N/A')}")
        print(f"  * Expectancy        : ${res.get('expectancy', 'N/A')} per trade")

        print("\n" + "-"*75)
        print("  2. MONTH-BY-MONTH BREAKDOWN (XAUUSD)")
        print("-"*75)
        print(f"{'Month':<18} | {'Trades':<6} | {'Wins':<5} | {'WinRate':<7} | {'Gross Win':<11} | {'Gross Loss':<11} | {'Net PnL':<12} | {'Monthly Ret'}")
        print("-" * 88)
        
        running_bal = 10000.0
        for m_key in sorted(m_stats.keys()):
            m = m_stats[m_key]
            t = m["trades"]
            w = m["wins"]
            l = m["losses"]
            wr = (w / t * 100) if t else 0.0
            pnl = m["net_pnl"]
            m_ret = (pnl / running_bal) * 100.0
            running_bal += pnl
            print(f"{m_key:<18} | {t:<6} | {w:<5} | {wr:>6.1f}% | ${m['gross_profit']:>9.2f} | ${m['gross_loss']:>9.2f} | ${pnl:>10.2f} | {m_ret:>+8.1f}%")

        print("\n" + "-"*75)
        print("  3. TRADING DAY OF WEEK BREAKDOWN (XAUUSD)")
        print("-"*75)
        print(f"{'Day of Week':<12} | {'Trades':<6} | {'Wins':<5} | {'Losses':<6} | {'WinRate':<7} | {'Net PnL':<12} | {'Avg Trade':<10} | {'Profit Factor'}")
        print("-" * 85)
        weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        for day in weekday_order:
            if day in w_stats:
                w = w_stats[day]
                t = w["trades"]
                wn = w["wins"]
                ls = w["losses"]
                wr = (wn / t * 100) if t else 0.0
                pnl = w["net_pnl"]
                avg = pnl / t if t else 0.0
                pf = (w["gross_profit"] / w["gross_loss"]) if w["gross_loss"] > 0 else (999.0 if w["gross_profit"] > 0 else 0.0)
                print(f"{day:<12} | {t:<6} | {wn:<5} | {ls:<6} | {wr:>6.1f}% | ${pnl:>10.2f} | ${avg:>8.2f} | {pf:>6.2f}")

        # Daily Win Rate Summary
        total_active_days = len(d_stats)
        winning_days = sum(1 for d in d_stats.values() if d["net_pnl"] > 0.01)
        losing_days = sum(1 for d in d_stats.values() if d["net_pnl"] < -0.01)
        breakeven_days = total_active_days - winning_days - losing_days
        daily_wr = (winning_days / total_active_days * 100) if total_active_days else 0.0
        avg_daily_pnl = res['total_pnl'] / total_active_days if total_active_days else 0.0

        print("\n" + "-"*75)
        print("  4. DAILY CONSISTENCY & TRADING DAYS SUMMARY (XAUUSD)")
        print("-"*75)
        print(f"  * Total Active Trading Days : {total_active_days} days")
        print(f"  * Profitable Trading Days   : {winning_days} days ({daily_wr:.1f}% Daily Win Rate!)")
        print(f"  * Losing Trading Days       : {losing_days} days ({losing_days/total_active_days*100:.1f}%)")
        print(f"  * Breakeven Days            : {breakeven_days} days")
        print(f"  * Average Profit Per Day    : +${avg_daily_pnl:.2f} / day")
        best_day = max(d_stats.items(), key=lambda x: x[1]["net_pnl"])
        worst_day = min(d_stats.items(), key=lambda x: x[1]["net_pnl"])
        print(f"  * Best Trading Day          : {best_day[0]} (+${best_day[1]['net_pnl']:,.2f})")
        print(f"  * Worst Trading Day         : {worst_day[0]} (-${abs(worst_day[1]['net_pnl']):,.2f})")

        print("\n" + "-"*75)
        print("  5. EXIT REASON ATTRIBUTION (XAUUSD)")
        print("-"*75)
        for reason, count in sorted(g["exit_reasons"].items(), key=lambda x: -x[1]):
            print(f"  * {reason:<30}: {count} trades ({count/res['total_trades']*100:.1f}%)")

    # Nasdaq 100 Summary
    nas_key = "USTECH100M (genuine_recent_nas100.json)"
    if nas_key in all_results:
        n = all_results[nas_key]
        res = n["res"]
        m_stats = n["m_stats"]
        print("\n" + "#"*75)
        print("  6. USTECH100M / NASDAQ 100 PERFORMANCE SUMMARY")
        print("#"*75)
        print(f"  * Initial Balance   : ${res['initial_balance']:,.2f}")
        print(f"  * Final Balance     : ${res['final_balance']:,.2f}")
        print(f"  * Net Profit (PnL)  : +${res['total_pnl']:,.2f} (+{res['return_pct']}%)")
        print(f"  * Total Trades      : {res['total_trades']}")
        print(f"  * Win Rate          : {res['win_rate']}% ({res['wins']}W / {res['losses']}L)")
        print(f"  * Profit Factor     : {res['profit_factor']}")
        print(f"  * Max Drawdown      : {res['max_drawdown_pct']}%")
        print(f"  * Sharpe Ratio      : {res.get('sharpe_ratio', 'N/A')}")
        print("\n  --- USTECH100M Monthly Breakdown ---")
        for m_name in sorted(m_stats.keys()):
            ms = m_stats[m_name]
            m_wr = (ms['wins'] / ms['trades'] * 100) if ms['trades'] else 0.0
            print(f"  * {m_name:<16}: Net PnL: +${ms['net_pnl']:>8.2f} | Trades: {ms['trades']:>2} | WR: {m_wr:>5.1f}% ({ms['wins']}W/{ms['losses']}L)")

    # Recent June - September XAUUSD dataset summary
    june_sep_key = "XAUUSD (native_true_jun_sep_xauusd.json)"
    if june_sep_key in all_results:
        js = all_results[june_sep_key]
        res = js["res"]
        print("\n" + "#"*75)
        print("  7. XAUUSD OUT-OF-SAMPLE / RECENT PERIOD (Jun - Sep 2026)")
        print("#"*75)
        print(f"  * Initial Balance   : ${res['initial_balance']:,.2f}")
        print(f"  * Final Balance     : ${res['final_balance']:,.2f}")
        print(f"  * Net Profit (PnL)  : +${res['total_pnl']:,.2f} (+{res['return_pct']}%)")
        print(f"  * Total Trades      : {res['total_trades']}")
        print(f"  * Win Rate          : {res['win_rate']}% ({res['wins']}W / {res['losses']}L)")
        print(f"  * Profit Factor     : {res['profit_factor']}")
        print(f"  * Max Drawdown      : {res['max_drawdown_pct']}%")

if __name__ == "__main__":
    main()
