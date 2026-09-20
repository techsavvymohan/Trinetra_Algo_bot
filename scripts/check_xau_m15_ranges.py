import sys, os, json
from datetime import datetime
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

with open('data/genuine_jan_aug_2026_xauusd.json', 'r') as f:
    raw_data = json.load(f)

m15 = raw_data['M15']
times = m15['time']
highs = m15['high']
lows = m15['low']

m_atr = defaultdict(list)
for t, h, l in zip(times, highs, lows):
    dt = datetime.fromisoformat(t)
    rng = h - l
    m_atr[dt.month].append(rng)

print(f"{'Month':<6} {'Avg M15 Range ($)':<20} {'Max M15 Range ($)'}")
print("-" * 45)
NAMES = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',7:'Jul',8:'Aug'}
for m in range(1, 9):
    arr = m_atr[m]
    avg_r = sum(arr) / len(arr) if arr else 0
    max_r = max(arr) if arr else 0
    print(f"{NAMES[m]:<6} ${avg_r:<19.2f} ${max_r:.2f}")
