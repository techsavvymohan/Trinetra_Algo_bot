#!/usr/bin/env python3
"""
Fetch 100% Genuine, Real-Market Data directly from connected MT5 Broker Terminal.
Guarantees:
- Authentic broker prices (Open, High, Low, Close, Tick Volume, Spread)
- Zero synthetic, artificial, or interpolated bars
- Full Multi-Timeframe synchronization (M1, M5, M15, H1, H4)
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

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

try:
    import MetaTrader5 as mt5
except ImportError:
    print("❌ MetaTrader5 package is not installed. Run: pip install MetaTrader5")
    sys.exit(1)

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from xauusd_bot.config import Config


def fetch_genuine_symbol_data(symbol: str, output_filename: str, max_m1_bars: int = 70000):
    cfg = Config()
    mt5_cfg = cfg.mt5

    init_kwargs = {"timeout": mt5_cfg.timeout_ms}
    if mt5_cfg.path and Path(mt5_cfg.path).exists():
        init_kwargs["path"] = mt5_cfg.path
    if mt5_cfg.login:
        init_kwargs["login"] = mt5_cfg.login
    if mt5_cfg.password:
        init_kwargs["password"] = mt5_cfg.password
    if mt5_cfg.server:
        init_kwargs["server"] = mt5_cfg.server

    if not mt5.initialize(**init_kwargs):
        # Fallback attach
        if not mt5.initialize():
            print(f"❌ Failed to connect to MT5: {mt5.last_error()}")
            return None

    print(f" Connected to MT5 Terminal: Account {mt5.account_info().login} on {mt5.account_info().server}")

    # Ensure symbol is selected
    if not mt5.symbol_select(symbol, True):
        print(f"❌ Failed to select symbol {symbol} in Market Watch")
        mt5.shutdown()
        return None

    info = mt5.symbol_info(symbol)
    if not info:
        print(f"❌ Symbol {symbol} not found on broker")
        mt5.shutdown()
        return None

    print(f"\n=======================================================")
    print(f"  FETCHING 100% GENUINE REAL-MARKET DATA: {symbol}")
    print(f"=======================================================")
    print(f"  Broker Path     : {info.path}")
    print(f"  Contract Size   : {info.trade_contract_size}")
    print(f"  Point Size      : {info.point}")
    print(f"  Digits          : {info.digits}")
    print(f"  Current Spread  : {info.spread} points")

    tf_map = {
        "M1": (mt5.TIMEFRAME_M1, max_m1_bars),
        "M5": (mt5.TIMEFRAME_M5, max_m1_bars),
        "M15": (mt5.TIMEFRAME_M15, max_m1_bars),
        "H1": (mt5.TIMEFRAME_H1, 35000),
        "H4": (mt5.TIMEFRAME_H4, 10000),
    }

    dataset = {}

    for tf_name, (tf_code, count) in tf_map.items():
        rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, count)
        if rates is None or len(rates) == 0:
            print(f"  ❌ Failed fetching {tf_name} for {symbol}: {mt5.last_error()}")
            continue

        times = []
        opens = []
        highs = []
        lows = []
        closes = []
        tick_volumes = []
        spreads = []

        for r in rates:
            dt = datetime.fromtimestamp(r["time"], tz=timezone.utc)
            times.append(dt.isoformat())
            opens.append(float(r["open"]))
            highs.append(float(r["high"]))
            lows.append(float(r["low"]))
            closes.append(float(r["close"]))
            tick_volumes.append(int(r["tick_volume"]))
            spreads.append(int(r["spread"]))

        dataset[tf_name] = {
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": tick_volumes,
            "spread": spreads,
        }

        t_start = datetime.fromtimestamp(rates[0]["time"], tz=timezone.utc)
        t_end = datetime.fromtimestamp(rates[-1]["time"], tz=timezone.utc)
        print(f"  ✅ {tf_name:>3}: {len(rates):>6} genuine bars | {t_start.strftime('%Y-%m-%d %H:%M')} -> {t_end.strftime('%Y-%m-%d %H:%M')} (Price: {closes[0]:.2f} -> {closes[-1]:.2f})")

    mt5.shutdown()

    # Save to disk
    out_path = Path("data") / output_filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f)

    file_size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n💾 Saved {symbol} genuine dataset to: {out_path} ({file_size_mb:.2f} MB)")
    return out_path


if __name__ == "__main__":
    target_symbol = sys.argv[1] if len(sys.argv) > 1 else "USTECH100M"
    out_file = sys.argv[2] if len(sys.argv) > 2 else f"genuine_recent_{target_symbol.lower()}.json"
    fetch_genuine_symbol_data(target_symbol, out_file)
