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

def run_test(name, dynamic_late_london=True, win_done=False):
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
    engine._test_london_win_done = win_done

    if dynamic_late_london:
        # Override is_in_xau_london_killzone dynamically
        def dynamic_london_check(dt):
            if dt is None: return False
            h = dt.hour if hasattr(dt, "hour") else 0
            m = dt.minute if hasattr(dt, "minute") else 0
            # 07:45 - 10:00 always London
            if (h == 7 and m >= 45) or (8 <= h < 10):
                return True
            # 10:00 - 10:30 only if regime is TRENDING or ATR ratio >= 1.15
            if h == 10 and m <= 30:
                vr = getattr(engine, '_current_regime', None)
                if vr:
                    is_trending = (vr.regime == "TRENDING") or (vr.atr_ratio >= 1.15)
                    return is_trending
                return False
            return False

        cfg.trading.is_in_xau_london_killzone = dynamic_london_check

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
print("TESTING DYNAMIC REGIME-DRIVEN LATE LONDON EXTENSION")
print("="*100)

run_test("Test Dyn1: Dynamic 10:00-10:30 (Only when TRENDING or ATR>=1.15) without win_done", dynamic_late_london=True, win_done=False)
run_test("Test Dyn2: Dynamic 10:00-10:30 with London One-Win-Done", dynamic_late_london=True, win_done=True)
