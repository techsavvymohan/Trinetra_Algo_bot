import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# Ensure root directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.backtesting.validation import run_monte_carlo, run_walk_forward_validation
from xauusd_bot.models import TradeStatus, TradeDirection


def analyze_trades(trades, initial_balance=10000.0):
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

    exit_reasons = defaultdict(int)
    
    for t in trades:
        pnl = t["pnl"]
        exit_reasons[t.get("exit_reason", "UNKNOWN")] += 1
        
        dt_val = t["close_time"] or t["open_time"]
        if isinstance(dt_val, str):
            dt = datetime.fromisoformat(dt_val)
        else:
            dt = dt_val
            
        m_key = dt.strftime("%Y-%m (%b)")
        d_key = dt.strftime("%Y-%m-%d")
        w_day = weekday_names[dt.weekday()]
        
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

    return monthly_stats, weekday_stats, exit_reasons


def run_full_evaluation():
    print("=" * 80)
    print("  INSTITUTIONAL QUANTITATIVE AUDIT & BACKTEST SUITE")
    print("  Real Broker Historical Data | Live Spread & $6.00/lot Commission")
    print("=" * 80)

    cfg = Config.load()
    initial_balance = 10000.0
    cfg.trading.backtest_initial_balance = initial_balance
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0

    # 1. Primary Jan - Aug 2026 XAUUSD Dataset (8 Months)
    xau_path = "data/genuine_jan_aug_2026_xauusd.json"
    if not os.path.exists(xau_path):
        print(f"Error: {xau_path} not found")
        return

    print(f"\n>> Loading {xau_path}...")
    with open(xau_path, "r") as f:
        raw_xau = json.load(f)

    print(">> Executing Backtest Engine on XAUUSD (Jan - Aug 2026)...")
    engine = BacktestEngine(cfg, initial_balance=initial_balance, symbol="XAUUSD")
    res_xau = engine.run(raw_xau)

    trades_xau = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                trades_xau.append({
                    "cluster_id": getattr(c, "cluster_id", ""),
                    "symbol": getattr(leg, "symbol", "XAUUSD"),
                    "direction": leg.direction.value,
                    "open_time": leg.open_time,
                    "close_time": leg.close_time,
                    "entry_price": leg.entry_price,
                    "exit_price": leg.exit_price,
                    "lot_size": leg.lot_size,
                    "pnl": getattr(leg, "pnl", 0.0),
                    "exit_reason": getattr(leg.exit_reason, "value", str(leg.exit_reason)),
                })

    m_stats, w_stats, exit_reasons = analyze_trades(trades_xau, initial_balance)

    print("\n" + "=" * 80)
    print("  1. XAUUSD OVERALL PERFORMANCE SUMMARY (Jan - Aug 2026)")
    print("=" * 80)
    print(f"  * Initial Balance    : ${res_xau['initial_balance']:,.2f}")
    print(f"  * Final Balance      : ${res_xau['final_balance']:,.2f}")
    print(f"  * Net Profit (PnL)   : +${res_xau['total_pnl']:,.2f} (+{res_xau['return_pct']}%)")
    print(f"  * Total Trades       : {res_xau['total_trades']}")
    print(f"  * Win Rate           : {res_xau['win_rate']}% ({res_xau['wins']}W / {res_xau['losses']}L)")
    print(f"  * Profit Factor      : {res_xau['profit_factor']}")
    print(f"  * Max Drawdown       : {res_xau['max_drawdown_pct']}%")
    print(f"  * Sharpe Ratio       : {res_xau.get('sharpe_ratio', 'N/A')}")
    print(f"  * Expectancy         : ${res_xau.get('expectancy', 'N/A')} per trade")

    print("\n" + "-" * 80)
    print("  2. MONTH-BY-MONTH BREAKDOWN (XAUUSD)")
    print("-" * 80)
    print(f"{'Month':<18} | {'Trades':<6} | {'Wins':<5} | {'WinRate':<7} | {'Gross Win':<11} | {'Gross Loss':<11} | {'Net PnL':<12} | {'Monthly Ret'}")
    print("-" * 88)
    running_bal = initial_balance
    for m_key in sorted(m_stats.keys()):
        m = m_stats[m_key]
        t = m["trades"]
        w = m["wins"]
        wr = (w / t * 100) if t else 0.0
        pnl = m["net_pnl"]
        m_ret = (pnl / running_bal) * 100.0
        running_bal += pnl
        print(f"{m_key:<18} | {t:<6} | {w:<5} | {wr:>6.1f}% | ${m['gross_profit']:>9.2f} | ${m['gross_loss']:>9.2f} | ${pnl:>10.2f} | {m_ret:>+8.1f}%")

    print("\n" + "-" * 80)
    print("  3. DAY-OF-WEEK PERFORMANCE")
    print("-" * 80)
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        w = w_stats[day]
        t = w["trades"]
        pnl = w["net_pnl"]
        wr = (w["wins"] / t * 100) if t else 0.0
        print(f"  * {day:<10}: {t:>3} trades | Win Rate: {wr:>5.1f}% | Net PnL: ${pnl:>9.2f}")

    print("\n" + "-" * 80)
    print("  4. EXIT REASONS DISTRIBUTION")
    print("-" * 80)
    for reason, count in sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  * {reason:<26}: {count:>3} trades ({count/len(trades_xau)*100:.1f}%)")

    # 2. Out-of-Sample Forward Test: June - Sep 2026
    oos_path = "data/native_true_jun_sep_xauusd.json"
    if os.path.exists(oos_path):
        print("\n" + "=" * 80)
        print("  5. OUT-OF-SAMPLE STRESS TEST (June - Sep 2026)")
        print("=" * 80)
        with open(oos_path, "r") as f:
            raw_oos = json.load(f)
        engine_oos = BacktestEngine(cfg, initial_balance=initial_balance, symbol="XAUUSD")
        res_oos = engine_oos.run(raw_oos)
        print(f"  * Net Profit (PnL)   : +${res_oos['total_pnl']:,.2f} (+{res_oos['return_pct']}%)")
        print(f"  * Total Trades       : {res_oos['total_trades']}")
        print(f"  * Win Rate           : {res_oos['win_rate']}%")
        print(f"  * Profit Factor      : {res_oos['profit_factor']}")
        print(f"  * Max Drawdown       : {res_oos['max_drawdown_pct']}%")

    # 3. Monte Carlo 15,000 Simulation Stress Test
    trade_pnls = res_xau.get("trade_pnls", [])
    if trade_pnls:
        print("\n" + "=" * 80)
        print("  6. MONTE CARLO STRESS TEST (15,000 Iterations Bootstrap)")
        print("=" * 80)
        mc_res = run_monte_carlo(
            trade_pnls,
            initial_capital=initial_balance,
            num_sims=15000,
            target_pct_p1=8.0,
            target_pct_p2=5.0,
            max_dd_limit_pct=10.0,
        )
        mc_res.print_dashboard(title="MONTE CARLO EMPIRICAL STRESS TEST — XAUUSD")

    # 4. Walk-Forward Validation (WFV)
    print("\n" + "=" * 80)
    print("  7. WALK-FORWARD VALIDATION (IS vs OOS Consistency)")
    print("=" * 80)
    wfv_res = run_walk_forward_validation(raw_xau, cfg, symbol="XAUUSD", initial_balance=initial_balance)
    wfv_res.print_dashboard()


if __name__ == "__main__":
    run_full_evaluation()
