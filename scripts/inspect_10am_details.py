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

target_dates = {"2026-02-12", "2026-02-18", "2026-02-27", "2026-04-20", "2026-04-21", "2026-04-22", "2026-05-12", "2026-05-28", "2026-06-03", "2026-06-04", "2026-06-08", "2026-07-31", "2026-08-20"}

for c in engine._clusters:
    first_leg = c.legs[0]
    dt = first_leg.open_time if isinstance(first_leg.open_time, datetime) else datetime.fromisoformat(str(first_leg.open_time))
    d_str = dt.strftime('%Y-%m-%d')
    if d_str in target_dates and dt.hour == 10 and dt.minute <= 30:
        c_pnl = sum(getattr(l, 'pnl', 0.0) or 0.0 for l in c.legs)
        # Check hierarchy or sweep info
        print(f"{dt.strftime('%Y-%m-%d %H:%M')} | {c.direction.value:<4} | PnL: ${c_pnl:>8.2f}")
