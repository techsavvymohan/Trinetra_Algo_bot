import json
import sys
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus


def run_sep_test(symbol: str, data_file: str, scale_a: float, title: str):
    with open(data_file) as f:
        data = json.load(f)

    cfg = Config.load()
    cfg.trading.symbol = symbol
    cfg.trading.symbols = [symbol]
    cfg.trading.conviction_scale_a = scale_a
    cfg.trading.runner_trail_atr_mult = 3.0
    cfg.trading.xau_stagnation_exit_enabled = True
    cfg.trading.xau_stagnation_bars = 20
    cfg.trading.xau_stagnation_min_r = 0.30

    start_dt = datetime(2026, 9, 1, 0, 0, 0)
    end_dt = datetime(2026, 9, 18, 23, 59, 59)

    eng = BacktestEngine(
        cfg,
        initial_balance=10000.0,
        symbol=symbol,
        start_date=start_dt,
        end_date=end_dt
    )
    res = eng.run(data)

    trades = []
    for c in eng._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
                dt_open = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                if dt_open.tzinfo is not None:
                    dt_open = dt_open.astimezone(timezone.utc).replace(tzinfo=None)
                if dt_open >= start_dt and dt_open <= end_dt:
                    trades.append({
                        "open_time": dt_open,
                        "close_time": leg.close_time or dt_open,
                        "direction": leg.direction.value,
                        "entry": leg.entry_price,
                        "exit": leg.exit_price,
                        "lots": leg.lot_size,
                        "pnl": getattr(leg, "pnl", 0.0) or 0.0,
                        "reason": str(getattr(leg, "exit_reason", "")),
                    })

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    total_pnl = sum(t["pnl"] for t in trades)
    wr = len(wins) / len(trades) * 100 if trades else 0.0

    # Max Drawdown
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

    gross_p = sum(t["pnl"] for t in wins)
    gross_l = abs(sum(t["pnl"] for t in losses))
    pf = gross_p / gross_l if gross_l > 0 else 99.9

    return {
        "title": title,
        "symbol": symbol,
        "trades": trades,
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": total_pnl,
        "roi_pct": (total_pnl / 10000.0) * 100,
        "wr": wr,
        "pf": pf,
        "max_dd": max_dd,
        "max_dd_pct": max_dd_pct,
    }


def main():
    print("=" * 105)
    print("  OUT-OF-SAMPLE BACKTEST: 1 SEPTEMBER TO 18 SEPTEMBER 2026")
    print("  Comparing Baseline (1.30x) vs Option C (2.60x Extra Trade on Grade A)")
    print("=" * 105)

    # 1. Gold Baseline (1.30x scale)
    xau_base = run_sep_test("XAUUSD", "data/genuine_recent_xauusd.json", 1.30, "Gold Baseline (1.30x)")
    # 2. Gold Option C (2.60x scale)
    xau_opt_c = run_sep_test("XAUUSD", "data/genuine_recent_xauusd.json", 2.60, "Gold Option C (2.60x)")

    # 3. Nasdaq Baseline (1.0% risk)
    nas_base = run_sep_test("USTECH100M", "data/genuine_recent_nas100.json", 1.30, "Nasdaq Baseline")
    # 4. Nasdaq Option C
    nas_opt_c = run_sep_test("USTECH100M", "data/genuine_recent_nas100.json", 2.60, "Nasdaq Option C")

    print("\n" + "*" * 105)
    print(f"{'Metric':<32} | {'Gold Baseline':>15} | {'Gold Option C':>15} | {'Nas Option C':>15} | {'Combined Opt C':>16}")
    print("*" * 105)

    comb_pnl = xau_opt_c["total_pnl"] + nas_opt_c["total_pnl"]
    comb_trades = len(xau_opt_c["trades"]) + len(nas_opt_c["trades"])
    comb_wins = xau_opt_c["wins"] + nas_opt_c["wins"]
    comb_wr = (comb_wins / comb_trades * 100) if comb_trades else 0

    print(f"{'Net Profit ($)':<32} | ${xau_base['total_pnl']:>14,.2f} | ${xau_opt_c['total_pnl']:>14,.2f} | ${nas_opt_c['total_pnl']:>14,.2f} | ${comb_pnl:>15,.2f}")
    print(f"{'Return on Capital (ROI)':<32} | {xau_base['roi_pct']:>14.1f}% | {xau_opt_c['roi_pct']:>14.1f}% | {nas_opt_c['roi_pct']:>14.1f}% | {(comb_pnl/10000.0)*100:>15.1f}%")
    print(f"{'Win Rate (%)':<32} | {xau_base['wr']:>14.1f}% | {xau_opt_c['wr']:>14.1f}% | {nas_opt_c['wr']:>14.1f}% | {comb_wr:>15.1f}%")
    str_x_b = f"{len(xau_base['trades'])} ({xau_base['wins']}W/{xau_base['losses']}L)"
    str_x_c = f"{len(xau_opt_c['trades'])} ({xau_opt_c['wins']}W/{xau_opt_c['losses']}L)"
    str_n_c = f"{len(nas_opt_c['trades'])} ({nas_opt_c['wins']}W/{nas_opt_c['losses']}L)"
    str_comb = f"{comb_trades} ({comb_wins}W/{comb_trades-comb_wins}L)"
    print(f"{'Total Trades (W/L)':<32} | {str_x_b:>15} | {str_x_c:>15} | {str_n_c:>15} | {str_comb:>16}")
    print(f"{'Profit Factor':<32} | {xau_base['pf']:>15.2f} | {xau_opt_c['pf']:>15.2f} | {nas_opt_c['pf']:>15.2f} | {'—':>16}")
    print(f"{'Max Drawdown ($)':<32} | ${xau_base['max_dd']:>14,.2f} | ${xau_opt_c['max_dd']:>14,.2f} | ${nas_opt_c['max_dd']:>14,.2f} | {'—':>16}")
    print(f"{'Max Drawdown (%)':<32} | {xau_base['max_dd_pct']:>14.1f}% | {xau_opt_c['max_dd_pct']:>14.1f}% | {nas_opt_c['max_dd_pct']:>14.1f}% | {'—':>16}")
    print("*" * 105)

    # Print trade-by-trade log for Gold Option C
    print("\n\n" + "=" * 105)
    print("  SEPTEMBER 1 - 18, 2026: TRADE-BY-TRADE LOG FOR GOLD (OPTION C)")
    print("=" * 105)
    print(f"{'#':<3} | {'Open Time (UTC)':<19} | {'Dir':<4} | {'Entry':>8} | {'Exit':>8} | {'Lots':>5} | {'PnL ($)':>12} | {'Exit Reason':<20}")
    print("-" * 105)
    for i, t in enumerate(xau_opt_c["trades"], 1):
        dt_str = t["open_time"].strftime("%Y-%m-%d %H:%M")
        print(f"{i:<3} | {dt_str:<19} | {t['direction']:<4} | {t['entry']:>8.2f} | {t['exit']:>8.2f} | {t['lots']:>5.2f} | ${t['pnl']:>11.2f} | {t['reason']:<20}")
    print("=" * 105)


if __name__ == "__main__":
    main()
