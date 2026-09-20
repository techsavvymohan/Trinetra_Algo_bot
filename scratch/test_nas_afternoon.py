"""Test NAS100 Afternoon Continuation Window (15:45 - 20:00 UTC) monthly breakdown."""
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from scratch.run_combined_xau_nas_full_backtest import load_stitched_nas100, extract_trades

def test_afternoon_nas():
    data_nas = load_stitched_nas100()

    cfg = Config.load()
    cfg.trading.symbol = "USTECH100M"
    cfg.trading.symbols = ["USTECH100M"]
    cfg.trading.backtest_apply_friction = True
    cfg.trading.enable_conviction_sizing = True
    cfg.trading.conviction_scale_nas_a_plus = 2.40
    cfg.trading.conviction_scale_a = 1.00
    cfg.trading.nas_session_start_hour = 15
    cfg.trading.nas_killzone_morning_start_min = 45
    cfg.trading.nas_stagnation_bars = 45
    cfg.trading.backtest_commission_per_lot = 0.0

    eng = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M")
    res = eng.run(data_nas)
    trades = extract_trades(eng, "USTECH100M")

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    pnl = sum(t["pnl"] for t in trades)
    wr = (len(wins) / len(trades) * 100) if trades else 0.0

    print("="*75)
    print(f"  NAS100 AFTERNOON WINDOW (15:45 - 20:00 UTC)")
    print("="*75)
    print(f"  Total Trades : {len(trades)}")
    print(f"  Win Rate     : {wr:.2f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Net Profit   : ${pnl:,.2f}")
    print(f"  Profit Factor: {res.get('profit_factor', 0.0):.2f}")
    print(f"  Max DD       : {res.get('max_drawdown_pct', 0.0):.2f}%")

    # Monthly breakdown
    monthly = defaultdict(list)
    for t in trades:
        m = t["open_time"].strftime("%Y-%m")
        monthly[m].append(t)

    print("\n  Monthly Breakdown:")
    for m in sorted(monthly.keys()):
        m_trades = monthly[m]
        m_wins = len([t for t in m_trades if t["pnl"] > 0])
        m_pnl = sum(t["pnl"] for t in m_trades)
        m_wr = (m_wins / len(m_trades) * 100) if m_trades else 0.0
        status = "[GREEN]" if m_pnl > 0 else "[RED]"
        print(f"    {m}: {len(m_trades):2d} trades | WR: {m_wr:5.1f}% | PnL: ${m_pnl:>9.2f} {status}")

if __name__ == "__main__":
    test_afternoon_nas()
