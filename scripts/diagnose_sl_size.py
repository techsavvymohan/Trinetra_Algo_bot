"""Diagnose average SL dollar size and R-to-SL distance for losing vs winning trades by month"""
import sys, json
from datetime import datetime
from pathlib import Path
BASE_DIR = Path(r"e:/XAUUSD digger bot")
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

with open(r"e:/XAUUSD digger bot/data/genuine_jan_aug_2026_xauusd.json") as f:
    raw_data = json.load(f)

cfg = Config.load()
cfg.trading.backtest_initial_balance = 10000.0
cfg.trading.backtest_apply_friction = True
cfg.trading.backtest_commission_per_lot = 6.0
engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
res = engine.run(raw_data)

NAMES = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",7:"Jul",8:"Aug"}
print("\n" + "="*100)
print("SL DISTANCE ANALYSIS (What causes -$700 losses in June/July?)")
print("="*100)
print(f"{'Month':<6} {'WinTrades':<11} {'LossTrades':<12} {'SL $dist Wins':>14} {'SL $dist Loss':>14} {'Avg R-move Win':>15} {'TP $dist':>10}")
print("-"*100)

for m in range(1, 9):
    wins_sl = []   # SL distance in $ for WINNING trades
    loss_sl = []   # SL distance in $ for LOSING trades
    wins_move = [] # actual price move for winners (exit - entry)
    tp_dist = []   # TP distance in $ for all trades

    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                if dt.month != m:
                    continue
                pnl = getattr(leg, "pnl", 0.0)
                if pnl is None:
                    continue

                # SL distance in price points (Gold: $1 per point per lot)
                sl_dist = abs(leg.entry_price - leg.sl_price)
                tp_d = abs(leg.tp_price - leg.entry_price)
                lot = leg.lot_size

                if pnl > 0.01:
                    wins_sl.append(sl_dist)
                    move = abs(leg.exit_price - leg.entry_price)
                    wins_move.append(move)
                    tp_dist.append(tp_d)
                elif pnl < -0.01:
                    loss_sl.append(sl_dist)

    avg_w_sl = sum(wins_sl)/len(wins_sl) if wins_sl else 0
    avg_l_sl = sum(loss_sl)/len(loss_sl) if loss_sl else 0
    avg_move = sum(wins_move)/len(wins_move) if wins_move else 0
    avg_tp   = sum(tp_dist)/len(tp_dist) if tp_dist else 0

    print(f"{NAMES[m]:<6} {len(wins_sl):<11} {len(loss_sl):<12} ${avg_w_sl:>12.2f} ${avg_l_sl:>12.2f} ${avg_move:>13.2f} ${avg_tp:>8.2f}")

print("="*100)
