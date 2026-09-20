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

def run_test(name, cutoff_hour=10, cutoff_min=30, win_done=False):
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = 10000.0
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0
    
    # Custom method
    def custom_in_london(dt):
        if dt is None: return False
        h = dt.hour if hasattr(dt, "hour") else 0
        m = dt.minute if hasattr(dt, "minute") else 0
        return (h == 7 and m >= 45) or (8 <= h < cutoff_hour) or (h == cutoff_hour and m <= cutoff_min)
    
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
    engine._test_london_win_done = win_done

    res = engine.run(raw_data)
    
    monthly = {}
    for m in range(1, 9):
        mt = []
        for c in engine._clusters:
            for leg in c.legs:
                if leg.status == TradeStatus.CLOSED and leg.exit_price:
                    dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                    if dt.month == m:
                        mt.append(getattr(leg, 'pnl', 0.0) or 0.0)
        monthly[m] = sum(mt)
    
    tot = res.get('total_pnl', 0.0)
    NAMES = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',7:'Jul',8:'Aug'}
    m_str = ' | '.join(f"{NAMES[m]}:{monthly[m]:>6.0f}" for m in range(1, 9))
    print(f"\n[{name}] Total: ${tot:>8.2f} (WR: {res.get('win_rate',0):.1f}%, DD: {res.get('max_drawdown',0):.2f}%)")
    print(f"   {m_str}")
    return tot, monthly

print("="*100)
print("TESTING LONDON CUTOFF OPTIMIZATIONS")
print("="*100)

run_test("Test A: Cutoff 10:30 (Current Test 3)", cutoff_hour=10, cutoff_min=30, win_done=False)
run_test("Test B: Cutoff 10:00 (No late London chop)", cutoff_hour=10, cutoff_min=0, win_done=False)
run_test("Test C: Cutoff 10:00 + One-Win-Done", cutoff_hour=10, cutoff_min=0, win_done=True)
run_test("Test D: Cutoff 09:45", cutoff_hour=9, cutoff_min=45, win_done=False)
