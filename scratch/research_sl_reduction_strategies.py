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

    # 1. Baseline: Current Edge A (Partial at 1.0R, BE at 1.0R, 3.0 ATR Trail)
    cfg_base = Config.load()
    cfg_base.trading.runner_trail_atr_mult = 3.0
    eng_base = BacktestEngine(cfg_base, initial_balance=10000.0, symbol="XAUUSD")
    eng_base.run(data_xau)
    st_base = extract_stats(eng_base)

    # 2. Strategy 1: Delayed Bigger Partial TP (Tranche 1 at 1.5R instead of 1.0R, Tranche 2 at 2.5R)
    # Win bada hoga kyunki partial jaldi nahi cut hoga
    cfg_s1 = Config.load()
    cfg_s1.trading.runner_trail_atr_mult = 3.0
    cfg_s1.trading.partial_tp_tranche1_r = 1.5
    cfg_s1.trading.partial_tp_tranche1_pct = 30.0
    cfg_s1.trading.partial_tp_tranche2_r = 2.5
    cfg_s1.trading.partial_tp_tranche2_pct = 30.0
    cfg_s1.trading.xau_breakeven_r = 1.2
    eng_s1 = BacktestEngine(cfg_s1, initial_balance=10000.0, symbol="XAUUSD")
    eng_s1.run(data_xau)
    st_s1 = extract_stats(eng_s1)

    # 3. Strategy 2: Ultra-Asymmetric Target (Tranche 1 at 2.0R, Runner 60% with 3.5 ATR)
    cfg_s2 = Config.load()
    cfg_s2.trading.runner_trail_atr_mult = 3.5
    cfg_s2.trading.partial_tp_tranche1_r = 2.0
    cfg_s2.trading.partial_tp_tranche1_pct = 40.0
    cfg_s2.trading.runner_tranche_pct = 0.60
    cfg_s2.trading.xau_breakeven_r = 1.2
    eng_s2 = BacktestEngine(cfg_s2, initial_balance=10000.0, symbol="XAUUSD")
    eng_s2.run(data_xau)
    st_s2 = extract_stats(eng_s2)

    # 4. Strategy 3: Stagnation Stop (If trade doesn't move within 8 bars, exit early)
    cfg_s3 = Config.load()
    cfg_s3.trading.runner_trail_atr_mult = 3.0
    cfg_s3.trading.xau_stagnation_exit_enabled = True
    cfg_s3.trading.xau_stagnation_bars = 8
    cfg_s3.trading.xau_stagnation_min_r = 0.20
    eng_s3 = BacktestEngine(cfg_s3, initial_balance=10000.0, symbol="XAUUSD")
    eng_s3.run(data_xau)
    st_s3 = extract_stats(eng_s3)

    # 5. Strategy 4: Wider SL Buffer Floor ($7.00 vs $5.00)
    # Give SL more room so direct wick SL hits are eliminated
    cfg_s4 = Config.load()
    cfg_s4.trading.runner_trail_atr_mult = 3.0
    cfg_s4.trading.xau_min_sl_distance = 7.0
    eng_s4 = BacktestEngine(cfg_s4, initial_balance=10000.0, symbol="XAUUSD")
    eng_s4.run(data_xau)
    st_s4 = extract_stats(eng_s4)

    print("=" * 115)
    print("  RESEARCH MATRIX: SOLVING DIRECT SL vs SMALL PARTIAL TP")
    print("=" * 115)
    print(f"{'Strategy':<38} | {'Total PnL ($)':>13} | {'Win Rate':>8} | {'Avg Win':>10} | {'Avg Loss':>10} | {'W/L Ratio':>9} | {'PF':>5}")
    print("-" * 115)
    for name, s in [
        ("0. Current Edge A", st_base),
        ("1. Delayed Partial (1.5R + 2.5R)", st_s1),
        ("2. Ultra-Asymmetric (2.0R + 60% Runner)", st_s2),
        ("3. Fast Stagnation Defense (8 bars)", st_s3),
        ("4. Wider SL Breathing Floor ($7.00)", st_s4),
    ]:
        print(f"{name:<38} | ${s['pnl']:>12,.2f} | {s['wr']:>7.1f}% | ${s['avg_win']:>9.2f} | ${s['avg_loss']:>9.2f} | {s['win_loss_ratio']:>9.2f} | {s['pf']:>5.2f}")
    print("=" * 115)


if __name__ == "__main__":
    main()
