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

def custom_in_london(dt):
    if dt is None: return False
    h = dt.hour if hasattr(dt, "hour") else 0
    m = dt.minute if hasattr(dt, "minute") else 0
    return (h == 7 and m >= 45) or (8 <= h < 10)

cfg.trading.is_in_xau_london_killzone = custom_in_london

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
    if (h == 7 and m >= 45) or (8 <= h < 10):
        return "LONDON"
    elif (h == 13 and m >= 30) or (14 <= h < 16) or (h == 16 and m <= 30):
        return "NY"
    return "OTHER"

for target_m, m_name in [(6, "JUNE"), (7, "JULY")]:
    m_trades = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                if dt.month == target_m:
                    m_trades.append((dt, leg))

    print("=" * 100)
    print(f"{m_name} TRADES WITH 10:00 UTC CUTOFF (Count: {len(m_trades)})")
    print(f"{'Date/Time':<17} {'Sess':<7} {'Dir':<4} {'Entry':>8} {'SL':>8} {'TP':>8} {'Exit':>8} {'PnL':>9} {'Reason'}")
    print("-" * 100)
    tot = 0.0
    wins, losses = 0, 0
    for dt, leg in sorted(m_trades, key=lambda x: x[0]):
        sess = get_session(dt)
        pnl = getattr(leg, 'pnl', 0.0) or 0.0
        tot += pnl
        if pnl > 0: wins += 1
        else: losses += 1
        reason = getattr(leg.exit_reason, 'value', str(leg.exit_reason))
        print(f"{dt.strftime('%Y-%m-%d %H:%M'):<17} {sess:<7} {leg.direction.value:<4} {leg.entry_price:>8.2f} {leg.sl_price:>8.2f} {leg.tp_price:>8.2f} {leg.exit_price:>8.2f} ${pnl:>8.2f} {reason}")
    print("-" * 100)
    print(f"{m_name} Total PnL: ${tot:.2f} | Wins: {wins}, Losses: {losses}, WinRate: {wins/(wins+losses)*100:.1f}%\n")
