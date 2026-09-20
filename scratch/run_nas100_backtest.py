import os
import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

def test_nas100():
    cfg = Config.load()
    initial_balance = 10000.0
    cfg.trading.backtest_initial_balance = initial_balance
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0

    datasets = [
        ("data/genuine_jan_aug_2026_nas100.json", "Jan - Aug 2026 (Full 8 Months)"),
        ("data/genuine_recent_nas100.json", "Recent OOS Data"),
    ]

    for path, label in datasets:
        if not os.path.exists(path):
            print(f"File not found: {path}")
            continue

        print("=" * 80)
        print(f"  NAS100 / USTECH100M BACKTEST: {label}")
        print("=" * 80)

        with open(path, "r") as f:
            raw_nas = json.load(f)

        engine = BacktestEngine(cfg, initial_balance=initial_balance, symbol="USTECH100M")
        res = engine.run(raw_nas)

        print(f"  * Initial Balance    : ${res['initial_balance']:,.2f}")
        print(f"  * Final Balance      : ${res['final_balance']:,.2f}")
        print(f"  * Net Profit (PnL)   : +${res['total_pnl']:,.2f} ({res['return_pct']:+.2f}%)")
        print(f"  * Total Trades       : {res['total_trades']}")
        print(f"  * Win Rate           : {res['win_rate']:.2f}% ({res['wins']}W / {res['losses']}L)")
        print(f"  * Profit Factor      : {res['profit_factor']}")
        print(f"  * Max Drawdown       : {res['max_drawdown_pct']:.2f}%")
        print(f"  * Sharpe Ratio       : {res.get('sharpe_ratio', 'N/A')}")
        print(f"  * Expectancy         : ${res.get('expectancy', 0.0):.2f} per trade")
        print("-" * 80)

if __name__ == "__main__":
    test_nas100()
