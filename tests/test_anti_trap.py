from xauusd_bot.strategy.trigger import TriggerDetector
from xauusd_bot.models import TimeframeData, TradeDirection


def _get_m15_data():
    m15_highs = [2010.0, 2012.0, 2020.0, 2015.0, 2014.0, 2008.0]
    m15_lows = [2005.0, 2006.0, 2010.0, 2004.0, 2002.0, 2000.0]
    m15_closes = [2008.0, 2010.0, 2018.0, 2006.0, 2003.0, 2001.0]
    return TimeframeData(
        tf="M15", time=[], open=m15_closes, high=m15_highs, low=m15_lows, close=m15_closes,
        tick_volume=[100]*6, spread=[1]*6
    )


def test_trend_bias_blocks_counter_trend_sweeps():
    """
    Test Asymmetric Trend-Aligned Liquidity Scanning:
    - In Bearish trend, counter-trend SSL sweeps must NOT trigger BUY.
    - In Bullish trend, counter-trend BSL sweeps must NOT trigger SELL.
    """
    td = TriggerDetector()
    m15_data = _get_m15_data()

    # 1. Bullish SSL sweep dataset
    m1_opens_buy  = [2004.0, 2003.5, 2002.0, 2001.5, 2001.0, 2001.0, 2006.0]
    m1_highs_buy  = [2004.5, 2004.0, 2002.5, 2002.0, 2002.5, 2006.5, 2008.0]
    m1_lows_buy   = [2003.0, 2002.0, 2001.0, 2000.5, 1998.0, 2001.0, 2004.5]
    m1_closes_buy = [2003.5, 2002.5, 2001.5, 2001.0, 2001.0, 2006.0, 2007.5]
    m1_data_buy = TimeframeData(
        tf="M1", time=[], open=m1_opens_buy, high=m1_highs_buy, low=m1_lows_buy, close=m1_closes_buy,
        tick_volume=[100]*7, spread=[1]*7
    )

    # When trend is BULLISH: BUY is permitted
    seq_buy_allowed = td.detect_xau_scalp_sequence(
        m15_data=m15_data, m1_data=m1_data_buy, m1_atr=1.5, lookback_m15=6, sequence_window_m1=5,
        target_r=2.0, trend_bias=TradeDirection.BUY, enable_anti_trap=False
    )
    assert seq_buy_allowed is not None
    assert seq_buy_allowed["direction"] == TradeDirection.BUY

    # When trend is BEARISH: BUY is STRICTLY BLOCKED
    seq_buy_blocked = td.detect_xau_scalp_sequence(
        m15_data=m15_data, m1_data=m1_data_buy, m1_atr=1.5, lookback_m15=6, sequence_window_m1=5,
        target_r=2.0, trend_bias=TradeDirection.SELL, enable_anti_trap=False
    )
    assert seq_buy_blocked is None

    # 2. Bearish BSL sweep dataset
    m1_opens_sell  = [2016.0, 2016.5, 2018.0, 2018.5, 2019.0, 2019.0, 2014.0]
    m1_highs_sell  = [2017.0, 2018.0, 2019.5, 2019.5, 2022.0, 2019.0, 2015.5]
    m1_lows_sell   = [2015.5, 2016.0, 2017.5, 2018.0, 2018.0, 2013.5, 2012.0]
    m1_closes_sell = [2016.5, 2017.5, 2018.5, 2019.0, 2019.0, 2014.0, 2012.5]
    m1_data_sell = TimeframeData(
        tf="M1", time=[], open=m1_opens_sell, high=m1_highs_sell, low=m1_lows_sell, close=m1_closes_sell,
        tick_volume=[100]*7, spread=[1]*7
    )

    # When trend is BEARISH: SELL is permitted
    seq_sell_allowed = td.detect_xau_scalp_sequence(
        m15_data=m15_data, m1_data=m1_data_sell, m1_atr=1.5, lookback_m15=6, sequence_window_m1=5,
        target_r=2.0, trend_bias=TradeDirection.SELL, enable_anti_trap=False
    )
    assert seq_sell_allowed is not None
    assert seq_sell_allowed["direction"] == TradeDirection.SELL

    # When trend is BULLISH: SELL is STRICTLY BLOCKED
    seq_sell_blocked = td.detect_xau_scalp_sequence(
        m15_data=m15_data, m1_data=m1_data_sell, m1_atr=1.5, lookback_m15=6, sequence_window_m1=5,
        target_r=2.0, trend_bias=TradeDirection.BUY, enable_anti_trap=False
    )
    assert seq_sell_blocked is None


def test_anti_trap_inversion_short():
    """
    Test Anti-Trap Inducement Inversion:
    In a BEARISH macro trend, when a counter-trend bullish bounce creates an M1 FVG
    and then subsequent candles break down below that FVG low (trap failure),
    the trigger enters a high-conviction SELL in the macro direction.
    """
    td = TriggerDetector()
    m15_data = _get_m15_data()

    # Candles 0-3: Market drops below 2000.0 SSL
    # Candle 4: Bullish candle creating FVG low=2002.0
    # Candle 5: Gap up
    # Candle 6: Massive drop breaking down below 2002.0 (Inversion Breakdown)
    m1_opens  = [2004.0, 2002.0, 2001.0, 1999.0, 2000.0, 2004.0, 2003.0]
    m1_highs  = [2004.5, 2002.5, 2001.5, 2000.0, 2003.5, 2006.0, 2003.5]
    m1_lows   = [2002.0, 2000.5, 1998.0, 1998.0, 2000.0, 2003.0, 1996.0]
    m1_closes = [2002.5, 2001.0, 1998.5, 1999.5, 2003.0, 2005.0, 1997.0]

    # Candle 3 high is 2000.0, Candle 5 low is 2003.0 -> Bullish FVG [2000.0, 2003.0]
    # Candle 6 closes at 1997.0, which is below 2000.0 -> Breakdown!
    m1_data = TimeframeData(
        tf="M1", time=[], open=m1_opens, high=m1_highs, low=m1_lows, close=m1_closes,
        tick_volume=[100]*7, spread=[1]*7
    )

    seq = td.detect_xau_scalp_sequence(
        m15_data=m15_data,
        m1_data=m1_data,
        m1_atr=1.5,
        lookback_m15=6,
        sequence_window_m1=5,
        target_r=2.0,
        trend_bias=TradeDirection.SELL,
        enable_anti_trap=True,
    )

    assert seq is not None
    assert seq["direction"] == TradeDirection.SELL
    assert seq["anti_trap_inversion"] is True
    assert seq["entry_price"] == 1997.0
    assert seq["sl_price"] > seq["entry_price"]
    assert seq["tp_price"] < seq["entry_price"]
