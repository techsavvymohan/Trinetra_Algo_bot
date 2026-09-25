import json
from pathlib import Path
from datetime import datetime, timezone

def inspect():
    with open("data/fetched_sep21_25_2026_nas100.json", "r") as f:
        nas = json.load(f)["M1"]

    with open("data/fetched_sep21_25_2026_xauusd.json", "r") as f:
        xau = json.load(f)["M1"]

    trades = [
        {"sym": "USTECH100M", "data": nas, "time": "2026-09-21T14:21", "dir": "BUY", "entry": 29975.00, "sl": 29961.10, "tp": 30002.80},
        {"sym": "USTECH100M", "data": nas, "time": "2026-09-24T14:13", "dir": "SELL", "entry": 30217.20, "sl": 30241.10, "tp": 30169.40},
        {"sym": "XAUUSD", "data": xau, "time": "2026-09-23T09:53", "dir": "BUY", "entry": 4333.38, "sl": 4329.32, "tp": 4341.50},
    ]

    for t in trades:
        print(f"\n=======================================================")
        print(f"Inspecting {t['sym']} {t['dir']} at {t['time']} (Entry: {t['entry']}, SL: {t['sl']})")
        d = t["data"]
        times = d["time"]
        # Find index
        idx = None
        for i, tm in enumerate(times):
            if tm.startswith(t["time"]):
                idx = i
                break
        if idx is None:
            print("  Timestamp not found!")
            continue

        print(f"  Bar index: {idx}, time: {times[idx]}")
        # Look forward 60 bars (1 hour)
        min_p = float("inf")
        max_p = float("-inf")
        sl_hit_bar = None
        sl_hit_price = None

        for offset in range(1, 61):
            if idx + offset >= len(times):
                break
            cur_t = times[idx + offset]
            h = d["high"][idx + offset]
            l = d["low"][idx + offset]
            c = d["close"][idx + offset]
            min_p = min(min_p, l)
            max_p = max(max_p, h)

            if t["dir"] == "BUY" and l <= t["sl"] and sl_hit_bar is None:
                sl_hit_bar = offset
                sl_hit_price = l
                print(f"  [SL HIT] at +{offset} bars ({cur_t}) | Low: {l} <= SL {t['sl']}")

            if t["dir"] == "SELL" and h >= t["sl"] and sl_hit_bar is None:
                sl_hit_bar = offset
                sl_hit_price = h
                print(f"  [SL HIT] at +{offset} bars ({cur_t}) | High: {h} >= SL {t['sl']}")

        print(f"  Next 60 bars: Lowest={min_p:.2f}, Highest={max_p:.2f}")

        # Did it go in anticipated direction?
        if t["dir"] == "BUY":
            print(f"  Lowest wick dip below SL: {t['sl'] - min_p:.2f} pts | Highest rally after: {max_p - t['entry']:.2f} pts")
        else:
            print(f"  Highest wick spike above SL: {max_p - t['sl']:.2f} pts | Lowest drop after: {t['entry'] - min_p:.2f} pts")

if __name__ == "__main__":
    inspect()
