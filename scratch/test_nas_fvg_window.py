import sys
import json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

with open("data/genuine_jan_aug_2026_nas100.json") as f:
    data_nas = json.load(f)

cfg = Config.load()
cfg.trading.symbol = "USTECH100M"
cfg.trading.symbols = ["USTECH100M"]

# Current baseline
print("=== BASELINE NAS100 ===")
engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M")
res = engine.run(data_nas)

monthly_trades = defaultdict(list)
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
            m = str(leg.open_time)[:7]
            monthly_trades[m].append(leg.pnl)

for m in sorted(monthly_trades.keys()):
    trades = monthly_trades[m]
    wins = len([p for p in trades if p > 0])
    pnl = sum(trades)
    print(f"  {m}: {len(trades)} trades, PnL = ${pnl:.2f}, WR = {wins/len(trades)*100:.1f}%")
print(f"TOTAL: {res['total_trades']} trades, PnL = ${res['total_pnl']:.2f}")
