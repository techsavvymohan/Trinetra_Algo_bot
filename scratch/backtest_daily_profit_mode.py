import sys
import os
import json

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, '.')

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

print('Loading authentic 2026 tick datasets...', flush=True)
with open('data/genuine_jan_aug_2026_xauusd.json') as f:
    xau_data = json.load(f)

xau_bars = len(xau_data['M1']['close'])
print(f'  XAUUSD bars loaded: {xau_bars}', flush=True)

BAL = 10000.0

scenarios = [
    {
        "name": "M1: BASELINE (2.0R, No Partial, Strict Killzones)",
        "ov": {
            "xau_partial_close_enabled": False,
            "xau_target_r": 2.0,
            "xau_breakeven_trigger_r": 1.50,
            "xau_strict_killzones": True,
            "max_daily_trades": 4,
            "xau_max_trades_per_session": 2,
            "xau_risk_per_trade": 0.01,
            "xau_h4_bias_guard": False,
        }
    },
    {
        "name": "M2: DAILY PROFIT (Partial TP +1.0R, Target 1.5R, BE 1.0R)",
        "ov": {
            "xau_partial_close_enabled": True,
            "partial_take_profit_r": 1.0,
            "partial_close_pct": 50.0,
            "xau_target_r": 1.5,
            "xau_breakeven_trigger_r": 1.0,
            "xau_breakeven_buffer_r": 0.05,
            "xau_strict_killzones": True,
            "max_daily_trades": 6,
            "xau_max_trades_per_session": 3,
            "xau_risk_per_trade": 0.01,
            "xau_h4_bias_guard": False,
        }
    },
    {
        "name": "M3: DAILY PROFIT + WIDER HOURS (Partial TP +1.0R, Target 1.8R, Wider Windows)",
        "ov": {
            "xau_partial_close_enabled": True,
            "partial_take_profit_r": 1.0,
            "partial_close_pct": 50.0,
            "xau_target_r": 1.8,
            "xau_breakeven_trigger_r": 1.0,
            "xau_breakeven_buffer_r": 0.05,
            "xau_strict_killzones": False,
            "max_daily_trades": 8,
            "xau_max_trades_per_session": 4,
            "xau_risk_per_trade": 0.01,
            "xau_h4_bias_guard": False,
        }
    },
    {
        "name": "M4: HIGH-VELOCITY SCALPER (Target 1.5R, BE 1.0R, 8 Trades/Day, 1% Risk)",
        "ov": {
            "xau_partial_close_enabled": False,
            "xau_target_r": 1.5,
            "xau_breakeven_trigger_r": 1.0,
            "xau_breakeven_buffer_r": 0.05,
            "xau_strict_killzones": False,
            "max_daily_trades": 8,
            "xau_max_trades_per_session": 4,
            "xau_risk_per_trade": 0.01,
            "xau_h4_bias_guard": False,
        }
    },
]

results = []
for sc in scenarios:
    label = sc["name"]
    ov = sc["ov"]
    print(f"\n==================================================", flush=True)
    print(f"Testing: {label}", flush=True)
    cfg = Config.load()
    for k, v in ov.items():
        if hasattr(cfg.trading, k):
            setattr(cfg.trading, k, v)
    eng = BacktestEngine(cfg, initial_balance=BAL, symbol="XAUUSD")
    res = eng.run(xau_data)
    pnl = res.get("total_pnl", 0.0)
    trades = res.get("total_trades", 0)
    wr = res.get("win_rate", 0.0)
    pf = res.get("profit_factor", 0.0)
    dd = res.get("max_drawdown_pct", 0.0)
    ret = res.get("return_pct", 0.0)
    results.append({
        "name": label,
        "pnl": pnl,
        "trades": trades,
        "wr": wr,
        "pf": pf,
        "dd": dd,
        "ret": ret,
    })
    print(f"  Result: PnL=${pnl:.2f} | Return={ret:+.2f}% | Trades={trades} | WR={wr:.1f}% | PF={pf:.2f} | MaxDD={dd:.2f}%", flush=True)

print("\n" + "=" * 95, flush=True)
print("  DAILY PROFIT MODE COMPARISON SUMMARY (Jan-Aug 2026, $10,000 Starting Balance)", flush=True)
print("=" * 95, flush=True)
print(f"{'Scenario':<45} | {'Net PnL':>10} | {'Return':>8} | {'Trades':>6} | {'WR%':>6} | {'PF':>5} | {'MaxDD':>7}")
print("-" * 95, flush=True)
for r in results:
    print(f"{r['name']:<45} | {r['pnl']:>9.2f}$ | {r['ret']:>7.1f}% | {r['trades']:>6} | {r['wr']:>5.1f}% | {r['pf']:>5.2f} | {r['dd']:>6.2f}%")
print("=" * 95, flush=True)
