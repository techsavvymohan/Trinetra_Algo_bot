import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus


def extract_leg_trades(engine, symbol: str):
    trades = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
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
                    "direction": leg.direction.value,
                    "entry_price": leg.entry_price,
                    "exit_price": leg.exit_price,
                    "volume": leg.lot_size,
                    "pnl": pnl,
                })
    return trades


def run_portfolio_monthly():
    print("=" * 105)
    print("  RUNNING COMPREHENSIVE DUAL-ENGINE MONTHLY BACKTEST: XAUUSD + NAS100")
    print("  100% Genuine Real-Market Broker Data | Streamlined Clean Timeframes (M1 + M15)")
    print("=" * 105)

    # 1. Backtest XAUUSD (Full Jan - Aug 2026 dataset)
    print("\n[1/2] Backtesting XAUUSD...", flush=True)
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)

    cfg_xau = Config.load()
    cfg_xau.trading.symbol = "XAUUSD"
    cfg_xau.trading.symbols = ["XAUUSD"]

    engine_xau = BacktestEngine(cfg_xau, initial_balance=10000.0, symbol="XAUUSD")
    res_xau = engine_xau.run(data_xau)
    trades_xau = extract_leg_trades(engine_xau, "XAUUSD")
    print(f"  [OK] XAUUSD: {len(trades_xau)} trades, Net PnL = ${res_xau.get('total_pnl', 0.0):,.2f}, WR = {res_xau.get('win_rate', 0.0):.1f}%", flush=True)

    # 2. Backtest NAS100 (Full Jan - Aug 2026 dataset)
    print("\n[2/2] Backtesting USTECH100M (NAS100)...", flush=True)
    with open("data/genuine_jan_aug_2026_nas100.json") as f:
        data_nas = json.load(f)

    cfg_nas = Config.load()
    cfg_nas.trading.symbol = "USTECH100M"
    cfg_nas.trading.symbols = ["USTECH100M"]

    engine_nas = BacktestEngine(cfg_nas, initial_balance=10000.0, symbol="USTECH100M")
    res_nas = engine_nas.run(data_nas)
    trades_nas = extract_leg_trades(engine_nas, "USTECH100M")
    print(f"  [OK] USTECH100M: {len(trades_nas)} trades, Net PnL = ${res_nas.get('total_pnl', 0.0):,.2f}, WR = {res_nas.get('win_rate', 0.0):.1f}%", flush=True)

    # 3. Monthly Attribution Table
    all_months = [
        "2026-01", "2026-02", "2026-03", "2026-04",
        "2026-05", "2026-06", "2026-07", "2026-08",
    ]
    month_names = {
        "2026-01": "January 2026",
        "2026-02": "February 2026",
        "2026-03": "March 2026",
        "2026-04": "April 2026",
        "2026-05": "May 2026",
        "2026-06": "June 2026",
        "2026-07": "July 2026",
        "2026-08": "August 2026 (1-18)",
    }

    xau_by_m = defaultdict(list)
    nas_by_m = defaultdict(list)

    for t in trades_xau:
        m_k = t["open_time"].strftime("%Y-%m")
        xau_by_m[m_k].append(t)

    for t in trades_nas:
        m_k = t["open_time"].strftime("%Y-%m")
        nas_by_m[m_k].append(t)

    print("\n" + "=" * 105)
    print(f"{'Month':<20} | {'XAU PnL ($)':>12} {'(WR)':>7} | {'NAS PnL ($)':>12} {'(WR)':>7} | {'COMBINED ($)':>14} {'Status':>8}")
    print("=" * 105)

    tot_xau = 0.0
    tot_nas = 0.0
    tot_comb = 0.0

    for m in all_months:
        x_trades = xau_by_m[m]
        n_trades = nas_by_m[m]

        x_pnl = sum(t["pnl"] for t in x_trades)
        x_wins = len([t for t in x_trades if t["pnl"] > 0])
        x_wr = (x_wins / len(x_trades) * 100) if x_trades else 0.0

        n_pnl = sum(t["pnl"] for t in n_trades)
        n_wins = len([t for t in n_trades if t["pnl"] > 0])
        n_wr = (n_wins / len(n_trades) * 100) if n_trades else 0.0

        comb_pnl = x_pnl + n_pnl
        tot_xau += x_pnl
        tot_nas += n_pnl
        tot_comb += comb_pnl

        status = "[GREEN]" if comb_pnl > 0 else "[RED]"
        m_label = month_names.get(m, m)

        print(f"{m_label:<20} | ${x_pnl:>11.2f} {x_wr:>6.1f}% | ${n_pnl:>11.2f} {n_wr:>6.1f}% | ${comb_pnl:>13.2f} {status:>8}")

    print("-" * 105)
    comb_status = "[ALL GREEN]" if tot_comb > 0 else "[NET LOSS]"
    print(f"{'TOTAL (Jan-Aug)':<20} | ${tot_xau:>11.2f}        | ${tot_nas:>11.2f}        | ${tot_comb:>13.2f} {comb_status:>8}")
    print("=" * 105)


if __name__ == "__main__":
    run_portfolio_monthly()
