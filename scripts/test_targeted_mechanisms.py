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

def run_test(name, modify_cfg_fn=None, modify_engine_fn=None):
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = 10000.0
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0
    if modify_cfg_fn:
        modify_cfg_fn(cfg)
    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol='XAUUSD')
    if modify_engine_fn:
        modify_engine_fn(engine)
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
print("TESTING STRATEGIC COMBINATIONS ON CLEAN ENGINE")
print("="*100)

# 1. Current Baseline as is (skip for speed)
# run_test("Current Code (Regime + G5 + G5b)")

# 2. Disable regime engine alterations (target_r=2.0, min_atr=0.60, be_trigger=1.50)
def pure_regime_neutral(engine):
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

run_test("Test 2: Baseline Optimal (No TP/BE Distortion) + G5 + G5b", modify_engine_fn=pure_regime_neutral)

# 3. Test Enhancement A: Full London H1 Trend Filter
def cfg_full_london_trend(cfg):
    cfg.trading.xau_london_require_h1_trend = True

def engine_full_london_trend(engine):
    pure_regime_neutral(engine)
    engine._test_full_london_trend = True

run_test("Test 3: Baseline Optimal + Full London H1 Trend Filter", modify_engine_fn=engine_full_london_trend)

# 4. Test Enhancement: London Protect Profits (after 1 winning trade in London, done for London)
def engine_london_win_done(engine):
    engine_full_london_trend(engine)
    engine._test_london_win_done = True

run_test("Test 4: Test 3 + London One-Win-Done", modify_engine_fn=engine_london_win_done)


