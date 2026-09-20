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

# Let's calculate Daily High (PDH) and Daily Low (PDL)
bars_by_date = defaultdict(list)
for i, t in enumerate(m15_times):
    bars_by_date[t.date()].append(i)

daily_levels = {}
sorted_dates = sorted(bars_by_date.keys())
for idx, d in enumerate(sorted_dates):
    if idx == 0:
        continue
    prev_d = sorted_dates[idx - 1]
    prev_indices = bars_by_date[prev_d]
    pdh = max(m15_highs[i] for i in prev_indices)
    pdl = min(m15_lows[i] for i in prev_indices)
    daily_levels[d] = (pdh, pdl)

# Strategy 3: London / NY Sweep of PDH / PDL with MSS & FVG confirmation
# When price sweeps PDH/PDL during active sessions (07:00 - 16:00 UTC) and reclaims with M15 confirmation

def run_pdl_pdh_sweep(target_r=2.0, risk_pct=0.015, initial_balance=10000.0):
    balance = initial_balance
    trades = []
    
    for d, indices in sorted(bars_by_date.items()):
        if d not in daily_levels:
            continue
        pdh, pdl = daily_levels[d]
        
        trade_taken = False
        for i in indices:
            if trade_taken:
                break
            t_now = m15_times[i]
            # Active European / US session (07:00 - 15:00 UTC)
            if not (7 <= t_now.hour < 15):
                continue
                
            c = m15_closes[i]
            o = m15_opens[i]
            h = m15_highs[i]
            l = m15_lows[i]
            
            # Bearish Sweep of PDH
            if h > pdh and c < pdh and c < o:
                sl = h + 0.00030
                sl_dist = sl - c
                sl_pips = sl_dist * 10000
                if 8 <= sl_pips <= 25:
                    entry = c
                    tp = entry - (sl_dist * target_r)
                    
                    outcome = None
                    exit_price = None
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
                    lot = round(risk_usd / (sl_pips * 10.0), 2)
                    lot = max(0.01, min(lot, 50.0))
                    pnl_pips = (entry - exit_price) * 10000
                    pnl_usd = (pnl_pips * 10.0 * lot) - (lot * 6.0)
                    balance += pnl_usd
                    trades.append({"date": t_now, "dir": "SELL", "pnl": pnl_usd, "outcome": outcome})
                    trade_taken = True
                    break
                    
            # Bullish Sweep of PDL
            elif l < pdl and c > pdl and c > o:
                sl = l - 0.00030
                sl_dist = c - sl
                sl_pips = sl_dist * 10000
                if 8 <= sl_pips <= 25:
                    entry = c
                    tp = entry + (sl_dist * target_r)
                    
                    outcome = None
                    exit_price = None
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
                    lot = round(risk_usd / (sl_pips * 10.0), 2)
                    lot = max(0.01, min(lot, 50.0))
                    pnl_pips = (exit_price - entry) * 10000
                    pnl_usd = (pnl_pips * 10.0 * lot) - (lot * 6.0)
                    balance += pnl_usd
                    trades.append({"date": t_now, "dir": "BUY", "pnl": pnl_usd, "outcome": outcome})
                    trade_taken = True
                    break
                    
    return trades, balance

print("\n--- Testing PDH / PDL Sweep Strategy on EURUSD ---")
for r in [1.5, 2.0, 2.5]:
    tr, bal = run_pdl_pdh_sweep(target_r=r)
    wins = len([t for t in tr if t["pnl"] > 0])
    wr = wins / len(tr) * 100 if tr else 0.0
    pnl = bal - 10000.0
    print(f"Target R={r:.1f}: Trades={len(tr)}, Wins={wins}, WR={wr:.1f}%, Net PnL=+${pnl:.2f}")
    if r == 2.0:
        by_m = defaultdict(list)
        for t in tr:
            by_m[t["date"].strftime("%Y-%m")].append(t)
        for m in sorted(by_m.keys()):
            m_tr = by_m[m]
            m_pnl = sum(x["pnl"] for x in m_tr)
            m_wins = len([x for x in m_tr if x["pnl"] > 0])
            m_wr = m_wins / len(m_tr) * 100 if m_tr else 0.0
            print(f"    {m}: {len(m_tr):>2} trades, WR={m_wr:>5.1f}%, PnL=+${m_pnl:>7.2f}")
