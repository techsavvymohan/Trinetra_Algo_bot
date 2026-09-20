"""Test script to verify stitching of both XAUUSD and NAS100 datasets from Jan 1 to Sep 18, 2026."""
import json
from datetime import datetime

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

def check_stitch(symbol, file1, file2, split_date):
    with open(file1) as f:
        d1 = json.load(f)["M1"]
    with open(file2) as f:
        d2 = json.load(f)["M1"]

    t1 = [to_naive_dt(t) for t in d1["time"]]
    t2 = [to_naive_dt(t) for t in d2["time"]]

    part1 = [t for t in t1 if t < split_date]
    part2 = [t for t in t2 if t >= split_date and t <= datetime(2026, 9, 18, 23, 59, 59)]

    combined = part1 + part2
    print(f"[{symbol}] Part 1: {len(part1)} bars ({part1[0]} -> {part1[-1]})")
    print(f"[{symbol}] Part 2: {len(part2)} bars ({part2[0]} -> {part2[-1]})")
    print(f"[{symbol}] Total Stitched: {len(combined)} bars ({combined[0]} -> {combined[-1]})")

if __name__ == "__main__":
    check_stitch("XAUUSD", "data/genuine_jan_aug_2026_xauusd.json", "data/genuine_recent_xauusd.json", datetime(2026, 9, 1))
    check_stitch("NAS100", "data/genuine_jan_aug_2026_nas100.json", "data/genuine_recent_nas100.json", datetime(2026, 8, 18))
