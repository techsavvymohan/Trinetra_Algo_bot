"""
Backtest: September 1-19, 2026 - XAUUSD & USTECH100M
Merges native_true_jun_sep + fetched_18sep datasets for full Sep coverage.
"""
import sys, json
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection
from xauusd_bot.indicators.moving_averages import ema
from xauusd_bot.indicators.atr import atr

SEP_START = datetime(2026, 9, 1, tzinfo=timezone.utc)
SEP_END   = datetime(2026, 9, 19, 23, 59, 59, tzinfo=timezone.utc)


def merge_datasets(base, overlay):
    result = {}
    for tf in set(list(base.keys()) + list(overlay.keys())):
        bd = base.get(tf, {})
        od = overlay.get(tf, {})
        b_times = bd.get("time", [])
        o_times = od.get("time", [])
        combined = {}
        for i, t in enumerate(b_times):
            bar = {k: bd[k][i] for k in bd if k != "tf" and isinstance(bd[k], list)}
            bar["time"] = t
            combined[t] = bar
        for i, t in enumerate(o_times):
            bar = {k: od[k][i] for k in od if k != "tf" and isinstance(od[k], list)}
            bar["time"] = t
            combined[t] = bar
        sorted_bars = sorted(combined.values(), key=lambda b: b["time"])
        if not sorted_bars:
            result[tf] = bd if bd else od
            continue
        keys = [k for k in sorted_bars[0].keys() if k != "time"]
        merged = {"tf": tf, "time": [b["time"] for b in sorted_bars]}
        for k in keys:
            merged[k] = [b.get(k, 0.0) for b in sorted_bars]
        result[tf] = merged
    return result


def _print_results(engine, res, symbol):
    trades = []
    if hasattr(engine, "_clusters"):
        for cluster in engine._clusters:
            for leg in cluster.legs:
                if leg.status == TradeStatus.CLOSED and leg.exit_price:
                    dt_open = leg.open_time if isinstance(leg.open_time, datetime) \
                              else datetime.fromisoformat(str(leg.open_time))
                    pnl = getattr(leg, "pnl", 0.0) or 0.0
                    trades.append({
                        "open": dt_open,
                        "pnl":  pnl,
                        "dir":  getattr(leg.direction, "name", str(leg.direction)),
                    })

    total_pnl     = res.get("total_pnl", 0.0)
    total_trades  = res.get("total_trades", len(trades))
    win_rate      = res.get("win_rate", 0.0)
    wins          = res.get("wins", sum(1 for t in trades if t["pnl"] > 0.01))
    losses        = res.get("losses", sum(1 for t in trades if t["pnl"] < -0.01))
    max_dd        = res.get("max_drawdown_pct", res.get("max_drawdown", 0.0))
    profit_factor = res.get("profit_factor", 0.0)
    final_bal     = res.get("final_balance", 10000.0 + total_pnl)
    status        = "GREEN (PROFIT)" if total_pnl > 0 else ("RED (LOSS)" if total_pnl < 0 else "FLAT (no trades)")

    print(f"\n  [{status}]")
    print(f"  Initial Balance : $10,000.00")
    print(f"  Final Balance   : ${final_bal:,.2f}")
    print(f"  Net PnL         : {'+'if total_pnl>=0 else ''}${total_pnl:,.2f}")
    print(f"  Total Trades    : {total_trades}")
    print(f"  Win Rate        : {win_rate:.1f}%  ({wins}W / {losses}L)")
    print(f"  Profit Factor   : {profit_factor:.2f}")
    print(f"  Max Drawdown    : {max_dd:.2f}%")

    daily = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})
    for t in trades:
        d = t["open"].strftime("%Y-%m-%d (%a)")
        daily[d]["pnl"]    += t["pnl"]
        daily[d]["trades"] += 1
        if t["pnl"] > 0.01:
            daily[d]["wins"] += 1
        elif t["pnl"] < -0.01:
            daily[d]["losses"] += 1

    if daily:
        print(f"\n  {'Date':<22} | {'PnL':>9} | {'Trades':>6} | W/L     | Status")
        print(f"  {'-'*65}")
        week_pnl = 0.0
        last_week = None
        for d in sorted(daily.keys()):
            s = daily[d]
            dt = datetime.strptime(d[:10], "%Y-%m-%d")
            week = dt.isocalendar()[1]
            if last_week is not None and week != last_week:
                print(f"  {'  WEEK TOTAL':<22} | ${week_pnl:>8.2f} |        |         |")
                print(f"  {'-'*65}")
                week_pnl = 0.0
            icon = "WIN" if s["pnl"] > 0 else ("LOSS" if s["pnl"] < 0 else "FLAT")
            print(f"  {d:<22} | ${s['pnl']:>8.2f} | {s['trades']:>6} | {s['wins']}W/{s['losses']}L   | {icon}")
            week_pnl += s["pnl"]
            last_week = week
        if week_pnl != 0:
            print(f"  {'  WEEK TOTAL':<22} | ${week_pnl:>8.2f} |        |         |")
    else:
        print(f"\n  (No trades in Sep 1-19 range)")

    if trades:
        best  = max(trades, key=lambda x: x["pnl"])
        worst = min(trades, key=lambda x: x["pnl"])
        print(f"\n  Best Trade  : +${best['pnl']:.2f}  [{best['dir']}]  on {best['open'].strftime('%b %d')}")
        print(f"  Worst Trade :  ${worst['pnl']:.2f}  [{worst['dir']}]  on {worst['open'].strftime('%b %d')}")
    print()


def run_xauusd(raw_data):
    print("\n" + "="*70)
    print("  XAUUSD  |  Sep 01 - Sep 19, 2026")
    print("="*70)

    cfg = Config.load()
    cfg.trading.backtest_initial_balance    = 10000.0
    cfg.trading.backtest_apply_friction     = True
    cfg.trading.backtest_commission_per_lot = 6.0

    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD",
                            start_date=SEP_START, end_date=SEP_END)
    res = engine.run(raw_data)
    _print_results(engine, res, "XAUUSD")


def run_nas100(raw_data):
    print("\n" + "="*70)
    print("  USTECH100M (Nasdaq 100)  |  Sep 01 - Sep 19, 2026")
    print("="*70)

    cfg = Config.load()
    cfg.trading.backtest_initial_balance    = 10000.0
    cfg.trading.backtest_apply_friction     = True
    cfg.trading.backtest_commission_per_lot = 6.0

    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M",
                            start_date=SEP_START, end_date=SEP_END)
    res = engine.run(raw_data)
    _print_results(engine, res, "USTECH100M")


if __name__ == "__main__":
    print("\n" + "#"*70)
    print("  BACKTEST REPORT -- September 1-19, 2026")
    print("#"*70)

    # Load & merge XAUUSD
    xau_base  = json.load(open("data/native_true_jun_sep_xauusd.json"))
    xau_over  = json.load(open("data/fetched_18sep2026_xauusd.json"))
    xau_data  = merge_datasets(xau_base, xau_over)
    m1_times  = xau_data.get("M1", {}).get("time", [])
    print(f"\n  XAUUSD data: {m1_times[0] if m1_times else '?'} -> {m1_times[-1] if m1_times else '?'}")

    # Load USTECH100M
    nas_data = json.load(open("data/genuine_recent_nas100.json"))
    m1_times = nas_data.get("M1", {}).get("time", [])
    print(f"  USTECH100M data: {m1_times[0] if m1_times else '?'} -> {m1_times[-1] if m1_times else '?'}")

    run_xauusd(xau_data)
    run_nas100(nas_data)
    print("#"*70 + "\n")
