import sys, os, json
from datetime import datetime
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

with open('data/genuine_jan_aug_2026_xauusd.json', 'r') as f:
    raw_data = json.load(f)

cfg = Config.load()
cfg.trading.backtest_initial_balance = 10000.0
cfg.trading.backtest_apply_friction = True
cfg.trading.backtest_commission_per_lot = 6.0

engine = BacktestEngine(cfg, initial_balance=10000.0, symbol='XAUUSD')
res = engine.run(raw_data)

for m in [1, 2, 3, 4, 5, 6, 7, 8]:
    m_trades = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(leg.open_time)
                if dt.month == m:
                    m_trades.append(getattr(leg, 'pnl', 0.0))
    wins = [p for p in m_trades if p > 0.01]
    losses = [p for p in m_trades if p < -0.01]
    avg_w = sum(wins)/len(wins) if wins else 0
    avg_l = sum(losses)/len(losses) if losses else 0
    ratio = abs(avg_w / avg_l) if avg_l else 0
    net = sum(m_trades)
    print(f"Month {m:02d}: Trades={len(m_trades):<3} | Wins={len(wins):<2} | Losses={len(losses):<2} | AvgWin=${avg_w:>7.2f} | AvgLoss=${avg_l:>7.2f} | Payoff={ratio:.2f} | Net=${net:>9.2f}")
