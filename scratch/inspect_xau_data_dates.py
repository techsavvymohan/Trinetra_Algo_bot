import json
from datetime import datetime

for fname in ["data/genuine_jan_aug_2026_xauusd.json", "data/genuine_recent_xauusd.json", "data/fetched_18sep2026_xauusd.json"]:
    try:
        with open(fname) as f:
            data = json.load(f)
        m1 = data.get("M1", {})
        times = m1.get("time", [])
        if times:
            print(f"{fname}: {len(times)} M1 bars | start={times[0]} | end={times[-1]}")
        else:
            print(f"{fname}: no M1 time found")
    except Exception as e:
        print(f"{fname}: error {e}")
