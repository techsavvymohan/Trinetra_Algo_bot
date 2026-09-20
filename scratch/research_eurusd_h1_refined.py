import json
import math
from datetime import datetime
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
h1_highs = h1["high"]
h1_lows = h1["low"]

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

h1_idx = 0
m15_to_h1 = []
for t in m15_times:
    while h1_idx + 1 < len(h1_times) and h1_times[h1_idx + 1] <= t:
        h1_idx += 1
    m15_to_h1.append(h1_idx)

# Test Refined Strategy:
# 1. H1 Trend: EMA 21 > EMA 50 > EMA 200 (Strong Bullish) or EMA 21 < EMA 50 < EMA 200 (Strong Bearish)
# 2. M15 Pullback & Reversal (M15 close reclaims above EMA 21 of M15)
# 3. Breakeven at 1.0R
# 4. Target 2.0R to 2.5R

m15_ema21 = calc_ema(m15_closes, 21)

def run_refined_h1_m15(target_r=2.0, be_r=1.0, risk_pct=0.015, initial_balance=10000.0):
    balance = initial_balance
    trades = []
    last_trade_day = None
    
    for i in range(50, len(m15_times) - 30):
        t_now = m15_times[i]
        h_utc = t_now.hour
        
        # Trade London Open (07:00 - 11:00 UTC) or NY Core (12:30 - 15:30 UTC)
        if not ((7 <= h_utc < 11) or (12 <= h_utc < 16)):
            continue
            
        cur_day = t_now.date()
        if cur_day == last_trade_day:
            continue
            
        h1_i = m15_to_h1[i]
        if h1_i < 200:
            continue
            
        e21_h1 = h1_ema21[h1_i]
        e50_h1 = h1_ema50[h1_i]
        e200_h1 = h1_ema200[h1_i]
        h1_c = h1_closes[h1_i]
        
        bullish = (e21_h1 > e50_h1) and (h1_c > e200_h1)
        bearish = (e21_h1 < e50_h1) and (h1_c < e200_h1)
        
        c = m15_closes[i]
        o = m15_opens[i]
        h = m15_highs[i]
        l = m15_lows[i]
        e21_m15 = m15_ema21[i]
        
        # Bullish: M15 crosses above M15 EMA 21 with bullish body
        if bullish and m15_closes[i-1] <= m15_ema21[i-1] and c > e21_m15 and c > o:
            # Swing low in last 5 bars
            recent_low = min(m15_lows[i-5:i+1])
            sl = recent_low - 0.00030
            sl_dist = c - sl
            sl_pips = sl_dist * 10000
            
            if 8 <= sl_pips <= 25:
                entry = c
                tp = entry + (sl_dist * target_r)
                be_trigger = entry + (sl_dist * be_r)
                
                outcome = None
                exit_price = None
                be_active = False
                
                for f_idx in range(i + 1, min(i + 48, len(m15_times))):
                    f_h = m15_highs[f_idx]
                    f_l = m15_lows[f_idx]
                    
                    if not be_active and f_h >= be_trigger:
                        be_active = True
                        sl = entry + 0.00010  # BE + 1 pip
                        
                    if f_l <= sl:
                        outcome = "BE" if be_active else "LOSS"
                        exit_price = sl
                        break
                    elif f_h >= tp:
                        outcome = "WIN"
                        exit_price = tp
                        break
                        
                if outcome is None:
                    exit_price = m15_closes[min(i + 47, len(m15_times) - 1)]
                    outcome = "WIN" if exit_price > entry else ("BE" if be_active else "LOSS")
                    
                risk_usd = balance * risk_pct
                lot = round(risk_usd / (sl_pips * 10.0), 2)
                lot = max(0.01, min(lot, 50.0))
                pnl_pips = (exit_price - entry) * 10000
                pnl_usd = (pnl_pips * 10.0 * lot) - (lot * 6.0)
                balance += pnl_usd
                trades.append({"date": t_now, "dir": "BUY", "pnl": pnl_usd, "outcome": outcome})
                last_trade_day = cur_day
                
        # Bearish: M15 crosses below M15 EMA 21 with bearish body
        elif bearish and m15_closes[i-1] >= m15_ema21[i-1] and c < e21_m15 and c < o:
            recent_high = max(m15_highs[i-5:i+1])
            sl = recent_high + 0.00030
            sl_dist = sl - c
            sl_pips = sl_dist * 10000
            
            if 8 <= sl_pips <= 25:
                entry = c
                tp = entry - (sl_dist * target_r)
                be_trigger = entry - (sl_dist * be_r)
                
                outcome = None
                exit_price = None
                be_active = False
                
                for f_idx in range(i + 1, min(i + 48, len(m15_times))):
                    f_h = m15_highs[f_idx]
                    f_l = m15_lows[f_idx]
                    
                    if not be_active and f_l <= be_trigger:
                        be_active = True
                        sl = entry - 0.00010  # BE + 1 pip
                        
                    if f_h >= sl:
                        outcome = "BE" if be_active else "LOSS"
                        exit_price = sl
                        break
                    elif f_l <= tp:
                        outcome = "WIN"
                        exit_price = tp
                        break
                        
                if outcome is None:
                    exit_price = m15_closes[min(i + 47, len(m15_times) - 1)]
                    outcome = "WIN" if exit_price < entry else ("BE" if be_active else "LOSS")
                    
                risk_usd = balance * risk_pct
                lot = round(risk_usd / (sl_pips * 10.0), 2)
                lot = max(0.01, min(lot, 50.0))
                pnl_pips = (entry - exit_price) * 10000
                pnl_usd = (pnl_pips * 10.0 * lot) - (lot * 6.0)
                balance += pnl_usd
                trades.append({"date": t_now, "dir": "SELL", "pnl": pnl_usd, "outcome": outcome})
                last_trade_day = cur_day
                
    return trades, balance

print("\n--- Testing Refined H1 Trend + M15 Momentum with BE ---")
for r in [1.5, 2.0, 2.5]:
    for be in [0.8, 1.0, 1.2]:
        tr, bal = run_refined_h1_m15(target_r=r, be_r=be)
        wins = len([t for t in tr if t["pnl"] > 0])
        wr = wins / len(tr) * 100 if tr else 0.0
        pnl = bal - 10000.0
        print(f"Target R={r:.1f}, BE={be:.1f}R: Trades={len(tr)}, Wins={wins}, WR={wr:.1f}%, Net PnL=+${pnl:.2f}")

# Best performer breakdown
tr, bal = run_refined_h1_m15(target_r=2.5, be_r=1.0)
by_m = defaultdict(list)
for t in tr:
    by_m[t["date"].strftime("%Y-%m")].append(t)
print("\nMonthly Breakdown for Target R=2.5, BE=1.0R:")
for m in sorted(by_m.keys()):
    m_tr = by_m[m]
    m_pnl = sum(x["pnl"] for x in m_tr)
    m_wins = len([x for x in m_tr if x["pnl"] > 0])
    m_wr = m_wins / len(m_tr) * 100 if m_tr else 0.0
    status = "[GREEN]" if m_pnl > 0 else "[RED]"
    print(f"  {m}: {len(m_tr):>2} trades, WR={m_wr:>5.1f}%, PnL=+${m_pnl:>7.2f} {status}")
