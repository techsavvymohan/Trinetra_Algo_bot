import json
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xauusd_bot.config import Config
from xauusd_bot.backtesting.engine import BacktestEngine
from xauusd_bot.models import SignalGrade, TradeDirection, Bias

with open("data/genuine_jan_aug_2026_xauusd.json") as f:
    data_xau = json.load(f)

cfg = Config.load()
cfg.trading.symbol = "XAUUSD"

class DebugEngine(BacktestEngine):
    def _generate_backtest_signal(self, data_all, idx, price, current_time=None):
        sig = super()._generate_backtest_signal(data_all, idx, price, current_time=current_time)
        if sig:
            print(f"Signal: dir={sig.direction}, h1_bias={sig.h1_bias} (type={type(sig.h1_bias)}), h4_bias={sig.h4_bias}, grade={sig.grade}")
            return None # Just print first few
        return sig

eng = DebugEngine(cfg, 10000.0, "XAUUSD")
# Run on first 10000 bars
small_data = {tf: {k: v[:10000] if isinstance(v, list) else v for k, v in tdata.items()} for tf, tdata in data_xau.items()}
eng.run(small_data)
