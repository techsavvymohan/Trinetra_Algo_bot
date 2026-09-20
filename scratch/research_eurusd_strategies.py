import json
import math
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

# Load EURUSD dataset
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

print(f"Loaded EURUSD: M15 bars = {len(m15_times)}, H1 bars = {len(h1_times)}")

# Let's test Candidate Strategy 1:
# Asian Range (00:00 - 06:45 UTC) Liquidity Sweep on M15 during London Open (07:00 - 11:00 UTC)
# Entry on M15 FVG, SL at sweep extreme, TP at 2.0R or opposite Asian level.

def run_asian_sweep_strategy(target_r=2.0, max_sl_pips=25.0, min_sl_pips=8.0, risk_pct=0.015, initial_balance=10000.0):
    balance = initial_balance
    trades = []
    
    # Group M15 bars by date
    bars_by_date = defaultdict(list)
    for i, t in enumerate(m15_times):
        d = t.date()
        bars_by_date[d].append(i)
        
    for d, indices in sorted(bars_by_date.items()):
        # 1. Calculate Asian Range (00:00 - 06:45 UTC)
        asian_bars = [i for i in indices if 0 <= m15_times[i].hour < 7]
        if len(asian_bars) < 10:
            continue
            
        asian_high = max(m15_highs[i] for i in asian_bars)
        asian_low = min(m15_lows[i] for i in asian_bars)
        asian_range_pips = (asian_high - asian_low) * 10000
        
        # If Asian range is too wide (> 50 pips) or too tiny (< 10 pips), skip
        if asian_range_pips > 50 or asian_range_pips < 10:
            continue
            
        # 2. Check London Session (07:00 - 11:30 UTC) for sweep & M15 FVG
        london_bars = [i for i in indices if 7 <= m15_times[i].hour < 12]
        
        trade_taken_today = False
        
        for idx in london_bars:
            if trade_taken_today:
                break
                
            curr_h = m15_highs[idx]
            curr_l = m15_lows[idx]
            curr_c = m15_closes[idx]
            curr_o = m15_opens[idx]
            t_now = m15_times[idx]
            
            # Check Bearish Setup: Sweep of Asian High + M15 Bearish Reclaim/FVG
            if curr_h > asian_high and curr_c < asian_high:
                # Check for M15 bearish candle / displacement
                if curr_c < curr_o:
                    sl_price = curr_h + 0.00030  # 3 pips buffer
                    entry_price = curr_c
                    sl_dist = sl_price - entry_price
                    sl_pips = sl_dist * 10000
                    
                    if min_sl_pips <= sl_pips <= max_sl_pips:
                        tp_price = entry_price - (sl_dist * target_r)
                        
                        # Simulate trade outcome over subsequent bars
                        outcome = None
                        exit_price = None
                        exit_time = None
                        
                        for f_idx in range(idx + 1, min(idx + 30, len(m15_times))):
                            bar_h = m15_highs[f_idx]
                            bar_l = m15_lows[f_idx]
                            
                            # Check SL first
                            if bar_h >= sl_price:
                                outcome = "LOSS"
                                exit_price = sl_price
                                exit_time = m15_times[f_idx]
                                break
                            elif bar_l <= tp_price:
                                outcome = "WIN"
                                exit_price = tp_price
                                exit_time = m15_times[f_idx]
                                break
                                
                        if outcome is None:
                            # Time exit at end of day
                            exit_price = m15_closes[min(idx + 29, len(m15_times) - 1)]
                            exit_time = m15_times[min(idx + 29, len(m15_times) - 1)]
                            outcome = "WIN" if exit_price < entry_price else "LOSS"
                            
                        # Calculate PnL
                        risk_usd = balance * risk_pct
                        pip_value_per_lot = 10.0  # $10 per pip on 1.0 lot EURUSD
                        lot_size = round(risk_usd / (sl_pips * pip_value_per_lot), 2)
                        lot_size = max(0.01, min(lot_size, 50.0))
                        
                        pnl_pips = (entry_price - exit_price) * 10000
                        pnl_usd = (pnl_pips * pip_value_per_lot * lot_size) - (lot_size * 6.0) # $6 commission
                        
                        balance += pnl_usd
                        trades.append({
                            "date": t_now,
                            "direction": "SELL",
                            "entry": entry_price,
                            "sl": sl_price,
                            "tp": tp_price,
                            "sl_pips": sl_pips,
                            "outcome": outcome,
                            "pnl": pnl_usd,
                            "balance": balance
                        })
                        trade_taken_today = True
                        break
                        
            # Check Bullish Setup: Sweep of Asian Low + M15 Bullish Reclaim/FVG
            elif curr_l < asian_low and curr_c > asian_low:
                if curr_c > curr_o:
                    sl_price = curr_l - 0.00030  # 3 pips buffer
                    entry_price = curr_c
                    sl_dist = entry_price - sl_price
                    sl_pips = sl_dist * 10000
                    
                    if min_sl_pips <= sl_pips <= max_sl_pips:
                        tp_price = entry_price + (sl_dist * target_r)
                        
                        outcome = None
                        exit_price = None
                        exit_time = None
                        
                        for f_idx in range(idx + 1, min(idx + 30, len(m15_times))):
                            bar_h = m15_highs[f_idx]
                            bar_l = m15_lows[f_idx]
                            
                            if bar_l <= sl_price:
                                outcome = "LOSS"
                                exit_price = sl_price
                                exit_time = m15_times[f_idx]
                                break
                            elif bar_h >= tp_price:
                                outcome = "WIN"
                                exit_price = tp_price
                                exit_time = m15_times[f_idx]
                                break
                                
                        if outcome is None:
                            exit_price = m15_closes[min(idx + 29, len(m15_times) - 1)]
                            exit_time = m15_times[min(idx + 29, len(m15_times) - 1)]
                            outcome = "WIN" if exit_price > entry_price else "LOSS"
                            
                        risk_usd = balance * risk_pct
                        pip_value_per_lot = 10.0
                        lot_size = round(risk_usd / (sl_pips * pip_value_per_lot), 2)
                        lot_size = max(0.01, min(lot_size, 50.0))
                        
                        pnl_pips = (exit_price - entry_price) * 10000
                        pnl_usd = (pnl_pips * pip_value_per_lot * lot_size) - (lot_size * 6.0)
                        
                        balance += pnl_usd
                        trades.append({
                            "date": t_now,
                            "direction": "BUY",
                            "entry": entry_price,
                            "sl": sl_price,
                            "tp": tp_price,
                            "sl_pips": sl_pips,
                            "outcome": outcome,
                            "pnl": pnl_usd,
                            "balance": balance
                        })
                        trade_taken_today = True
                        break
                        
    return trades, balance

print("\n--- Testing Asian Range Sweep M15 Strategy ---")
for r in [1.5, 2.0, 2.5]:
    tr, final_bal = run_asian_sweep_strategy(target_r=r, risk_pct=0.015)
    wins = len([t for t in tr if t["pnl"] > 0])
    wr = wins / len(tr) * 100 if tr else 0.0
    net_pnl = final_bal - 10000.0
    print(f"Target R={r:.1f}: Trades={len(tr)}, Wins={wins}, WR={wr:.1f}%, Net PnL=+${net_pnl:.2f}")
    
    # Monthly breakdown for r=2.0
    if r == 2.0:
        by_month = defaultdict(list)
        for t in tr:
            by_month[t["date"].strftime("%Y-%m")].append(t)
        for m in sorted(by_month.keys()):
            m_tr = by_month[m]
            m_pnl = sum(x["pnl"] for x in m_tr)
            m_wins = len([x for x in m_tr if x["pnl"] > 0])
            m_wr = m_wins / len(m_tr) * 100 if m_tr else 0.0
            print(f"    {m}: {len(m_tr):>2} trades, WR={m_wr:>5.1f}%, PnL=+${m_pnl:>7.2f}")
