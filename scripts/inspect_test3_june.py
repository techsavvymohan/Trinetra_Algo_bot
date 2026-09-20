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

def get_session(dt):
    h, m = dt.hour, dt.minute
    if (h == 7 and m >= 45) or (8 <= h < 10) or (h == 10 and m <= 30):
        return "LONDON"
    elif (h == 13 and m >= 30) or (14 <= h < 16) or (h == 16 and m <= 30):
        return "NY"
    return "OTHER"

june_trades = []
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if dt.month == 6:
                june_trades.append((dt, leg))

print(f"Total June Trades in Test 3: {len(june_trades)}")
print(f"{'Date/Time':<17} {'Sess':<7} {'Dir':<4} {'Entry':>8} {'SL':>8} {'TP':>8} {'Exit':>8} {'PnL':>9} {'Reason'}")
print("-" * 95)
net_pnl = 0.0
for dt, leg in sorted(june_trades, key=lambda x: x[0]):
    sess = get_session(dt)
    pnl = getattr(leg, 'pnl', 0.0) or 0.0
    net_pnl += pnl
    reason = getattr(leg.exit_reason, 'value', str(leg.exit_reason))
    print(f"{dt.strftime('%Y-%m-%d %H:%M'):<17} {sess:<7} {leg.direction.value:<4} {leg.entry_price:>8.2f} {leg.sl_price:>8.2f} {leg.tp_price:>8.2f} {leg.exit_price:>8.2f} ${pnl:>8.2f} {reason}")
print("-" * 95)
print(f"June Net PnL: ${net_pnl:.2f}")
