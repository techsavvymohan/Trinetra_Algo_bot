import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

def run_portfolio():
    print("=" * 80)
    print("  TESTING GOLD + NASDAQ 100 WITH HOUSE MONEY COMPOUNDING")
    print("  Period: July 14 - September 18, 2026 (100% Genuine MT5 Real Data)")
    print("=" * 80)

    with open("data/genuine_recent_xauusd.json") as f:
        xau_d = json.load(f)
    with open("data/genuine_recent_nas100.json") as f:
        nas_d = json.load(f)

    # 1. Nasdaq 100
    cfg_nas = Config()
    cfg_nas.trading.symbol = "USTECH100M"
    cfg_nas.trading.symbols = ["USTECH100M"]
    cfg_nas.trading.enable_profit_compounding = True
    cfg_nas.trading.backtest_apply_friction = True

    engine_nas = BacktestEngine(cfg_nas, initial_balance=10000.0, symbol="USTECH100M")
    res_nas = engine_nas.run(nas_d)

    # 2. XAUUSD
    cfg_xau = Config()
    cfg_xau.trading.symbol = "XAUUSD"
    cfg_xau.trading.symbols = ["XAUUSD"]
    cfg_xau.trading.enable_profit_compounding = True
    cfg_xau.trading.backtest_apply_friction = True

    engine_xau = BacktestEngine(cfg_xau, initial_balance=10000.0, symbol="XAUUSD")
    res_xau = engine_xau.run(xau_d)

    print(f"\n[USTECH100M] PnL: ${res_nas['total_pnl']:>8.2f} | Trades: {res_nas['total_trades']:>3} | WR: {res_nas['win_rate']:>5.1f}% | PF: {res_nas['profit_factor']:>4.2f} | MaxDD: {res_nas['max_drawdown_pct']:>4.2f}%")
    print(f"[XAUUSD]     PnL: ${res_xau['total_pnl']:>8.2f} | Trades: {res_xau['total_trades']:>3} | WR: {res_xau['win_rate']:>5.1f}% | PF: {res_xau['profit_factor']:>4.2f} | MaxDD: {res_xau['max_drawdown_pct']:>4.2f}%")

    comb_pnl = res_nas['total_pnl'] + res_xau['total_pnl']
    comb_trades = res_nas['total_trades'] + res_xau['total_trades']
    comb_wins = res_nas['wins'] + res_xau['wins']
    comb_wr = (comb_wins / comb_trades * 100.0) if comb_trades > 0 else 0.0
    print("-" * 80)
    print(f"COMBINED GOLD + NASDAQ: Net PnL = ${comb_pnl:.2f} | Win Rate = {comb_wr:.1f}% ({comb_trades} trades)")

if __name__ == "__main__":
    run_portfolio()
