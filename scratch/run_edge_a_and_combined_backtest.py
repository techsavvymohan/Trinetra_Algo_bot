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


def run_single_setup(title: str, xau_cfg_overrides: dict, nas_cfg_overrides: dict, data_xau, data_nas):
    print("=" * 105)
    print(f"  BACKTEST RUN: {title}")
    print("=" * 105)

    # 1. Backtest XAUUSD
    cfg_xau = Config.load()
    cfg_xau.trading.symbol = "XAUUSD"
    cfg_xau.trading.symbols = ["XAUUSD"]
    for k, v in xau_cfg_overrides.items():
        setattr(cfg_xau.trading, k, v)

    engine_xau = BacktestEngine(cfg_xau, initial_balance=10000.0, symbol="XAUUSD")
    res_xau = engine_xau.run(data_xau)
    trades_xau = extract_leg_trades(engine_xau, "XAUUSD")

    # 2. Backtest NAS100
    cfg_nas = Config.load()
    cfg_nas.trading.symbol = "USTECH100M"
    cfg_nas.trading.symbols = ["USTECH100M"]
    for k, v in nas_cfg_overrides.items():
        setattr(cfg_nas.trading, k, v)

    engine_nas = BacktestEngine(cfg_nas, initial_balance=10000.0, symbol="USTECH100M")
    res_nas = engine_nas.run(data_nas)
    trades_nas = extract_leg_trades(engine_nas, "USTECH100M")

    # 3. Monthly Attribution
    all_months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
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
        xau_by_m[t["open_time"].strftime("%Y-%m")].append(t)
    for t in trades_nas:
        nas_by_m[t["open_time"].strftime("%Y-%m")].append(t)

    print(f"{'Month':<20} | {'XAU PnL ($)':>12} {'(WR)':>7} | {'NAS PnL ($)':>12} {'(WR)':>7} | {'COMBINED ($)':>14} {'Status':>8}")
    print("-" * 105)

    tot_xau = 0.0
    tot_nas = 0.0
    tot_comb = 0.0
    green_count = 0

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

        if comb_pnl > 0:
            green_count += 1
            status = "[GREEN]"
        else:
            status = "[RED]"

        m_label = month_names.get(m, m)
        print(f"{m_label:<20} | ${x_pnl:>11.2f} {x_wr:>6.1f}% | ${n_pnl:>11.2f} {n_wr:>6.1f}% | ${comb_pnl:>13.2f} {status:>8}")

    print("-" * 105)
    print(f"{'TOTAL (Jan-Aug)':<20} | ${tot_xau:>11.2f}        | ${tot_nas:>11.2f}        | ${tot_comb:>13.2f} [{'ALL GREEN' if green_count == 8 else f'{green_count}/8 GREEN'}]")

    # Metrics
    combined_trades = sorted(trades_xau + trades_nas, key=lambda x: x["close_time"])
    peak = 10000.0
    equity = 10000.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for t in combined_trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    total_trades = len(combined_trades)
    total_wins = len([t for t in combined_trades if t["pnl"] > 0])
    wr = (total_wins / total_trades * 100) if total_trades else 0.0

    gross_profit = sum(t["pnl"] for t in combined_trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in combined_trades if t["pnl"] < 0))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else 99.9

    print(f"\n  Summary Metrics:")
    print(f"    - Initial Capital:   $10,000.00")
    print(f"    - Final Balance:     ${10000.0 + tot_comb:,.2f}")
    print(f"    - Net Profit:        ${tot_comb:,.2f} (+{(tot_comb/10000.0)*100:.1f}%)")
    print(f"    - Win Rate:          {wr:.1f}% ({total_wins}W / {total_trades - total_wins}L / {total_trades} trades)")
    print(f"    - Profit Factor:     {pf:.2f}")
    print(f"    - Max Drawdown:      ${max_dd:,.2f} ({max_dd_pct:.1f}%)")
    print(f"    - Green Months:      {green_count}/8 months")
    print("=" * 105 + "\n\n")

    return {
        "title": title,
        "xau_pnl": tot_xau,
        "nas_pnl": tot_nas,
        "total_pnl": tot_comb,
        "roi_pct": (tot_comb / 10000.0) * 100,
        "win_rate": wr,
        "profit_factor": pf,
        "max_dd": max_dd,
        "max_dd_pct": max_dd_pct,
        "green_count": green_count,
    }


def main():
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)
    with open("data/genuine_jan_aug_2026_nas100.json") as f:
        data_nas = json.load(f)

    # 1. Edge A Alone: 3.0 ATR Runner Trail (Nasdaq at 1.0% risk)
    res_edge_a = run_single_setup(
        title="EDGE A (Wide 3.0 ATR Runner Trail | Nasdaq 1.0% Risk)",
        xau_cfg_overrides={"runner_trail_atr_mult": 3.0},
        nas_cfg_overrides={"runner_trail_atr_mult": 3.0, "nas_risk_per_trade": 0.010},
        data_xau=data_xau,
        data_nas=data_nas,
    )

    # 2. Edge A + D: 3.0 ATR Runner Trail + Nasdaq 2.0% Risk Parity
    res_edge_ad = run_single_setup(
        title="EDGE A + D (Wide 3.0 ATR Runner Trail + Nasdaq 2.0% Risk Parity)",
        xau_cfg_overrides={"runner_trail_atr_mult": 3.0},
        nas_cfg_overrides={"runner_trail_atr_mult": 3.0, "nas_risk_per_trade": 0.020},
        data_xau=data_xau,
        data_nas=data_nas,
    )

    print("*" * 105)
    print("  SIDE-BY-SIDE COMPARISON: EDGE A vs EDGE A + D")
    print("*" * 105)
    print(f"{'Metric':<30} | {'Edge A (3.0 ATR Runner)':>32} | {'Edge A + D (Runner + 2% Nas)':>34}")
    print("-" * 105)
    print(f"{'Net Profit ($)':<30} | ${res_edge_a['total_pnl']:>31,.2f} | ${res_edge_ad['total_pnl']:>33,.2f}")
    print(f"{'ROI (%)':<30} | {res_edge_a['roi_pct']:>31.1f}% | {res_edge_ad['roi_pct']:>33.1f}%")
    print(f"{'Gold (XAUUSD) PnL':<30} | ${res_edge_a['xau_pnl']:>31,.2f} | ${res_edge_ad['xau_pnl']:>33,.2f}")
    print(f"{'Nasdaq (NAS100) PnL':<30} | ${res_edge_a['nas_pnl']:>31,.2f} | ${res_edge_ad['nas_pnl']:>33,.2f}")
    print(f"{'Win Rate (%)':<30} | {res_edge_a['win_rate']:>31.1f}% | {res_edge_ad['win_rate']:>33.1f}%")
    print(f"{'Profit Factor':<30} | {res_edge_a['profit_factor']:>32.2f} | {res_edge_ad['profit_factor']:>34.2f}")
    print(f"{'Max Drawdown ($)':<30} | ${res_edge_a['max_dd']:>31,.2f} | ${res_edge_ad['max_dd']:>33,.2f}")
    print(f"{'Max Drawdown (%)':<30} | {res_edge_a['max_dd_pct']:>31.1f}% | {res_edge_ad['max_dd_pct']:>33.1f}%")
    print(f"{'Green Months':<30} | {res_edge_a['green_count']:>30}/8 | {res_edge_ad['green_count']:>32}/8")
    print("*" * 105)


if __name__ == "__main__":
    main()
