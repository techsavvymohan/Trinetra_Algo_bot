import sys
import os
import json
from datetime import datetime, timezone

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, '.')

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

with open('data/genuine_jan_aug_2026_xauusd.json') as f:
    xau_data = json.load(f)

print("Testing 1-Month Profit Capacity (August 2026, $10,000 Starting Balance)...", flush=True)

start_aug = datetime(2026, 8, 1, tzinfo=timezone.utc)
end_aug = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)

for risk in [0.01, 0.02, 0.03, 0.04, 0.05]:
    cfg = Config.load()
    cfg.trading.xau_risk_per_trade = risk
    cfg.trading.pyramid_initial_risk_pct = risk * 100
    cfg.trading.xau_partial_close_enabled = True
    cfg.trading.partial_take_profit_r = 1.0
    cfg.trading.xau_target_r = 1.8
    cfg.trading.xau_breakeven_trigger_r = 1.0
    cfg.trading.xau_strict_killzones = False
    cfg.trading.max_daily_trades = 8
    cfg.trading.daily_loss_limit_pct = 20.0  # Real account unconstrained
    cfg.trading.max_dd_limit_pct = 35.0     # Real account unconstrained
    cfg.trading.enable_profit_compounding = True

    eng = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD", start_date=start_aug, end_date=end_aug)
    res = eng.run(xau_data)
    pnl = res.get("total_pnl", 0.0)
    ret = res.get("return_pct", 0.0)
    trades = res.get("total_trades", 0)
    wr = res.get("win_rate", 0.0)
    dd = res.get("max_drawdown_pct", 0.0)
    pf = res.get("profit_factor", 0.0)
    print(f"Risk {risk*100:.1f}% -> 1-Month PnL: ${pnl:+8.2f} ({ret:+5.1f}%) | Trades: {trades:2d} | WR: {wr:4.1f}% | PF: {pf:4.2f} | MaxDD: {dd:4.2f}%", flush=True)
