import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus


def get_pnl(symbol, data_file):
    cfg = Config.load()
    cfg.trading.symbol = symbol
    cfg.trading.symbols = [symbol]
    eng = BacktestEngine(cfg, initial_balance=10000.0, symbol=symbol)
    with open(data_file) as f:
        data = json.load(f)
    eng.run(data)
    trades = []
    for c in eng._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
                trades.append(getattr(leg, "pnl", 0.0) or 0.0)
    wins = [p for p in trades if p > 0]
    losses = [abs(p) for p in trades if p < 0]
    gp = sum(wins)
    gl = sum(losses)
    np = gp - gl
    return len(trades), len(wins), len(losses), gp, gl, np


def main():
    x_t, x_w, x_l, x_gp, x_gl, x_np = get_pnl("XAUUSD", "data/genuine_jan_aug_2026_xauusd.json")
    n_t, n_w, n_l, n_gp, n_gl, n_np = get_pnl("USTECH100M", "data/genuine_jan_aug_2026_nas100.json")

    c_t = x_t + n_t
    c_w = x_w + n_w
    c_l = x_l + n_l
    c_gp = x_gp + n_gp
    c_gl = x_gl + n_gl
    c_np = c_gp - c_gl

    print("=" * 95)
    print("  EXACT GROSS PROFIT, GROSS LOSS & NET PROFIT BREAKDOWN (JAN - AUG 2026)")
    print("=" * 95)
    print(f"{'Asset / Engine':<20} | {'Trades (W/L)':>15} | {'Gross Profit ($)':>18} | {'Gross Loss ($)':>16} | {'Net Profit ($)':>16}")
    print("-" * 95)
    print(f"{'XAUUSD (Gold)':<20} | {f'{x_t} ({x_w}W / {x_l}L)':>15} | ${x_gp:>17,.2f} | ${x_gl:>15,.2f} | ${x_np:>15,.2f}")
    print(f"{'NAS100 (Nasdaq)':<20} | {f'{n_t} ({n_w}W / {n_l}L)':>15} | ${n_gp:>17,.2f} | ${n_gl:>15,.2f} | ${n_np:>15,.2f}")
    print("-" * 95)
    print(f"{'COMBINED PORTFOLIO':<20} | {f'{c_t} ({c_w}W / {c_l}L)':>15} | ${c_gp:>17,.2f} | ${c_gl:>15,.2f} | ${c_np:>15,.2f}")
    print("=" * 95)
    print(f"  - Starting Capital:  $10,000.00")
    print(f"  - Final Balance:     ${10000.0 + c_np:,.2f}")
    print(f"  - Net Return (ROI):  +{(c_np / 10000.0) * 100:.1f}%")
    print(f"  - Overall Win Rate:  {(c_w / c_t) * 100:.1f}%")
    print(f"  - Profit Factor:     {c_gp / c_gl:.2f}")
    print("=" * 95)


if __name__ == "__main__":
    main()
