import sys
sys.path.insert(0, ".")
import json
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

with open("data/genuine_jan_aug_2026_xauusd.json") as f:
    raw = json.load(f)

# Test 1: No Pyramiding (max_pyramid_entries = 1)
cfg1 = Config.load()
cfg1.trading.enable_fvg_pyramiding = False
cfg1.trading.max_pyramid_entries = 1
e1 = BacktestEngine(cfg1, initial_balance=10000.0, symbol="XAUUSD")
r1 = e1.run(raw)

# Test 2: Current Pyramiding (max_pyramid_entries = 2 / +1 Pyramid when Breakeven)
cfg2 = Config.load()
cfg2.trading.enable_fvg_pyramiding = True
cfg2.trading.max_pyramid_entries = 2
e2 = BacktestEngine(cfg2, initial_balance=10000.0, symbol="XAUUSD")
r2 = e2.run(raw)

# Test 3: Aggressive Pyramiding (max_pyramid_entries = 3)
cfg3 = Config.load()
cfg3.trading.enable_fvg_pyramiding = True
cfg3.trading.max_pyramid_entries = 3
e3 = BacktestEngine(cfg3, initial_balance=10000.0, symbol="XAUUSD")
r3 = e3.run(raw)

print("="*80)
print("PYRAMIDING ABLATION TEST ON GENUINE XAUUSD (JAN - AUG 2026)")
print("="*80)
for label, r in [("1. Single Entry Only (No Pyramiding)", r1), 
                 ("2. +1 Pyramid Allowed (Max 2 Legs)", r2), 
                 ("3. +2 Pyramid Allowed (Max 3 Legs)", r3)]:
    pnl = r['total_pnl']
    ret = (pnl / 10000.0) * 100
    trades = r['total_trades']
    wr = r['win_rate']
    pf = r['profit_factor']
    dd = r['max_drawdown_pct']
    sharpe = r['sharpe_ratio']
    pyra_legs = r['ablation'].get('pyramid_legs_added', 0)
    print(f"{label:<38} | PnL: ${pnl:>8.2f} ({ret:>+6.2f}%) | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | DD: {dd:>4.2f}% | Sharpe: {sharpe:>4.2f} | Pyra Legs: {pyra_legs}")
print("="*80)
