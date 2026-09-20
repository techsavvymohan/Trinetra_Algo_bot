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

late_london_trades = []
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if dt.hour == 10 and dt.minute <= 30:
                late_london_trades.append((dt, leg))

print(f"TOTAL LATE LONDON (10:00-10:30 UTC) TRADES: {len(late_london_trades)}")
print(f"{'Date/Time':<17} {'Month':<5} {'Dir':<4} {'Entry':>8} {'SL':>8} {'TP':>8} {'PnL':>9} {'Reason'}")
print("-" * 80)
for dt, leg in sorted(late_london_trades, key=lambda x: x[0]):
    pnl = getattr(leg, 'pnl', 0.0) or 0.0
    reason = getattr(leg.exit_reason, 'value', str(leg.exit_reason))
    print(f"{dt.strftime('%Y-%m-%d %H:%M'):<17} {dt.strftime('%b'):<5} {leg.direction.value:<4} {leg.entry_price:>8.2f} {leg.sl_price:>8.2f} {leg.tp_price:>8.2f} ${pnl:>8.2f} {reason}")
