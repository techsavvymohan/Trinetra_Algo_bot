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

# We can hook into order execution or cluster creation to record regime state
regimes_at_trade = {}
orig_execute = engine._execute_order

def recorded_execute(order, i, data_all):
    res = orig_execute(order, i, data_all)
    if res:
        regimes_at_trade[order['cluster_id']] = (engine._current_regime.regime, engine._current_regime.atr_ratio, engine._current_regime.adx_proxy)
    return res

engine._execute_order = recorded_execute

engine.run(raw_data)

print(f"{'Date/Time':<17} {'Month':<5} {'Dir':<4} {'PnL':>9} {'Regime':<12} {'ATR_Ratio':>10} {'ADX_Proxy':>10}")
print("-" * 75)
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
            if dt.hour == 10 and dt.minute <= 30:
                pnl = getattr(leg, 'pnl', 0.0) or 0.0
                reg_info = regimes_at_trade.get(c.cluster_id, ("UNKNOWN", 0.0, 0.0))
                print(f"{dt.strftime('%Y-%m-%d %H:%M'):<17} {dt.strftime('%b'):<5} {leg.direction.value:<4} ${pnl:>8.2f} {reg_info[0]:<12} {reg_info[1]:>10.2f} {reg_info[2]:>10.2f}")
