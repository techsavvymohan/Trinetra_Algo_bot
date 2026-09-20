import sys, json
from datetime import datetime
from pathlib import Path
BASE_DIR = Path(r'e:/XAUUSD digger bot')
sys.path.insert(0, str(BASE_DIR))
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus

with open(r'e:/XAUUSD digger bot/data/genuine_jan_aug_2026_xauusd.json') as f:
    raw_data = json.load(f)

cfg = Config.load()
cfg.trading.backtest_initial_balance = 10000.0
cfg.trading.backtest_apply_friction = True
cfg.trading.backtest_commission_per_lot = 6.0
engine = BacktestEngine(cfg, initial_balance=10000.0, symbol='XAUUSD')
res = engine.run(raw_data)

NAMES = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',7:'Jul',8:'Aug'}
print('\n' + '='*90)
print('DYNAMIC VOLATILITY-REGIME ENGINE  -  BACKTEST JAN-AUG 2026')
print('='*90)
print(f"{'Month':<6} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'AvgWin':>9} {'AvgLoss':>9} {'Payoff':>7} {'Net':>11} Status")
print('-'*90)

for m in range(1, 9):
    mt = []
    for c in engine._clusters:
        for leg in c.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                dt = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                if dt.month == m:
                    mt.append(getattr(leg, 'pnl', 0.0))
    wins   = [p for p in mt if p >  0.01]
    losses = [p for p in mt if p < -0.01]
    aw = sum(wins)/len(wins) if wins else 0
    al = sum(losses)/len(losses) if losses else 0
    ratio = abs(aw/al) if al else 0
    net = sum(mt)
    flag = 'GREEN' if net >= 0 else 'RED  '
    print(f"{NAMES[m]:<6} {len(mt):<8} {len(wins):<6} {len(losses):<6} ${aw:>8.2f} ${al:>8.2f} {ratio:>7.2f} ${net:>10.2f}  [{flag}]")

print('='*90)
pnl  = res.get('total_pnl', 0)
wr   = res.get('win_rate', 0)
mdd  = res.get('max_drawdown', 0)
ret  = res.get('return_pct', 0)
pf   = res.get('profit_factor', 0)
po   = res.get('payoff_ratio', 0)
exp  = res.get('expectancy', 0)
print(f"Net PnL:  ${pnl:.2f}   Return: {ret:.1f}%   Win Rate: {wr:.1f}%")
print(f"MaxDD:    {mdd:.2f}%   ProfitFactor: {pf:.2f}   Payoff: {po:.2f}   Expectancy: ${exp:.2f}")
print('='*90)
