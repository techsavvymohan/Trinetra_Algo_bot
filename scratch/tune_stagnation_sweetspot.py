import json
import sys
import numpy as np
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus


def extract_stats(engine):
    trades = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
                pnl = getattr(leg, "pnl", 0.0) or 0.0
                trades.append(pnl)
    wins = [p for p in trades if p > 0]
    losses = [abs(p) for p in trades if p < 0]
    total_pnl = sum(trades)
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else 99.9
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    return {
        "pnl": total_pnl,
        "wr": wr,
        "trades": len(trades),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "pf": pf,
    }


def main():
    with open("data/genuine_jan_aug_2026_xauusd.json") as f:
        data_xau = json.load(f)

    print("=" * 115)
    print("  FINE-TUNING STAGNATION DEFENSE TO CRUSH AVERAGE LOSS WITHOUT SACRIFICING PROFIT")
    print("=" * 115)

    bars_to_test = [10, 12, 14, 16, 18, 20]
    print(f"{'Bars to Cut Stagnant Trade':<30} | {'Total PnL ($)':>13} | {'Win Rate':>8} | {'Avg Win':>10} | {'Avg Loss':>10} | {'W/L Ratio':>9} | {'PF':>5}")
    print("-" * 115)

    for b in bars_to_test:
        cfg = Config.load()
        cfg.trading.runner_trail_atr_mult = 3.0
        cfg.trading.xau_stagnation_exit_enabled = True
        cfg.trading.xau_stagnation_bars = b
        cfg.trading.xau_stagnation_min_r = 0.30
        eng = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
        eng.run(data_xau)
        s = extract_stats(eng)
        print(f"{f'Stagnation at {b} bars':<30} | ${s['pnl']:>12,.2f} | {s['wr']:>7.1f}% | ${s['avg_win']:>9.2f} | ${s['avg_loss']:>9.2f} | {s['win_loss_ratio']:>9.2f} | {s['pf']:>5.2f}")

    print("=" * 115)


if __name__ == "__main__":
    main()
