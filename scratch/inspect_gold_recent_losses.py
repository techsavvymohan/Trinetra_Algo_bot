import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeDirection, TradeStatus


def inspect_gold_losses():
    with open("data/genuine_recent_xauusd.json") as f:
        data = json.load(f)

    cfg = Config()
    cfg.trading.symbol = "XAUUSD"
    cfg.trading.symbols = ["XAUUSD"]
    # Disable kill switch temporarily to see ALL trades through Aug & Sep
    cfg.trading.daily_loss_limit_pct = 50.0
    cfg.trading.max_dd_limit_pct = 50.0
    cfg.trading.enable_profit_compounding = False
    cfg.trading.backtest_apply_friction = True

    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
    res = engine.run(data)

    print("=" * 110)
    print(f"  ALL GOLD TRADES INSPECTION (July 8 - September 18, 2026)")
    print(f"  Total Trades: {res.get('total_trades')} | Wins: {res.get('wins')} | Losses: {res.get('losses')} | Net PnL: ${res.get('total_pnl'):.2f} | WR: {res.get('win_rate'):.1f}%")
    print("=" * 110)
    print(f"{'Open Time (UTC)':<20} | {'Day':<3} | {'Dir':<4} | {'Entry':>8} | {'SL':>8} | {'Exit':>8} | {'PnL ($)':>8} | {'Exit Reason':<15} | {'Cluster ID':<10}")
    print("-" * 110)

    loss_trades = []
    win_trades = []

    for c in engine._clusters:
        for leg in c.legs:
            ot = str(leg.open_time)[:19] if leg.open_time else "N/A"
            ct = str(leg.close_time)[:19] if leg.close_time else "N/A"
            pnl = getattr(leg, "pnl", 0.0)
            sl = getattr(leg, "sl_price", 0.0)
            ep = getattr(leg, "entry_price", 0.0)
            xp = getattr(leg, "exit_price", 0.0)
            d = leg.direction.value
            reas = getattr(c, "exit_reason", "UNKNOWN")
            if hasattr(reas, "value"):
                reas = reas.value
            
            # day of week
            dow = ""
            if leg.open_time and hasattr(leg.open_time, "strftime"):
                dow = leg.open_time.strftime("%a")
            elif isinstance(leg.open_time, str):
                try:
                    from datetime import datetime
                    dow = datetime.fromisoformat(leg.open_time).strftime("%a")
                except Exception:
                    pass

            item = {
                "open_time": ot,
                "day": dow,
                "dir": d,
                "entry": ep,
                "sl": sl,
                "exit": xp,
                "pnl": pnl,
                "reason": reas,
                "cluster": c.cluster_id[:8],
            }
            if pnl < 0:
                loss_trades.append(item)
            else:
                win_trades.append(item)

            print(f"{ot:<20} | {dow:<3} | {d:<4} | {ep:>8.2f} | {sl:>8.2f} | {xp:>8.2f} | {pnl:>8.2f} | {str(reas):<15} | {c.cluster_id[:8]:<10}")

    print("=" * 110)
    print(f"Total Wins: {len(win_trades)} | Total Losses: {len(loss_trades)}")
    
    # Analyze losses by Day of Week
    from collections import Counter
    dow_losses = Counter(t["day"] for t in loss_trades)
    dow_wins = Counter(t["day"] for t in win_trades)
    print("\nPerformance by Day of Week:")
    for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        w = dow_wins.get(d, 0)
        l = dow_losses.get(d, 0)
        tot = w + l
        wr = (w / tot * 100) if tot > 0 else 0
        print(f"  {d}: {w} Wins, {l} Losses ({wr:.1f}% WR)")

    # Analyze losses by Hour of Day
    hour_losses = Counter(int(t["open_time"][11:13]) for t in loss_trades if len(t["open_time"]) >= 13 and t["open_time"][11:13].isdigit())
    hour_wins = Counter(int(t["open_time"][11:13]) for t in win_trades if len(t["open_time"]) >= 13 and t["open_time"][11:13].isdigit())
    print("\nPerformance by UTC Hour:")
    for h in sorted(set(list(hour_losses.keys()) + list(hour_wins.keys()))):
        w = hour_wins.get(h, 0)
        l = hour_losses.get(h, 0)
        tot = w + l
        wr = (w / tot * 100) if tot > 0 else 0
        print(f"  {h:02d}:00 UTC: {w} Wins, {l} Losses ({wr:.1f}% WR)")


if __name__ == "__main__":
    inspect_gold_losses()
