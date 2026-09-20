import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.config import Config
from xauusd_bot.strategy.trigger import TriggerDetector
from xauusd_bot.indicators.atr import atr
from xauusd_bot.models import TimeframeData, TradeDirection
from xauusd_bot.utils.asset_specs import get_asset_spec
from xauusd_bot.backtesting.engine import BacktestEngine

with open("data/genuine_jan_aug_2026_nas100.json") as f:
    data_nas = json.load(f)

m1_raw = data_nas["M1"]
m15_raw = data_nas["M15"]

cfg = Config.load()
cfg.trading.symbol = "USTECH100M"
cfg.trading.symbols = ["USTECH100M"]

trigger = TriggerDetector(cfg.trading.ema_fast, cfg.trading.rsi_period,
                          cfg.trading.rsi_mid_upper, cfg.trading.rsi_mid_lower)

# Let's count for each month in Jan - May
for target_m in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]:
    indices = [i for i, t in enumerate(m1_raw["time"]) if target_m in str(t)]
    if not indices:
        print(f"{target_m}: No M1 bars!")
        continue
    start_idx, end_idx = indices[0], indices[-1]

    us_cash_count = 0
    sweeps_found = 0
    reclaims_found = 0
    displacements_found = 0
    mss_found = 0
    fvg_found = 0
    orders_placed = 0

    # Let's run a sample scan
    engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M")
    
    # We can inspect what happens in BacktestEngine for this month
    data_month = {
        "M1": {k: v[start_idx:end_idx+1] for k, v in m1_raw.items()},
        "M15": m15_raw,  # full M15
    }
    
    # Let's count US cash bars
    for t in m1_raw["time"][start_idx:end_idx+1]:
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00")) if isinstance(t, str) else t
        h, m = dt.hour, dt.minute
        if (13 < h < 20) or (h == 13 and m >= 30):
            us_cash_count += 1

    res = engine.run(data_month)
    n_trades = res.get("total_trades", 0)
    pnl = res.get("total_pnl", 0.0)
    print(f"{target_m}: US Cash bars={us_cash_count}, Trades={n_trades}, PnL=${pnl:.2f}")
    print(f"  Telemetry: {dict(engine._ablation_counters)}")
