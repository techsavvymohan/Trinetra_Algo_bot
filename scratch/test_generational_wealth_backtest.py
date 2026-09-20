import json
import sys
import copy
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


def run_experiment(name: str, xau_overrides: dict, nas_overrides: dict, data_xau, data_nas):
    # Setup XAU
    cfg_xau = Config.load()
    cfg_xau.trading.symbol = "XAUUSD"
    cfg_xau.trading.symbols = ["XAUUSD"]
    for k, v in xau_overrides.items():
        setattr(cfg_xau.trading, k, v)

    engine_xau = BacktestEngine(cfg_xau, initial_balance=10000.0, symbol="XAUUSD")
    res_xau = engine_xau.run(data_xau)
    trades_xau = extract_leg_trades(engine_xau, "XAUUSD")

    # Setup NAS
    cfg_nas = Config.load()
    cfg_nas.trading.symbol = "USTECH100M"
    cfg_nas.trading.symbols = ["USTECH100M"]
    for k, v in nas_overrides.items():
        setattr(cfg_nas.trading, k, v)

    engine_nas = BacktestEngine(cfg_nas, initial_balance=10000.0, symbol="USTECH100M")
    res_nas = engine_nas.run(data_nas)
    trades_nas = extract_leg_trades(engine_nas, "USTECH100M")

    # Monthly breakdown
    all_months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    xau_by_m = defaultdict(list)
    nas_by_m = defaultdict(list)
    for t in trades_xau:
        xau_by_m[t["open_time"].strftime("%Y-%m")].append(t)
    for t in trades_nas:
        nas_by_m[t["open_time"].strftime("%Y-%m")].append(t)

    green_months = 0
    monthly_pnls = []
    for m in all_months:
        m_pnl = sum(t["pnl"] for t in xau_by_m[m]) + sum(t["pnl"] for t in nas_by_m[m])
        monthly_pnls.append(m_pnl)
        if m_pnl > 0:
            green_months += 1

    xau_pnl = res_xau.get("total_pnl", 0.0)
    nas_pnl = res_nas.get("total_pnl", 0.0)
    total_pnl = xau_pnl + nas_pnl

    total_trades = len(trades_xau) + len(trades_nas)
    total_wins = len([t for t in trades_xau if t["pnl"] > 0]) + len([t for t in trades_nas if t["pnl"] > 0])
    win_rate = (total_wins / total_trades * 100) if total_trades else 0.0

    gross_profit = sum(t["pnl"] for t in trades_xau if t["pnl"] > 0) + sum(t["pnl"] for t in trades_nas if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades_xau if t["pnl"] < 0) + sum(t["pnl"] for t in trades_nas if t["pnl"] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.9

    # Max Drawdown across equity curve
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

    return {
        "name": name,
        "xau_pnl": xau_pnl,
        "xau_wr": res_xau.get("win_rate", 0.0),
        "xau_trades": len(trades_xau),
        "nas_pnl": nas_pnl,
        "nas_wr": res_nas.get("win_rate", 0.0),
        "nas_trades": len(trades_nas),
        "total_pnl": total_pnl,
        "roi_pct": (total_pnl / 10000.0) * 100,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "profit_factor": profit_factor,
        "max_dd_dollars": max_dd,
        "max_dd_pct": max_dd_pct,
        "green_months": f"{green_months}/8",
        "monthly_pnls": monthly_pnls,
    }


def main():
    print("=" * 110)
    print("  GENERATIONAL WEALTH EXPERIMENTAL BACKTEST MATRIX (JAN - AUG 2026)")
    print("  Testing 4 Institutional Edges: Uncapped Runners, Pyramiding, H4 Confluence, Nasdaq Parity")
    print("=" * 110)

    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)
    with open("data/genuine_jan_aug_2026_nas100.json") as f:
        data_nas = json.load(f)

    experiments = [
        (
            "0. Baseline (Current Production Bot)",
            {},
            {},
        ),
        (
            "1. Edge A: Wide ATR Runner Trail (3.0 ATR vs 2.0)",
            {"runner_trail_atr_mult": 3.0},
            {"runner_trail_atr_mult": 3.0},
        ),
        (
            "2. Edge A: Ultra-Wide ATR Runner Trail (4.0 ATR - Big Trends)",
            {"runner_trail_atr_mult": 4.0},
            {"runner_trail_atr_mult": 4.0},
        ),
        (
            "3. Edge B: Strict 1.0R Pyramiding (Only add when trade is locked at BE)",
            {"pyramid_add_trigger_r": 1.0, "max_pyramid_entries": 3},
            {"pyramid_add_trigger_r": 1.0, "max_pyramid_entries": 3},
        ),
        (
            "4. Edge C: Macro H4 Bias Guard Active",
            {"xau_h4_bias_guard": True},
            {},
        ),
        (
            "5. Edge D: Nasdaq Risk Parity (2.0% Risk on Nasdaq vs 1.0%)",
            {},
            {"nas_risk_per_trade": 0.020},
        ),
        (
            "6. Combined Generational Wealth Mode (Edges A + B + D)",
            {"runner_trail_atr_mult": 3.0, "pyramid_add_trigger_r": 1.0},
            {"runner_trail_atr_mult": 3.0, "pyramid_add_trigger_r": 1.0, "nas_risk_per_trade": 0.020},
        ),
    ]

    results = []
    for exp_name, xau_cfg, nas_cfg in experiments:
        print(f"\n>> Running: {exp_name}...", flush=True)
        res = run_experiment(exp_name, xau_cfg, nas_cfg, data_xau, data_nas)
        results.append(res)
        print(f"   [DONE] Total PnL: ${res['total_pnl']:,.2f} | WR: {res['win_rate']:.1f}% | DD: ${res['max_dd_dollars']:,.2f} ({res['max_dd_pct']:.1f}%) | Green: {res['green_months']}", flush=True)

    print("\n\n" + "=" * 115)
    print(f"{'Strategy / Configuration':<40} | {'Total PnL':>12} | {'ROI (%)':>8} | {'Win Rate':>8} | {'Max DD ($ / %)':>16} | {'PF':>6} | {'Green M':>7}")
    print("=" * 115)
    for r in results:
        dd_str = f"${r['max_dd_dollars']:,.0f} ({r['max_dd_pct']:.1f}%)"
        print(f"{r['name']:<40} | ${r['total_pnl']:>11.2f} | {r['roi_pct']:>7.1f}% | {r['win_rate']:>7.1f}% | {dd_str:>16} | {r['profit_factor']:>5.2f} | {r['green_months']:>7}")
    print("=" * 115)


if __name__ == "__main__":
    main()
