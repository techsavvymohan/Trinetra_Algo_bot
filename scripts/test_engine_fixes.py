import sys, os, json
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

with open('data/genuine_jan_aug_2026_xauusd.json', 'r') as f:
    raw_data = json.load(f)

# Patch BacktestEngine to support friday_skip_ny_session and tuesday_trade_enabled
orig_run = BacktestEngine.run

def test_config_variant(friday_skip_ny, tuesday_enabled, tuesday_risk_mult=1.0):
    cfg = Config.load()
    cfg.trading.backtest_initial_balance = 10000.0
    cfg.trading.backtest_apply_friction = True
    cfg.trading.backtest_commission_per_lot = 6.0
    cfg.trading.friday_skip_ny_session = friday_skip_ny
    cfg.trading.tuesday_trade_enabled = tuesday_enabled
    cfg.trading.tuesday_risk_mult = tuesday_risk_mult

    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol='XAUUSD')

    # We patch the step in engine that checks killzones
    # In engine.run, line 165 checks xau_strict_killzones
    # Let's run and filter
    return engine.run(raw_data)

print("Running baseline...")
cfg_base = Config.load()
cfg_base.trading.backtest_initial_balance = 10000.0
cfg_base.trading.backtest_apply_friction = True
cfg_base.trading.backtest_commission_per_lot = 6.0
eng = BacktestEngine(cfg_base, initial_balance=10000.0, symbol='XAUUSD')
res = eng.run(raw_data)
print(f"Baseline: PnL=+${res['total_pnl']:,.2f} (+{res['return_pct']}%), Trades={res['total_trades']}, WR={res['win_rate']}%, MaxDD={res['max_drawdown_pct']}%, PF={res['profit_factor']}")
