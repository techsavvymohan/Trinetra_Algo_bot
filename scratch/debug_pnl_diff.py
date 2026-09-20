import sys
sys.path.insert(0, ".")
import json
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

with open("data/genuine_jan_aug_2026_xauusd.json") as f:
    raw = json.load(f)

cfg_load = Config.load()
print("cfg_load.trading.enable_profit_compounding:", cfg_load.trading.enable_profit_compounding)
print("cfg_load.trading.pyramid_initial_risk_pct:", cfg_load.trading.pyramid_initial_risk_pct)
print("cfg_load.trading.xau_risk_per_trade:", cfg_load.trading.xau_risk_per_trade)

cfg_direct = Config()
print("cfg_direct.trading.enable_profit_compounding:", cfg_direct.trading.enable_profit_compounding)
print("cfg_direct.trading.pyramid_initial_risk_pct:", cfg_direct.trading.pyramid_initial_risk_pct)
print("cfg_direct.trading.xau_risk_per_trade:", cfg_direct.trading.xau_risk_per_trade)

eng1 = BacktestEngine(cfg_load, initial_balance=10000.0, symbol="XAUUSD")
print("eng1.sizer.enable_profit_compounding:", eng1.sizer.enable_profit_compounding)
print("eng1.sizer.initial_risk_pct:", eng1.sizer.initial_risk_pct)
res1 = eng1.run(raw)
print(f"Result with cfg_load (current): PnL = ${res1['total_pnl']:.2f}")

eng2 = BacktestEngine(cfg_direct, initial_balance=10000.0, symbol="XAUUSD")
print("eng2.sizer.enable_profit_compounding:", eng2.sizer.enable_profit_compounding)
print("eng2.sizer.initial_risk_pct:", eng2.sizer.initial_risk_pct)
res2 = eng2.run(raw)
print(f"Result with cfg_direct: PnL = ${res2['total_pnl']:.2f}")
