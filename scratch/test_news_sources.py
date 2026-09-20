import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import urllib.request
from datetime import datetime, timezone, timedelta
import requests

def test_forexfactory():
    print("--- Testing Option 1: ForexFactory (FairEconomy Live JSON) ---")
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    try:
        start_t = datetime.now()
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            elapsed = (datetime.now() - start_t).total_seconds()
            if status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                usd_events = [e for e in data if e.get("country") == "USD"]
                high_usd = [e for e in usd_events if str(e.get("impact")).lower() in ("high", "red")]
                print(f"[PASS] ForexFactory SUCCESS! HTTP {status} in {elapsed:.2f}s")
                print(f"   Total events this week: {len(data)}")
                print(f"   USD events: {len(usd_events)}")
                print(f"   High-Impact (Red Folder) USD events: {len(high_usd)}")
                if high_usd:
                    print(f"   Sample High-Impact USD Events this week:")
                    for e in high_usd[:3]:
                        print(f"     * {e.get('date')} | {e.get('title')} | Impact: {e.get('impact')}")
                return True
            else:
                print(f"[FAIL] ForexFactory returned HTTP {status}")
                return False
    except Exception as e:
        print(f"[FAIL] ForexFactory FAILED: {e}")
        return False

def test_lse():
    print("\n--- Testing Option 2: London Strategic Edge (LSE) ---")
    api_key = os.getenv("LSE_API_KEY", "")
    if not api_key:
        # Try loading from .env
        from pathlib import Path
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("LSE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    print(f"   Using LSE_API_KEY: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else ''}")
    lse_url = "https://api.londonstrategicedge.com/vault/ref/economic_calendar"
    now_utc = datetime.now(timezone.utc)
    start_date = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")
    end_date = (now_utc + timedelta(days=7)).strftime("%Y-%m-%d")
    headers = {"x-api-key": api_key}

    try:
        start_t = datetime.now()
        resp = requests.get(
            lse_url,
            params={"region": "US", "start": start_date, "end": end_date, "limit": 100},
            headers=headers,
            timeout=10,
        )
        elapsed = (datetime.now() - start_t).total_seconds()
        print(f"   LSE HTTP Status: {resp.status_code} in {elapsed:.2f}s")
        if resp.status_code == 200:
            events = resp.json()
            print(f"[PASS] London Strategic Edge SUCCESS! HTTP 200")
            print(f"   Total US events returned: {len(events)}")
            if events:
                print(f"   Sample events:")
                for e in events[:3]:
                    print(f"     * {e.get('datetime') or e.get('date')} | {e.get('event')} | Region: {e.get('region_code')}")
            return True
        else:
            print(f"[FAIL] LSE returned HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[FAIL] LSE FAILED: {e}")
        return False

def test_economic_calendar_class():
    print("\n--- Testing Full EconomicCalendar Class (with fallback) ---")
    from dotenv import load_dotenv
    load_dotenv()
    from xauusd_bot.data.economic_calendar import EconomicCalendar
    cal = EconomicCalendar()
    success = cal.fetch(days_ahead=3, force=True)
    print(f"   Calendar fetch result: {success}")
    print(f"   Total loaded events: {len(cal.events)}")
    if cal.events:
        print(f"   Sample loaded events:")
        for e in cal.events[:3]:
            print(f"     * {e.date} | {e.title} | Impact: {e.impact}")
    blocked, reason = cal.is_blocked()
    print(f"   Currently News Blocked? {blocked} ({reason})")

if __name__ == "__main__":
    ff_ok = test_forexfactory()
    lse_ok = test_lse()
    test_economic_calendar_class()
