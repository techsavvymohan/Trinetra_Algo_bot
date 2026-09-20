import json
import sys, os
sys.path.insert(0, '.')
from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, TradeStatus, Bias

with open('data/genuine_jan_aug_2026_xauusd.json') as f:
    data_xau = json.load(f)

cfg = Config.load()
cfg.trading.symbol = 'XAUUSD'

eng = BacktestEngine(cfg, 10000.0, 'XAUUSD')
eng.run(data_xau)

aligned_trades = []
unaligned_trades = []

for c in eng._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED and leg.exit_price is not None:
            # Check if this trade was aligned
            # Find the signal from _pending_fvg_orders or cluster
            pass

# Let's run with signal grade tracking directly in BacktestEngine
class TrackEngine(BacktestEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trade_records = []

    def _generate_signal(self, hierarchy_result, data_all, price, current_time=None):
        sig = super()._generate_signal(hierarchy_result, data_all, price, current_time=current_time)
        if sig:
            h1 = sig.h1_bias.value if isinstance(sig.h1_bias, Bias) else str(sig.h1_bias)
            h4 = sig.h4_bias.value if isinstance(sig.h4_bias, Bias) else str(sig.h4_bias)
            aligned = (sig.direction == TradeDirection.BUY and (h1 == "bullish" or (h1 == "neutral" and h4 == "bullish"))) or \
                      (sig.direction == TradeDirection.SELL and (h1 == "bearish" or (h1 == "neutral" and h4 == "bearish")))
            sig._is_aligned = aligned
            sig._h1_val = h1
            sig._h4_val = h4
        return sig

eng = TrackEngine(cfg, 10000.0, 'XAUUSD')
eng.run(data_xau)

trades = []
for po in eng._ablation_counters:
    pass

# Check clusters
for c in eng._clusters:
    for leg in c.legs:
        if leg.status == TradeStatus.CLOSED:
            trades.append(leg)

print(f"Total trades closed: {len(trades)}")
