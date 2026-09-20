import json
import sys
import numpy as np
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus


def run_test(scale_c_val: float, title: str):
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)

    cfg = Config.load()
    cfg.trading.conviction_scale_c = scale_c_val
    eng = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
    eng.run(data_xau)

    trades = []
    for c in eng._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
                pnl = getattr(leg, "pnl", 0.0) or 0.0
                trades.append({
                    "open_time": leg.open_time,
                    "close_time": leg.close_time or leg.open_time,
                    "pnl": pnl,
                })

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
    total_pnl = sum(t["pnl"] for t in trades)
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else 99.9

    # Max DD
    sorted_t = sorted(trades, key=lambda x: x["close_time"])
    peak = 10000.0
    eq = 10000.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for t in sorted_t:
        eq += t["pnl"]
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    # Monthly breakdown
    all_months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    by_m = defaultdict(list)
    for t in trades:
        m_k = t["open_time"].strftime("%Y-%m") if hasattr(t["open_time"], "strftime") else str(t["open_time"])[:7]
        by_m[m_k].append(t)

    green_months = sum(1 for m in all_months if sum(t["pnl"] for t in by_m[m]) > 0)

    return {
        "title": title,
        "total_pnl": total_pnl,
        "roi_pct": (total_pnl / 10000.0) * 100,
        "wr": wr,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "pf": pf,
        "max_dd": max_dd,
        "max_dd_pct": max_dd_pct,
        "green_months": f"{green_months}/8",
    }


def main():
    print("=" * 110)
    print("  BACKTEST: GRADE C (WEAK SETUPS) RISK AT 1.0% vs 2.10% (CURRENT)")
    print("  Grade A: 4.55% (1.30x) | Grade B: 3.50% (1.00x) — UNTOUCHED")
    print("=" * 110)

    # 1. Current: Grade C = 2.10% (0.60x scale)
    res_curr = run_test(0.60, "Current (Grade C at 2.10% / 0.60x scale)")

    # 2. Test: Grade C = 1.00% (1.0 / 3.5 = 0.2857 scale)
    res_1pct = run_test(1.0 / 3.5, "New Test (Grade C at 1.00% / 0.2857 scale)")

    print(f"{'Metric':<32} | {'Current (Grade C at 2.1%)':>32} | {'New Test (Grade C at 1.0%)':>34}")
    print("-" * 110)
    print(f"{'Total Net Profit ($)':<32} | ${res_curr['total_pnl']:>31,.2f} | ${res_1pct['total_pnl']:>33,.2f}")
    print(f"{'Account ROI (%)':<32} | {res_curr['roi_pct']:>31.1f}% | {res_1pct['roi_pct']:>33.1f}%")
    print(f"{'Win Rate (%)':<32} | {res_curr['wr']:>31.1f}% | {res_1pct['wr']:>33.1f}%")
    t_str_curr = f"{res_curr['trades']} ({res_curr['wins']}W / {res_curr['losses']}L)"
    t_str_1pct = f"{res_1pct['trades']} ({res_1pct['wins']}W / {res_1pct['losses']}L)"
    print(f"{'Total Trades (W/L)':<32} | {t_str_curr:>32} | {t_str_1pct:>34}")
    print(f"{'Average Win ($)':<32} | ${res_curr['avg_win']:>31.2f} | ${res_1pct['avg_win']:>33.2f}")
    print(f"{'Average Loss ($)':<32} | ${res_curr['avg_loss']:>31.2f} | ${res_1pct['avg_loss']:>33.2f}")
    print(f"{'Profit Factor':<32} | {res_curr['pf']:>32.2f} | {res_1pct['pf']:>34.2f}")
    print(f"{'Max Drawdown ($)':<32} | ${res_curr['max_dd']:>31,.2f} | ${res_1pct['max_dd']:>33,.2f}")
    print(f"{'Max Drawdown (%)':<32} | {res_curr['max_dd_pct']:>31.1f}% | {res_1pct['max_dd_pct']:>33.1f}%")
    print(f"{'Green Months':<32} | {res_curr['green_months']:>32} | {res_1pct['green_months']:>34}")
    print("=" * 110)


if __name__ == "__main__":
    main()
