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

for d_str in sorted(target_dates):
    day_clusters = []
    for c in engine._clusters:
        first_leg = c.legs[0]
        dt = first_leg.open_time if isinstance(first_leg.open_time, datetime) else datetime.fromisoformat(str(first_leg.open_time))
        if dt.strftime('%Y-%m-%d') == d_str:
            c_pnl = sum(getattr(l, 'pnl', 0.0) or 0.0 for l in c.legs)
            day_clusters.append((dt, c.direction.value, c_pnl, c.r_distance()))
    print(f"Date: {d_str}")
    for dt, direction, pnl, r_dist in day_clusters:
        print(f"   {dt.strftime('%H:%M')} | {direction:<4} | PnL: ${pnl:>8.2f} | R: {r_dist:.2f}")
