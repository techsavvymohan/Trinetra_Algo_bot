import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.config import Config
from xauusd_bot.models import TradeDirection, SignalGrade

import json

data_gold = "data/full_2026_xauusd.json"
data_nas = "data/full_2026_nas100.json"
print("Loading datasets from disk...")
with open(data_gold, "r") as f:
    data_gold_dict = json.load(f)
with open(data_nas, "r") as f:
    data_nas_dict = json.load(f)

def run_sim(label, config_modifier=None):
    cfg = Config()
    cfg.trading.backtest_apply_friction = True
    cfg.trading.enable_profit_compounding = True
    cfg.trading.initial_account_balance = 10000.0
    cfg.trading.xau_partial_close_enabled = True
    if config_modifier:
        config_modifier(cfg)
    
    eng_gold = BacktestEngine(cfg, symbol="XAUUSD", initial_balance=10000.0)
    rep_gold = eng_gold.run(data_gold_dict)
    
    eng_nas = BacktestEngine(cfg, symbol="USTECH100M", initial_balance=10000.0)
    rep_nas = eng_nas.run(data_nas_dict)
    
    tot_pnl = rep_gold["total_pnl"] + rep_nas["total_pnl"]
    tot_trades = rep_gold["total_trades"] + rep_nas["total_trades"]
    tot_wins = rep_gold["wins"] + rep_nas["wins"]
    wr = (tot_wins / tot_trades * 100) if tot_trades > 0 else 0.0
    
    print(f"\n--- {label} ---")
    print(f"Total PnL   : ${tot_pnl:,.2f}")
    print(f"Total Trades: {tot_trades} (Win Rate: {wr:.1f}%)")
    print(f"Gold PnL    : ${rep_gold['total_pnl']:,.2f} ({rep_gold['total_trades']} trades, {rep_gold['win_rate']:.1f}% WR)")
    print(f"Nas PnL     : ${rep_nas['total_pnl']:,.2f} ({rep_nas['total_trades']} trades, {rep_nas['win_rate']:.1f}% WR)")
    return rep_gold, rep_nas

print("Running Diagnostic Overfitting Comparison...")

# 1. Baseline Current
def mod_baseline(cfg): pass
run_sim("1. Current Production Settings", mod_baseline)

# 2. Test Removing Overfitted A+ Bias Block (xau_a_plus_block_h1_bullish=False)
def mod_unblock_bullish(cfg):
    cfg.trading.xau_a_plus_block_h1_bullish = False
run_sim("2. Without 'xau_a_plus_block_h1_bullish' (Natural Trend Following)", mod_unblock_bullish)

# 3. Test Normalizing Unicorn Conviction Sizing (scale 2.6x -> 1.5x)
def mod_conviction_scaled(cfg):
    cfg.trading.conviction_scale_a_plus = 1.50
    cfg.trading.conviction_scale_nas_a_plus = 1.50
run_sim("3. Normalized Conviction (1.50x instead of 2.60x curve-fit)", mod_conviction_scaled)

# 4. Test Disabling 'xau_london_protect_profits' (allow clean continuation trades)
def mod_london_protect(cfg):
    cfg.trading.xau_london_protect_profits = False
run_sim("4. Without 'xau_london_protect_profits' (No Early Lockout)", mod_london_protect)
