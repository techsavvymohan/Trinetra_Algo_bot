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
res = engine.run(raw_data)

trades = []
weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price:
            dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(leg.open_time)
            trades.append({
                'dt': dt,
                'wday': weekday_names[dt.weekday()],
                'hour': dt.hour,
                'minute': dt.minute,
                'pnl': getattr(leg, 'pnl', 0.0),
                'lot': leg.lot_size
            })

base_pnl = sum(t['pnl'] for t in trades)
print(f"Baseline Total Net PnL: ${base_pnl:,.2f}")

# Scenario 1: Friday Stop after London (no entries after 11:30 UTC on Friday)
trades_scen_1 = [t for t in trades if not (t['wday'] == 'Friday' and (t['hour'] > 11 or (t['hour'] == 11 and t['minute'] >= 30)))]
pnl_1 = sum(t['pnl'] for t in trades_scen_1)
print(f"Scenario 1 (Friday Skip NY Session): ${pnl_1:,.2f} | Net Improvement: +${pnl_1 - base_pnl:,.2f}")

# Scenario 2: Tuesday Half-Risk (1.5% instead of 3.5%) + Friday Skip NY
pnl_2 = 0.0
for t in trades_scen_1:
    if t['wday'] == 'Tuesday':
        pnl_2 += t['pnl'] * (1.5 / 3.5)
    else:
        pnl_2 += t['pnl']
print(f"Scenario 2 (Tuesday 1.5% Risk + Friday Skip NY): ${pnl_2:,.2f} | Net Improvement: +${pnl_2 - base_pnl:,.2f}")

# Scenario 3: Tuesday Skip Entirely + Friday Skip NY
trades_scen_3 = [t for t in trades_scen_1 if t['wday'] != 'Tuesday']
pnl_3 = sum(t['pnl'] for t in trades_scen_3)
print(f"Scenario 3 (Skip Tuesday Completely + Friday Skip NY): ${pnl_3:,.2f} | Net Improvement: +${pnl_3 - base_pnl:,.2f}")
