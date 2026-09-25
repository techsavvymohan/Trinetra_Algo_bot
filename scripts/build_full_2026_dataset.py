import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def normalize_time(t_str: str) -> str:
    """Normalize timestamp string to standard ISO format with UTC timezone."""
    # handle formats like '2026-01-01 23:04:00.000000', '2026-01-01T23:04:00+00:00', etc.
    t_clean = t_str.strip()
    if t_clean.endswith("+00:00"):
        t_clean = t_clean[:-6]
    elif t_clean.endswith("Z"):
        t_clean = t_clean[:-1]
    
    # replace space with T
    if " " in t_clean:
        parts = t_clean.split(" ")
        t_clean = f"{parts[0]}T{parts[1]}"
    
    # trim microseconds
    if "." in t_clean:
        t_clean = t_clean.split(".")[0]
        
    return t_clean + "+00:00"

def merge_symbol_data(symbol_key: str, files_list: list, out_file: Path):
    print(f"\n>>> Merging datasets for {symbol_key}...")
    merged = {"M1": {}, "M5": {}, "M15": {}, "H1": {}}
    
    # We will build a dictionary: tf -> { norm_time -> (o, h, l, c, v, s) }
    tf_records = {tf: {} for tf in ["M1", "M5", "M15", "H1"]}
    
    for fpath in files_list:
        p = DATA_DIR / fpath
        if not p.exists():
            print(f"  Warning: {fpath} does not exist!")
            continue
        print(f"  Reading {fpath}...")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        for tf in ["M1", "M5", "M15", "H1"]:
            if tf not in data:
                continue
            times = data[tf]["time"]
            opens = data[tf]["open"]
            highs = data[tf]["high"]
            lows = data[tf]["low"]
            closes = data[tf]["close"]
            vols = data[tf].get("tick_volume", [0] * len(times))
            spreads = data[tf].get("spread", [0] * len(times))
            
            for i in range(len(times)):
                nt = normalize_time(times[i])
                # Filter to Jan 1, 2026 - Sep 24, 2026 23:59:59
                if "2026-01-01" <= nt[:10] <= "2026-09-24":
                    tf_records[tf][nt] = (
                        opens[i], highs[i], lows[i], closes[i], vols[i], spreads[i]
                    )
                    
    for tf in ["M1", "M5", "M15", "H1"]:
        sorted_times = sorted(tf_records[tf].keys())
        if not sorted_times:
            print(f"  ❌ No data for {tf}!")
            continue
        opens = [tf_records[tf][t][0] for t in sorted_times]
        highs = [tf_records[tf][t][1] for t in sorted_times]
        lows = [tf_records[tf][t][2] for t in sorted_times]
        closes = [tf_records[tf][t][3] for t in sorted_times]
        vols = [tf_records[tf][t][4] for t in sorted_times]
        spreads = [tf_records[tf][t][5] for t in sorted_times]
        
        merged[tf] = {
            "time": sorted_times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": vols,
            "spread": spreads,
        }
        print(f"  [OK] {tf}: {len(sorted_times)} bars ({sorted_times[0][:16]} -> {sorted_times[-1][:16]})")
        
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(merged, f)
    print(f"  [SAVED] complete 2026 dataset to {out_file} ({out_file.stat().st_size / (1024*1024):.1f} MB)")

def main():
    xau_files = [
        "genuine_jan_aug_2026_xauusd.json",
        "genuine_recent_xauusd.json",
        "fetched_sep21_25_2026_xauusd.json"
    ]
    nas_files = [
        "genuine_jan_aug_2026_nas100.json",
        "genuine_recent_nas100.json",
        "fetched_sep21_25_2026_nas100.json"
    ]
    
    merge_symbol_data("XAUUSD", xau_files, DATA_DIR / "full_2026_xauusd.json")
    merge_symbol_data("USTECH100M", nas_files, DATA_DIR / "full_2026_nas100.json")

if __name__ == "__main__":
    main()
