import sys, json
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(".").resolve()
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TradeDirection

SEP_START = datetime(2026, 9, 1, tzinfo=timezone.utc)
SEP_END   = datetime(2026, 9, 19, 23, 59, 59, tzinfo=timezone.utc)

with open("data/native_true_jun_sep_xauusd.json") as f: base = json.load(f)
with open("data/fetched_18sep2026_xauusd.json") as f: overlay = json.load(f)

result = {}
for tf in set(list(base.keys()) + list(overlay.keys())):
    bd = base.get(tf, {})
    od = overlay.get(tf, {})
    combined = {}
    for i, t in enumerate(bd.get("time", [])):
        bar = {k: bd[k][i] for k in bd if k != "tf" and isinstance(bd[k], list)}
        bar["time"] = t
        combined[t] = bar
    for i, t in enumerate(od.get("time", [])):
        bar = {k: od[k][i] for k in od if k != "tf" and isinstance(od[k], list)}
        bar["time"] = t
        combined[t] = bar
    sorted_bars = sorted(combined.values(), key=lambda b: b["time"])
    if not sorted_bars:
        result[tf] = bd if bd else od
        continue
    keys = [k for k in sorted_bars[0].keys() if k != "time"]
    merged = {"tf": tf, "time": [b["time"] for b in sorted_bars]}
    for k in keys:
        merged[k] = [b.get(k, 0.0) for b in sorted_bars]
    result[tf] = merged

cfg = Config.load()
cfg.trading.backtest_initial_balance    = 10000.0
cfg.trading.backtest_apply_friction     = True
cfg.trading.backtest_commission_per_lot = 6.0

engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD",
                        start_date=SEP_START, end_date=SEP_END)
res = engine.run(result)

trades = []
if hasattr(engine, "_clusters"):
    for cluster in engine._clusters:
        for leg in cluster.legs:
            if leg.status == TradeStatus.CLOSED and leg.exit_price:
                dt_open = leg.open_time if isinstance(leg.open_time, datetime) else datetime.fromisoformat(str(leg.open_time))
                pnl  = getattr(leg, "pnl", 0.0) or 0.0
                sl   = getattr(leg, "sl_price",   None)
                tp   = getattr(leg, "tp_price",   None)
                ep   = getattr(leg, "entry_price", None) or getattr(leg, "open_price", None)
                ep   = ep or getattr(leg, "open_price", 0.0)
                exit_p = leg.exit_price
                exit_r = getattr(leg, "exit_reason", "UNKNOWN")
                dirn   = getattr(leg.direction, "name", str(leg.direction))
                lots   = getattr(leg, "volume", getattr(leg, "lots", 0.0))
                trades.append({
                    "open": dt_open, "pnl": pnl, "dir": dirn,
                    "ep": ep, "sl": sl, "tp": tp, "exit_p": exit_p,
                    "exit_r": exit_r, "lots": lots,
                })

print(f"\nXAUUSD Sep 1-19 | All {len(trades)} Trades")
print("="*95)
for i, t in enumerate(sorted(trades, key=lambda x: x["open"]), 1):
    status = "WIN " if t["pnl"] > 0.01 else ("LOSS" if t["pnl"] < -0.01 else "BE  ")
    ep = t["ep"] or 0
    sl = t["sl"] or 0
    tp = t["tp"] or 0
    sl_dist = abs(ep - sl) if ep and sl else 0
    tp_dist = abs(tp - ep) if tp and ep else 0
    rr = f"{tp_dist/sl_dist:.1f}R" if sl_dist > 0 else "?"
    print(f"  #{i:2} [{status}] {t['open'].strftime('%b %d %H:%M')} {t['dir']:<5}  "
          f"Entry={ep:.2f}  SL={sl:.2f}  TP={tp:.2f}  Exit={t['exit_p']:.2f}  "
          f"RR={rr}  PnL=${t['pnl']:>8.2f}  [{t['exit_r']}]")

wins   = [t for t in trades if t["pnl"] > 0.01]
losses = [t for t in trades if t["pnl"] < -0.01]

print(f"\n{'='*95}")
print(f"EXIT REASON BREAKDOWN:")
exit_reasons = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0})
for t in trades:
    r = t["exit_r"]
    exit_reasons[r]["count"] += 1
    exit_reasons[r]["pnl"] += t["pnl"]
    if t["pnl"] > 0.01: exit_reasons[r]["wins"] += 1
    elif t["pnl"] < -0.01: exit_reasons[r]["losses"] += 1
for reason, s in sorted(exit_reasons.items(), key=lambda x: x[1]["pnl"]):
    print(f"  {reason:<35} | {s['count']:>3} trades | {s['wins']}W/{s['losses']}L | PnL=${s['pnl']:>9.2f}")

print(f"\nDAY OF WEEK:")
dow = defaultdict(lambda: {"t": 0, "w": 0, "l": 0, "pnl": 0.0})
for t in trades:
    d = t["open"].strftime("%A")
    dow[d]["t"] += 1; dow[d]["pnl"] += t["pnl"]
    if t["pnl"] > 0.01: dow[d]["w"] += 1
    elif t["pnl"] < -0.01: dow[d]["l"] += 1
for day in ["Monday","Tuesday","Wednesday","Thursday","Friday"]:
    if day in dow:
        s = dow[day]
        wr = s["w"]/s["t"]*100 if s["t"] else 0
        print(f"  {day:<12}: {s['t']} trades | {s['w']}W/{s['l']}L | WR={wr:.0f}% | PnL=${s['pnl']:.2f}")

print(f"\nHOUR OF DAY (UTC):")
hour = defaultdict(lambda: {"t": 0, "w": 0, "l": 0, "pnl": 0.0})
for t in trades:
    h = t["open"].hour
    hour[h]["t"] += 1; hour[h]["pnl"] += t["pnl"]
    if t["pnl"] > 0.01: hour[h]["w"] += 1
    elif t["pnl"] < -0.01: hour[h]["l"] += 1
for h in sorted(hour.keys()):
    s = hour[h]
    wr = s["w"]/s["t"]*100 if s["t"] else 0
    bar = "+" * s["w"] + "-" * s["l"]
    print(f"  {h:02d}:xx UTC : {s['t']} trades | {s['w']}W/{s['l']}L | WR={wr:.0f}% | PnL=${s['pnl']:>8.2f}  {bar}")
