import json
import math
from datetime import datetime, timezone
from collections import defaultdict

with open("data/genuine_jan_aug_2026_eurusd.json") as f:
    data = json.load(f)

m15 = data["M15"]
h1 = data["H1"]

m15_times = [datetime.fromisoformat(str(t).replace("Z", "+00:00")).replace(tzinfo=None) for t in m15["time"]]
m15_opens = m15["open"]
m15_highs = m15["high"]
m15_lows = m15["low"]
m15_closes = m15["close"]

h1_times = [datetime.fromisoformat(str(t).replace("Z", "+00:00")).replace(tzinfo=None) for t in h1["time"]]
h1_closes = h1["close"]

# Calculate H1 EMA 21 and EMA 50
def calc_ema(prices, period):
    res = []
    k = 2.0 / (period + 1)
    cur = prices[0]
    res.append(cur)
    for p in prices[1:]:
        cur = p * k + cur * (1 - k)
        res.append(cur)
    return res

h1_ema21 = calc_ema(h1_closes, 21)
h1_ema50 = calc_ema(h1_closes, 50)
h1_ema200 = calc_ema(h1_closes, 200)

# Map each M15 bar to latest completed H1 bar
h1_idx = 0
m15_to_h1 = []
for t in m15_times:
    while h1_idx + 1 < len(h1_times) and h1_times[h1_idx + 1] <= t:
        h1_idx += 1
    m15_to_h1.append(h1_idx)

# Test Strategy 2: H1 Trend Following + M15 Pullback & Breakout
# - H1 Trend: EMA 21 > EMA 50 (Bullish) or EMA 21 < EMA 50 (Bearish)
# - Price pulls back on M15, then creates an M15 FVG or structure break in direction of trend
# - Trading only in London (07:00 - 11:30 UTC) and NY (13:00 - 16:30 UTC)

def run_trend_following_strategy(target_r=1.5, risk_pct=0.015, initial_balance=10000.0, use_200=True):
    balance = initial_balance
    trades = []
    last_trade_day = None
    
    for i in range(50, len(m15_times) - 30):
        t_now = m15_times[i]
        h_utc = t_now.hour
        m_utc = t_now.minute
        
        # Session Filter: London (07:00 - 11:00 UTC) or NY (13:00 - 16:00 UTC)
        in_sess = (7 <= h_utc < 11) or (13 <= h_utc < 16)
        if not in_sess:
            continue
            
        h1_i = m15_to_h1[i]
        if h1_i < 200:
            continue
            
        e21 = h1_ema21[h1_i]
        e50 = h1_ema50[h1_i]
        e200 = h1_ema200[h1_i]
        h1_c = h1_closes[h1_i]
        
        bullish = (e21 > e50) and (h1_c > e200 if use_200 else True)
        bearish = (e21 < e50) and (h1_c < e200 if use_200 else True)
        
        c = m15_closes[i]
        o = m15_opens[i]
        h = m15_highs[i]
        l = m15_lows[i]
        
        # Check M15 FVG in trend direction
        # Bullish FVG: candle[i-2].high < candle[i].low
        c_prev2_h = m15_highs[i - 2]
        c_prev2_l = m15_lows[i - 2]
        
        c_prev1_c = m15_closes[i - 1]
        c_prev1_o = m15_opens[i - 1]
        
        # Day limit: max 1 trade per day
        cur_day = t_now.date()
        if cur_day == last_trade_day:
            continue
            
        if bullish and c_prev2_h < l and (c_prev1_c > c_prev1_o): # Bullish FVG
            entry = c
            sl = c_prev2_l - 0.00030
            sl_dist = entry - sl
            sl_pips = sl_dist * 10000
            
            if 8 <= sl_pips <= 25:
                tp = entry + (sl_dist * target_r)
                
                # Check forward outcome
                exit_price = None
                outcome = None
                for f_idx in range(i + 1, min(i + 40, len(m15_times))):
                    if m15_lows[f_idx] <= sl:
                        outcome = "LOSS"
                        exit_price = sl
                        break
                    elif m15_highs[f_idx] >= tp:
                        outcome = "WIN"
                        exit_price = tp
                        break
                if outcome is None:
                    exit_price = m15_closes[min(i + 39, len(m15_times) - 1)]
                    outcome = "WIN" if exit_price > entry else "LOSS"
                    
                risk_usd = balance * risk_pct
                pip_value_per_lot = 10.0
                lot_size = round(risk_usd / (sl_pips * pip_value_per_lot), 2)
                lot_size = max(0.01, min(lot_size, 50.0))
                
                pnl_pips = (exit_price - entry) * 10000
                pnl_usd = (pnl_pips * pip_value_per_lot * lot_size) - (lot_size * 6.0)
                balance += pnl_usd
                trades.append({"date": t_now, "dir": "BUY", "pnl": pnl_usd, "outcome": outcome, "sl_pips": sl_pips})
                last_trade_day = cur_day
                
        elif bearish and c_prev2_l > h and (c_prev1_c < c_prev1_o): # Bearish FVG
            entry = c
            sl = c_prev2_h + 0.00030
            sl_dist = sl - entry
            sl_pips = sl_dist * 10000
            
            if 8 <= sl_pips <= 25:
                tp = entry - (sl_dist * target_r)
                
                exit_price = None
                outcome = None
                for f_idx in range(i + 1, min(i + 40, len(m15_times))):
                    if m15_highs[f_idx] >= sl:
                        outcome = "LOSS"
                        exit_price = sl
                        break
                    elif m15_lows[f_idx] <= tp:
                        outcome = "WIN"
                        exit_price = tp
                        break
                if outcome is None:
                    exit_price = m15_closes[min(i + 39, len(m15_times) - 1)]
                    outcome = "WIN" if exit_price < entry else "LOSS"
                    
                risk_usd = balance * risk_pct
                pip_value_per_lot = 10.0
                lot_size = round(risk_usd / (sl_pips * pip_value_per_lot), 2)
                lot_size = max(0.01, min(lot_size, 50.0))
                
                pnl_pips = (entry - exit_price) * 10000
                pnl_usd = (pnl_pips * pip_value_per_lot * lot_size) - (lot_size * 6.0)
                balance += pnl_usd
                trades.append({"date": t_now, "dir": "SELL", "pnl": pnl_usd, "outcome": outcome, "sl_pips": sl_pips})
                last_trade_day = cur_day
                
    return trades, balance

print("\n--- Testing H1 Trend Following + M15 FVG Strategy ---")
for r in [1.5, 2.0, 2.5]:
    for use_200 in [True, False]:
        tr, bal = run_trend_following_strategy(target_r=r, use_200=use_200)
        wins = len([t for t in tr if t["pnl"] > 0])
        wr = wins / len(tr) * 100 if tr else 0.0
        pnl = bal - 10000.0
        print(f"Target R={r:.1f} (use_200={use_200}): Trades={len(tr)}, Wins={wins}, WR={wr:.1f}%, Net PnL=+${pnl:.2f}")

