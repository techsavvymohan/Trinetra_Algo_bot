#!/usr/bin/env python3
"""
Backtest Script: September 21 - September 25, 2026
Downloads genuine M1, M5, M15, H1 broker data from MT5 and executes
the TRINETRA dual-engine backtest for XAUUSD and USTECH100M.
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

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import MetaTrader5 as mt5
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

SEP_START = datetime(2026, 9, 21, 0, 0, 0, tzinfo=timezone.utc)
SEP_END = datetime(2026, 9, 25, 23, 59, 59, tzinfo=timezone.utc)
WARMUP_START = datetime(2026, 9, 14, 0, 0, 0, tzinfo=timezone.utc)


def fetch_and_save_data(symbol: str, output_path: Path) -> dict:
    print(f"\n>>> Fetching genuine MT5 data for {symbol}...")
    if not mt5.initialize():
        print(f"❌ MT5 initialization failed: {mt5.last_error()}")
        sys.exit(1)

    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    if not info:
        print(f"❌ Symbol {symbol} not found in MT5!")
        sys.exit(1)

    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
    }

    dataset = {}
    for tf_name, tf_code in tf_map.items():
        rates = mt5.copy_rates_range(symbol, tf_code, WARMUP_START, SEP_END)
        if rates is None or len(rates) == 0:
            print(f"  ❌ No {tf_name} rates returned for {symbol}: {mt5.last_error()}")
            continue

        times, opens, highs, lows, closes, vols, spreads = [], [], [], [], [], [], []
        for r in rates:
            dt = datetime.fromtimestamp(r["time"], tz=timezone.utc)
            times.append(dt.isoformat())
            opens.append(float(r["open"]))
            highs.append(float(r["high"]))
            lows.append(float(r["low"]))
            closes.append(float(r["close"]))
            vols.append(int(r["tick_volume"]))
            spreads.append(int(r["spread"]))

        dataset[tf_name] = {
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": vols,
            "spread": spreads,
        }
        print(f"  ✅ {tf_name}: {len(rates)} bars ({times[0][:16]} -> {times[-1][:16]})")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f)
    print(f"💾 Saved to {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
    return dataset


def run_single_backtest(symbol: str, raw_data: dict, initial_balance: float = 10000.0) -> dict:
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = initial_balance
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0

    engine = BacktestEngine(
        cfg,
        initial_balance=initial_balance,
        symbol=symbol,
        start_date=SEP_START,
        end_date=SEP_END,
    )
    res = engine.run(raw_data)

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
                        "lots": getattr(leg, "lot_size", 0.0),
                        "pnl": pnl,
                        "exit_reason": getattr(leg.exit_reason, "name", str(leg.exit_reason)),
                    })

    trades.sort(key=lambda t: t["open_time"])
    return {
        "engine": engine,
        "results": res,
        "trades": trades,
        "symbol": symbol,
    }


def print_backtest_report(xau_res: dict, nas_res: dict):
    print("\n" + "=" * 80)
    print("  TRINETRA DUAL-ENGINE INSTITUTIONAL BACKTEST REPORT")
    print("  Evaluation Window: September 21, 2026 - September 25, 2026")
    print("=" * 80)

    for data in [xau_res, nas_res]:
        sym = data["symbol"]
        res = data["results"]
        trades = data["trades"]
        pnl = res.get("total_pnl", sum(t["pnl"] for t in trades))
        bal = res.get("final_balance", 10000.0 + pnl)
        wins = sum(1 for t in trades if t["pnl"] > 0.01)
        losses = sum(1 for t in trades if t["pnl"] < -0.01)
        total_t = len(trades)
        wr = (wins / total_t * 100) if total_t > 0 else 0.0
        pf = res.get("profit_factor", 0.0)
        max_dd = res.get("max_drawdown_pct", res.get("max_drawdown", 0.0))

        status = "PROFITABLE" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")
        print(f"\n--- {sym} PERFORMANCE --- [{status}]")
        print(f"  Starting Balance : $10,000.00")
        print(f"  Final Balance    : ${bal:,.2f}")
        print(f"  Net PnL          : {'+' if pnl >= 0 else ''}${pnl:,.2f}")
        print(f"  Total Trades     : {total_t} ({wins} Wins / {losses} Losses)")
        print(f"  Win Rate         : {wr:.1f}%")
        print(f"  Profit Factor    : {pf:.2f}")
        print(f"  Max Drawdown     : {max_dd:.2f}%")

        if trades:
            print(f"\n  {'Open Time':<17} | {'Dir':<4} | {'Lots':<5} | {'Entry Price':<11} | {'Exit Price':<11} | {'PnL ($)':<9} | {'Exit Reason'}")
            print("  " + "-" * 82)
            for t in trades:
                d_str = t["open_time"].strftime("%b %d %H:%M")
                pnl_str = f"{'+' if t['pnl'] >= 0 else ''}{t['pnl']:.2f}"
                print(f"  {d_str:<17} | {t['direction']:<4} | {t['lots']:<5.2f} | {t['entry_price']:<11.2f} | {t['exit_price']:<11.2f} | {pnl_str:>9} | {t['exit_reason']}")

    # Portfolio level
    x_trades = xau_res["trades"]
    n_trades = nas_res["trades"]
    all_trades = sorted(x_trades + n_trades, key=lambda t: t["open_time"])
    tot_pnl = sum(t["pnl"] for t in all_trades)
    tot_wins = sum(1 for t in all_trades if t["pnl"] > 0.01)
    tot_losses = sum(1 for t in all_trades if t["pnl"] < -0.01)
    tot_wr = (tot_wins / len(all_trades) * 100) if all_trades else 0.0

    print("\n" + "=" * 80)
    print("  PORTFOLIO COMBINED SUMMARY (GOLD + NASDAQ)")
    print("=" * 80)
    print(f"  Combined Net PnL : {'+' if tot_pnl >= 0 else ''}${tot_pnl:,.2f}")
    print(f"  Total Trades     : {len(all_trades)} ({tot_wins}W / {tot_losses}L)")
    print(f"  Combined Win Rate: {tot_wr:.1f}%")
    print("=" * 80 + "\n")


def main():
    xau_path = BASE_DIR / "data" / "fetched_sep21_25_2026_xauusd.json"
    nas_path = BASE_DIR / "data" / "fetched_sep21_25_2026_nas100.json"

    xau_data = fetch_and_save_data("XAUUSD", xau_path)
    nas_data = fetch_and_save_data("USTECH100M", nas_path)
    mt5.shutdown()

    xau_res = run_single_backtest("XAUUSD", xau_data)
    nas_res = run_single_backtest("USTECH100M", nas_data)

    print_backtest_report(xau_res, nas_res)


if __name__ == "__main__":
    main()
