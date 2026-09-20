import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine

def to_naive_dt(t):
    if isinstance(t, str):
        t_clean = t.replace("T", " ")
        if "+" in t_clean:
            t_clean = t_clean.split("+")[0]
        if "Z" in t_clean:
            t_clean = t_clean.replace("Z", "")
        return datetime.fromisoformat(t_clean)
    elif hasattr(t, "replace"):
        return t.replace(tzinfo=None)
    return t

with open("data/genuine_jan_aug_2026_nas100.json") as f:
    d1 = json.load(f)["M1"]

cfg = Config.load()
dt_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
dt_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)
eng = BacktestEngine(cfg, initial_balance=100000.0, symbol="USTECH100M", start_date=dt_start, end_date=dt_end)
res = eng.run({"M1": d1})

print("Telemetry counters for Jan-May:")
for k, v in eng._ablation_counters.items():
    print(f"  {k}: {v}")
print(f"Total trades: {res.get('total_trades', 0)}")
