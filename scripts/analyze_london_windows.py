import sys, os, json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

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

# Breakdown of London trades by 30-min time buckets
buckets = defaultdict(list)
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            sess = get_session(dt)
            if sess == "LONDON":
                pnl = getattr(leg, 'pnl', 0.0) or 0.0
                bucket_key = f"{dt.hour:02d}:{'00-29' if dt.minute < 30 else '30-59'}"
                buckets[bucket_key].append((dt.month, pnl))

print(f"{'Time Bucket':<12} {'Total Trades':<12} {'Win%':<8} {'Total PnL':>10} {'Jun PnL':>10} {'Jul PnL':>10} {'Other Mos':>10}")
print("-" * 75)
for b in sorted(buckets.keys()):
    trades = buckets[b]
    cnt = len(trades)
    wins = sum(1 for m, p in trades if p > 0)
    wr = wins / cnt * 100 if cnt > 0 else 0
    tot = sum(p for m, p in trades)
    jun = sum(p for m, p in trades if m == 6)
    jul = sum(p for m, p in trades if m == 7)
    oth = sum(p for m, p in trades if m not in (6, 7))
    print(f"{b:<12} {cnt:<12} {wr:<7.1f}% ${tot:>9.2f} ${jun:>9.2f} ${jul:>9.2f} ${oth:>9.2f}")
