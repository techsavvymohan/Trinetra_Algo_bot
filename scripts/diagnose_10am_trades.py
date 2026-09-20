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
engine._vr_engine.neutral_target_r = 2.0
engine._vr_engine.neutral_be_trigger_r = 1.50
engine._vr_engine.neutral_min_atr_mult = 0.60
engine._vr_engine.neutral_min_body_ratio = 0.60
engine._vr_engine.trending_target_r = 2.0
engine._vr_engine.trending_be_trigger_r = 1.50
engine._vr_engine.trending_min_atr_mult = 0.60
engine._vr_engine.trending_min_body_ratio = 0.60
engine._vr_engine.compressed_target_r = 2.0
engine._vr_engine.compressed_be_trigger_r = 1.50
engine._vr_engine.compressed_min_atr_mult = 0.60
engine._vr_engine.compressed_min_body_ratio = 0.60
engine._test_full_london_trend = True

engine.run(raw_data)

# Find all 10:00-10:30 trades and examine their parameters
print("="*100)
print("INSPECTING 10:00-10:30 TRADES CHARACTERISTICS")
print("="*100)

for c in engine._clusters:
    first_leg = c.legs[0]
    dt = first_leg.open_time if isinstance(first_leg.open_time, datetime) else datetime.fromisoformat(str(first_leg.open_time))
    if dt.hour == 10 and dt.minute <= 30:
        c_pnl = sum(getattr(l, 'pnl', 0.0) or 0.0 for l in c.legs)
        # Check H1 EMA gap at entry time
        # Let's see what features distinguish winners from losers
        print(f"{dt.strftime('%Y-%m-%d %H:%M')} | {dt.strftime('%a')} | {c.direction.value:<4} | Cluster PnL: ${c_pnl:>8.2f} | Entry: {first_leg.entry_price:.2f} | SL: {first_leg.sl_price:.2f} | R: {c.r_distance():.2f}")
