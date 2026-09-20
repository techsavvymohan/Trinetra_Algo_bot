"""
Analyze Grade A trades in XAUUSD backtest data (Jan-Aug 2026).
Break down by:
1. H1 Bias alignment (Trend vs Counter-trend vs Neutral)
2. H4 Bias alignment
3. Session (NY vs London)
4. Displacement strength
Measure: Win Rate, Net Profit ($), Profit Factor, Max Drawdown for each segment.
"""
import os
import sys
import pandas as pd
import numpy as np

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, Bias

def main():
    import json
    json_path = "data/genuine_jan_aug_2026_xauusd.json"
    if not os.path.exists(json_path):
        print(f"File {json_path} not found!")
        return

    print("Loading data...")
    with open(json_path) as f:
        data_xau = json.load(f)
    print(f"Loaded {len(data_xau.get('M1', [])):,} M1 bars.")

    # Configure engine with Option C baseline settings
    cfg = Config()
    cfg.trading.symbol = "XAUUSD"
    cfg.trading.use_dual_window = True
    cfg.trading.xau_session_cutoff_hour = 16
    cfg.trading.xau_london_require_h1_trend = True
    cfg.trading.xau_enable_london_asian_sweep = True
    cfg.trading.enable_conviction_sizing = False  # Run baseline 1.0x first to see raw trade quality

    engine = BacktestEngine(config=cfg, symbol="XAUUSD", initial_balance=100000.0)
    print("Running baseline backtest...")
    results = engine.run(data_xau)
    
    trades = results.get("closed_trades", [])
    print(f"\nTotal closed trades: {len(trades)}")

    # Analyze trades
    rows = []
    for t in trades:
        # Check alignment
        sig_dir = t.direction
        h1_b = getattr(t, "h1_bias", None) or "neutral"
        h4_b = getattr(t, "h4_bias", None) or "neutral"
        if isinstance(h1_b, Bias):
            h1_b = h1_b.value
        if isinstance(h4_b, Bias):
            h4_b = h4_b.value

        h1_aligned = (sig_dir == TradeDirection.BUY and h1_b == "bullish") or (sig_dir == TradeDirection.SELL and h1_b == "bearish")
        h1_counter = (sig_dir == TradeDirection.BUY and h1_b == "bearish") or (sig_dir == TradeDirection.SELL and h1_b == "bullish")
        h1_neutral = h1_b == "neutral"

        h4_aligned = (sig_dir == TradeDirection.BUY and h4_b == "bullish") or (sig_dir == TradeDirection.SELL and h4_b == "bearish")

        pnl = t.pnl_dollars
        win = 1 if pnl > 0 else 0

        rows.append({
            "trade_id": t.cluster_id,
            "direction": sig_dir.value,
            "h1_bias": h1_b,
            "h4_bias": h4_b,
            "h1_aligned": h1_aligned,
            "h1_counter": h1_counter,
            "h1_neutral": h1_neutral,
            "h4_aligned": h4_aligned,
            "pnl": pnl,
            "win": win,
            "exit_reason": t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason),
            "pnl_r": getattr(t, "pnl_r", 0.0),
        })

    tdf = pd.DataFrame(rows)
    print("\n--- PERFORMANCE BREAKDOWN BY H1 ALIGNMENT ---")
    for group_name, mask in [
        ("H1 Aligned (Trend Following)", tdf["h1_aligned"]),
        ("H1 Neutral", tdf["h1_neutral"]),
        ("H1 Counter-Trend", tdf["h1_counter"]),
        ("H1 Aligned OR (H1 Neutral & H4 Aligned)", tdf["h1_aligned"] | (tdf["h1_neutral"] & tdf["h4_aligned"])),
    ]:
        sub = tdf[mask]
        n = len(sub)
        if n == 0:
            print(f"{group_name}: 0 trades")
            continue
        wins = sub["win"].sum()
        wr = (wins / n) * 100
        net_pnl = sub["pnl"].sum()
        gross_win = sub[sub["pnl"] > 0]["pnl"].sum()
        gross_loss = abs(sub[sub["pnl"] < 0]["pnl"].sum())
        pf = gross_win / gross_loss if gross_loss > 0 else 999.0
        avg_trade = sub["pnl"].mean()
        print(f"{group_name}:")
        print(f"  Trades: {n} ({n/len(tdf)*100:.1f}%) | Wins: {wins} | Win Rate: {wr:.1f}%")
        print(f"  Net PnL: ${net_pnl:,.2f} | PF: {pf:.2f} | Avg Trade: ${avg_trade:,.2f}")

if __name__ == "__main__":
    main()
