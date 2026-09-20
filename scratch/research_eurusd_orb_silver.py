import json
from datetime import datetime
from collections import defaultdict

with open("data/genuine_jan_aug_2026_eurusd.json") as f:
    data = json.load(f)

m15 = data["M15"]
m15_times = [datetime.fromisoformat(str(t).replace("Z", "+00:00")).replace(tzinfo=None) for t in m15["time"]]
m15_opens = m15["open"]
m15_highs = m15["high"]
m15_lows = m15["low"]
m15_closes = m15["close"]

# Group by date
bars_by_date = defaultdict(list)
for i, t in enumerate(m15_times):
    bars_by_date[t.date()].append(i)

# Strategy A: London Open Range Breakout (ORB)
# Range defined by Frankfurt / Pre-London 06:00 - 07:00 UTC
# Breakout between 07:00 and 10:00 UTC
# SL at opposite side of 06:00-07:00 range, or range midpoint
def test_london_orb(target_r=1.5, risk_pct=0.015, initial_balance=10000.0):
    balance = initial_balance
    trades = []
    
    for d, indices in sorted(bars_by_date.items()):
        # Pre-London bars: 06:00 to 07:00 UTC (4 bars of M15)
        pre_bars = [i for i in indices if 6 <= m15_times[i].hour < 7]
        if len(pre_bars) < 3:
            continue
            
        r_high = max(m15_highs[i] for i in pre_bars)
        r_low = min(m15_lows[i] for i in pre_bars)
        r_size_pips = (r_high - r_low) * 10000
        
        # We want reasonable range (8 to 25 pips)
        if not (8 <= r_size_pips <= 30):
            continue
            
        mid = (r_high + r_low) / 2.0
        
        # Trade between 07:00 and 10:00 UTC
        trade_taken = False
        for i in indices:
            if trade_taken:
                break
            t = m15_times[i]
            if not (7 <= t.hour < 10):
                continue
                
            c = m15_closes[i]
            h = m15_highs[i]
            l = m15_lows[i]
            
            # Long breakout: close above r_high
            if c > r_high and m15_closes[i-1] <= r_high:
                sl = mid # SL at range midpoint
                sl_dist = c - sl
                sl_pips = sl_dist * 10000
                if 5 <= sl_pips <= 20:
                    entry = c
                    tp = entry + (sl_dist * target_r)
                    
                    exit_price = None
                    outcome = None
                    for f_idx in range(i + 1, min(i + 32, len(m15_times))):
                        if m15_lows[f_idx] <= sl:
                            outcome = "LOSS"
                            exit_price = sl
                            break
                        elif m15_highs[f_idx] >= tp:
                            outcome = "WIN"
                            exit_price = tp
                            break
                    if outcome is None:
                        exit_price = m15_closes[min(i + 31, len(m15_times) - 1)]
                        outcome = "WIN" if exit_price > entry else "LOSS"
                        
                    lot = round((balance * risk_pct) / (sl_pips * 10.0), 2)
                    lot = max(0.01, min(lot, 50.0))
                    pnl_pips = (exit_price - entry) * 10000
                    pnl = (pnl_pips * 10.0 * lot) - (lot * 6.0)
                    balance += pnl
                    trades.append({"date": t, "dir": "BUY", "pnl": pnl, "outcome": outcome})
                    trade_taken = True
                    break
                    
            # Short breakout: close below r_low
            elif c < r_low and m15_closes[i-1] >= r_low:
                sl = mid
                sl_dist = sl - c
                sl_pips = sl_dist * 10000
                if 5 <= sl_pips <= 20:
                    entry = c
                    tp = entry - (sl_dist * target_r)
                    
                    exit_price = None
                    outcome = None
                    for f_idx in range(i + 1, min(i + 32, len(m15_times))):
                        if m15_highs[f_idx] >= sl:
                            outcome = "LOSS"
                            exit_price = sl
                            break
                        elif m15_lows[f_idx] <= tp:
                            outcome = "WIN"
                            exit_price = tp
                            break
                    if outcome is None:
                        exit_price = m15_closes[min(i + 31, len(m15_times) - 1)]
                        outcome = "WIN" if exit_price < entry else "LOSS"
                        
                    lot = round((balance * risk_pct) / (sl_pips * 10.0), 2)
                    lot = max(0.01, min(lot, 50.0))
                    pnl_pips = (entry - exit_price) * 10000
                    pnl = (pnl_pips * 10.0 * lot) - (lot * 6.0)
                    balance += pnl
                    trades.append({"date": t, "dir": "SELL", "pnl": pnl, "outcome": outcome})
                    trade_taken = True
                    break
                    
    return trades, balance

print("\n--- Testing London Open Range Breakout (ORB) on EURUSD ---")
for r in [1.0, 1.2, 1.5, 2.0]:
    tr, bal = test_london_orb(target_r=r)
    wins = len([t for t in tr if t["pnl"] > 0])
    wr = wins / len(tr) * 100 if tr else 0.0
    pnl = bal - 10000.0
    print(f"Target R={r:.1f}: Trades={len(tr)}, Wins={wins}, WR={wr:.1f}%, Net PnL=+${pnl:.2f}")

