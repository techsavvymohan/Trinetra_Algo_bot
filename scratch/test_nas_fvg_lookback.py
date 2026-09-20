import sys
import json
from pathlib import Path
from collections import defaultdict
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import TradeStatus, TimeframeData, TradeDirection
from xauusd_bot.strategy.trigger import TriggerDetector

with open("data/genuine_jan_aug_2026_nas100.json") as f:
    data_nas = json.load(f)

# Let's see what happens if detect_m1_fvg searches the last N bars (e.g. 5 bars) for the most recent valid FVG
original_detect_fvg = TriggerDetector.detect_m1_fvg

def detect_m1_fvg_multi(self, data: TimeframeData, direction: TradeDirection, lookback_bars: int = 5) -> Optional[Tuple[float, float]]:
    h = data.high
    l = data.low
    n = len(h)
    if n < 3:
        return None
    # Check backwards from current candle
    max_k = min(lookback_bars, n - 2)
    for k in range(1, max_k + 1):
        c1_idx = - (k + 2)
        c3_idx = - k
        c1_high, c1_low = h[c1_idx], l[c1_idx]
        c3_high, c3_low = h[c3_idx], l[c3_idx]
        if direction == TradeDirection.BUY:
            if c1_high < c3_low:
                return (c1_high, c3_low)
        else:
            if c1_low > c3_high:
                return (c3_high, c1_low)
    return None

TriggerDetector.detect_m1_fvg = lambda self, data, direction: detect_m1_fvg_multi(self, data, direction, lookback_bars=5)

cfg = Config.load()
cfg.trading.symbol = "USTECH100M"
cfg.trading.symbols = ["USTECH100M"]
cfg.trading.nas_fvg_expiry_bars = 12
cfg.trading.nas_retest_max_bars = 12

engine = BacktestEngine(cfg, initial_balance=10000.0, symbol="USTECH100M")
res = engine.run(data_nas)

monthly_trades = defaultdict(list)
for c in engine._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
            m = str(leg.open_time)[:7]
            monthly_trades[m].append(leg.pnl)

print("=== ENHANCED FVG LOOKBACK NAS100 ===")
for m in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]:
    trades = monthly_trades.get(m, [])
    if trades:
        wins = len([p for p in trades if p > 0])
        pnl = sum(trades)
        status = "[GREEN]" if pnl > 0 else "[RED]"
        print(f"  {m}: {len(trades):>3} trades, PnL = ${pnl:>9.2f}, WR = {wins/len(trades)*100:>5.1f}% {status}")
    else:
        print(f"  {m}:   0 trades, PnL = $     0.00, WR =   0.0%")

print(f"TOTAL: {res['total_trades']} trades, PnL = ${res['total_pnl']:.2f}")
