import json
import sys
import numpy as np
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeLeg


class ExtraTradeOnHighestScoreEngine(BacktestEngine):
    """Subclass that executes an EXTRA trade leg whenever signal is Grade A (highest score)."""

    def __init__(self, *args, extra_trade_on_grade_a: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra_trade_on_grade_a = extra_trade_on_grade_a

    def _execute_backtest_order(self, signal, account, data_all, idx, price, current_time=None):
        cluster = super()._execute_backtest_order(signal, account, data_all, idx, price, current_time)
        if cluster is not None and self.extra_trade_on_grade_a and getattr(signal, "grade", None) is not None:
            from xauusd_bot.models import SignalGrade
            if signal.grade == SignalGrade.A:
                # Add an exact EXTRA trade leg on the highest score signal
                extra_leg = TradeLeg(
                    direction=signal.direction,
                    entry_price=price,
                    lot_size=cluster.legs[0].lot_size,
                    symbol=signal.symbol,
                    sl_price=signal.sl_price,
                    tp_price=signal.tp_price,
                    open_time=signal.timestamp,
                    status=TradeStatus.OPEN,
                )
                extra_leg._is_extra_trade = True
                cluster.legs.append(extra_leg)
        return cluster


def run_experiment(engine_cls, cfg_overrides: dict, title: str, extra_trade_flag: bool = False):
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)

    cfg = Config.load()
    for k, v in cfg_overrides.items():
        setattr(cfg.trading, k, v)

    if extra_trade_flag:
        eng = engine_cls(cfg, initial_balance=10000.0, symbol="XAUUSD", extra_trade_on_grade_a=True)
    else:
        eng = engine_cls(cfg, initial_balance=10000.0, symbol="XAUUSD")
    eng.run(data_xau)

    trades = []
    for c in eng._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
                trades.append({
                    "open_time": leg.open_time,
                    "close_time": leg.close_time or leg.open_time,
                    "pnl": getattr(leg, "pnl", 0.0) or 0.0,
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
    print("=" * 115)
    print("  EXPERIMENT: TAKING AN EXTRA TRADE ON HIGHEST SCORE SIGNALS (GRADE A+)")
    print("=" * 115)

    experiments = [
        ("0. Current Active Baseline (1 Trade, 1.30x Conviction)", BacktestEngine, {}, False),
        ("1. Extra Trade Leg on Grade A (Twin Order)", ExtraTradeOnHighestScoreEngine, {}, True),
        ("2. Double Sizing on Grade A (2.00x Conviction Scale)", BacktestEngine, {"conviction_scale_a": 2.00}, False),
        ("3. 2x Full Extra Trade on Grade A (2.60x Conviction Scale)", BacktestEngine, {"conviction_scale_a": 2.60}, False),
    ]

    results = []
    for title, eng_cls, overrides, flag in experiments:
        print(f">> Running: {title}...", flush=True)
        res = run_experiment(eng_cls, overrides, title, flag)
        results.append(res)
        print(f"   [DONE] PnL: ${res['total_pnl']:,.2f} | WR: {res['wr']:.1f}% | DD: ${res['max_dd']:,.2f} ({res['max_dd_pct']:.1f}%) | Green: {res['green_months']}", flush=True)

    print("\n\n" + "=" * 115)
    print(f"{'Strategy / Setup':<44} | {'Net PnL ($)':>14} | {'ROI (%)':>8} | {'Win Rate':>8} | {'Max DD ($ / %)':>16} | {'PF':>5} | {'Green':>5}")
    print("=" * 115)
    for r in results:
        dd_str = f"${r['max_dd']:,.0f} ({r['max_dd_pct']:.1f}%)"
        print(f"{r['title']:<44} | ${r['total_pnl']:>13,.2f} | {r['roi_pct']:>7.1f}% | {r['wr']:>7.1f}% | {dd_str:>16} | {r['pf']:>5.2f} | {r['green_months']:>5}")
    print("=" * 115)


if __name__ == "__main__":
    main()
