"""Diagnose what regime the engine classifies each June/July bar as"""
import sys, json
from datetime import datetime
from pathlib import Path
BASE_DIR = Path(r"e:/XAUUSD digger bot")
sys.path.insert(0, str(BASE_DIR))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.strategy.volatility_regime import VolatilityRegimeEngine
from xauusd_bot.models import TradeStatus, TimeframeData
import bisect

with open(r"e:/XAUUSD digger bot/data/genuine_jan_aug_2026_xauusd.json") as f:
    raw_data = json.load(f)

cfg = Config.load()
engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="XAUUSD")
data = engine._convert_dicts(raw_data)
m15 = data["M15"]
m1  = data["M1"]

vr_engine = VolatilityRegimeEngine()
regime_counts = {}

for m in [1, 2, 3, 4, 5, 6, 7, 8]:
    counts = {"TRENDING": 0, "NEUTRAL": 0, "COMPRESSED": 0}
    atr_samples = []
    adx_samples = []
    body_samples = []

    for i in range(55, len(m15.close)):
        t = m15.time[i]
        dt = t if isinstance(t, datetime) else datetime.fromisoformat(str(t))
        if dt.month != m:
            continue
        m15_slice = TimeframeData(
            tf="M15",
            time=m15.time[max(0,i-99):i],
            open=m15.open[max(0,i-99):i],
            high=m15.high[max(0,i-99):i],
            low=m15.low[max(0,i-99):i],
            close=m15.close[max(0,i-99):i],
            tick_volume=m15.tick_volume[max(0,i-99):i],
            spread=m15.spread[max(0,i-99):i],
        )
        if len(m15_slice.close) < 55:
            continue
        state = vr_engine.classify(m15_slice)
        counts[state.regime] += 1
        atr_samples.append(state.atr_ratio)
        adx_samples.append(state.adx_proxy)
        body_samples.append(state.body_ratio)

    regime_counts[m] = counts
    total = sum(counts.values()) or 1
    avg_atr  = sum(atr_samples)/len(atr_samples) if atr_samples else 0
    avg_adx  = sum(adx_samples)/len(adx_samples) if adx_samples else 0
    avg_body = sum(body_samples)/len(body_samples) if body_samples else 0

    NAMES = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",7:"Jul",8:"Aug"}
    print(f"{NAMES[m]}: TRENDING={counts['TRENDING']:>4} ({100*counts['TRENDING']//total:>2}%) | "
          f"NEUTRAL={counts['NEUTRAL']:>4} ({100*counts['NEUTRAL']//total:>2}%) | "
          f"COMPRESSED={counts['COMPRESSED']:>4} ({100*counts['COMPRESSED']//total:>2}%)  "
          f"AvgATR={avg_atr:.3f} AvgADX={avg_adx:.1f} AvgBody={avg_body:.3f}")
