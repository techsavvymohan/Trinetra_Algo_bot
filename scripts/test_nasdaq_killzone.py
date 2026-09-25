import json
from datetime import datetime, timezone
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeDirection

with open("data/full_2026_nas100.json", "r") as f:
    nas = json.load(f)

cfg = Config.load()
cfg.trading.backtest_initial_balance = 10000.0
cfg.trading.backtest_apply_friction = True
cfg.trading.backtest_commission_per_lot = 6.0

engine = BacktestEngine(
    cfg,
    initial_balance=10000.0,
    symbol="USTECH100M",
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    end_date=datetime(2026, 9, 24, 23, 59, 59, tzinfo=timezone.utc),
)

orig_generate = engine._generate_signal
def patched_gen(h_res, d_all, p, current_time=None):
    if current_time:
        h = current_time.hour
        m = current_time.minute
        # Strict NY Cash Open Drive: 13:30 to 16:00 UTC (9:30 AM to 12:00 PM NY)
        if not ((h == 13 and m >= 30) or (14 <= h < 16)):
            return None
    return orig_generate(h_res, d_all, p, current_time=current_time)

engine._generate_signal = patched_gen

# Also add 2.0x ATR buffer on SL
orig_detect = engine.trigger.detect_xau_scalp_sequence
def patched_detect(*args, **kwargs):
    seq = orig_detect(*args, **kwargs)
    if seq:
        m1_atr = kwargs.get("m1_atr", 1.0)
        ep = seq["entry_price"]
        direction = seq["direction"]
        pad = max(m1_atr * 2.0, 4.0 if ep > 5000 else 0.8)
        if direction == TradeDirection.BUY:
            new_sl = seq["sweep_low"] - pad
            risk = ep - new_sl
            if risk > 0:
                seq["sl_price"] = round(new_sl, 1)
                seq["tp_price"] = round(ep + (risk * kwargs.get("target_r", 2.0)), 1)
        else:
            new_sl = seq["sweep_high"] + pad
            risk = new_sl - ep
            if risk > 0:
                seq["sl_price"] = round(new_sl, 1)
                seq["tp_price"] = round(ep - (risk * kwargs.get("target_r", 2.0)), 1)
    return seq

engine.trigger.detect_xau_scalp_sequence = patched_detect

res = engine.run(nas)
trades = [t for c in engine._clusters for t in c.legs if t.status.name == "CLOSED"]
wins = [t for t in trades if t.pnl > 0.01]
losses = [t for t in trades if t.pnl < -0.01]
wr = len(wins) / len(trades) * 100 if trades else 0
pnl = res.get("total_pnl", sum(t.pnl for t in trades))
max_dd = res.get("max_drawdown_pct", 0)

print("=" * 60)
print(f"USTECH100M (NY Open Drive 13:30-16:00 UTC + ATR Buffer):")
print(f"  Net PnL       : {'+' if pnl >= 0 else ''}${pnl:,.2f}")
print(f"  Total Trades  : {len(trades)} ({len(wins)}W / {len(losses)}L)")
print(f"  Win Rate      : {wr:.1f}%")
print(f"  Max Drawdown  : {max_dd:.2f}%")
print("=" * 60)
