import sys
import datetime
import MetaTrader5 as mt5

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, '.')
from xauusd_bot.config import Config
from xauusd_bot.strategy.timeframe_hierarchy import TimeframeHierarchy
from xauusd_bot.strategy.bias_detector import BiasDetector
from xauusd_bot.strategy.zone_detector import ZoneDetector
from xauusd_bot.strategy.sideways_detector import SidewaysDetector

mt5.initialize()
rates_sample = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 1)
latest_dt = datetime.datetime.fromtimestamp(rates_sample[0]['time'], tz=datetime.timezone.utc)
today_date = latest_dt.date()
start_lookback = datetime.datetime(today_date.year, today_date.month, today_date.day, 0, 0, 0, tzinfo=datetime.timezone.utc) - datetime.timedelta(days=7)
end_time = latest_dt + datetime.timedelta(minutes=1)

tf_map = {
    'M1': mt5.TIMEFRAME_M1,
    'M5': mt5.TIMEFRAME_M5,
    'M15': mt5.TIMEFRAME_M15,
    'M30': mt5.TIMEFRAME_M30,
    'H1': mt5.TIMEFRAME_H1,
    'H4': mt5.TIMEFRAME_H4,
}

def fetch_data_dict(symbol):
    data = {}
    for tf_str, tf_val in tf_map.items():
        rates = mt5.copy_rates_range(symbol, tf_val, start_lookback, end_time)
        times, opens, highs, lows, closes, volumes, spreads = [], [], [], [], [], [], []
        for r in rates:
            dt = datetime.datetime.fromtimestamp(r['time'], tz=datetime.timezone.utc)
            times.append(dt.isoformat())
            opens.append(float(r['open']))
            highs.append(float(r['high']))
            lows.append(float(r['low']))
            closes.append(float(r['close']))
            volumes.append(int(r['tick_volume']))
            spreads.append(int(r['spread']))
        data[tf_str] = {
            'time': times, 'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'tick_volume': volumes, 'spread': spreads,
        }
    return data

today_start_dt = datetime.datetime(today_date.year, today_date.month, today_date.day, 0, 0, 0, tzinfo=datetime.timezone.utc)
cfg = Config.load()

# Let's inspect the HTF bias, sideways status, and why XAUUSD didn't trigger signals today
from xauusd_bot.models import TimeframeData
raw_xau = fetch_data_dict('XAUUSD')

bias_det = BiasDetector(
    cfg.trading.ema_fast, cfg.trading.ema_medium, cfg.trading.ema_slow,
    cfg.trading.rsi_period, cfg.trading.rsi_mid_upper, cfg.trading.rsi_mid_lower,
)
zone_det = ZoneDetector(cfg.trading.vwap_period, cfg.trading.min_structure_swing_bars, cfg.trading.max_structure_swing_bars)
sideways_det = SidewaysDetector(
    chop_threshold=cfg.trading.sideways_chop_threshold,
    adx_threshold=cfg.trading.sideways_adx_threshold,
    bandwidth_squeeze_pct=cfg.trading.sideways_bandwidth_squeeze_pct,
)

# Convert all TFs to TimeframeData
data_all = {}
for tf, d in raw_xau.items():
    data_all[tf] = TimeframeData(
        tf=tf,
        time=[datetime.datetime.fromisoformat(t) for t in d['time']],
        open=d['open'], high=d['high'], low=d['low'], close=d['close'],
        tick_volume=d['tick_volume'], spread=d['spread']
    )

hierarchy = TimeframeHierarchy(bias_det, zone_det, sideways_detector=sideways_det, session_agnostic=True)
from xauusd_bot.models import Session
h_res = hierarchy.evaluate(data_all, Session.LONDON)

print("XAUUSD Hierarchy State Today:")
for k, v in h_res.items():
    print(f"  {k}: {v}")

# Check why no FVG or MSS today in XAUUSD backtest
from xauusd_bot.backtesting.engine import BacktestEngine
engine = BacktestEngine(cfg, initial_balance=99488.20, symbol='XAUUSD', start_date=today_start_dt)
engine.run(raw_xau)
print(f"\nXAUUSD Ablation Counters: {dict(engine._ablation_counters)}")

mt5.shutdown()
