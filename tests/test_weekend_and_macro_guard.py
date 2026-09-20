"""Unit tests for Friday Weekend Guard and Macro Trend Bias Guard."""

from datetime import datetime, timezone
import pytest

from xauusd_bot.models import ExitReason, TradeDirection, TimeframeData
from xauusd_bot.filters.session_filter import is_friday_weekend_close
from xauusd_bot.strategy.trigger import evaluate_h4_macro_bias
from xauusd_bot.config import Config


def test_exit_reason_weekend_close():
    """Verify ExitReason enum has WEEKEND_CLOSE with proper value."""
    assert hasattr(ExitReason, "WEEKEND_CLOSE")
    assert ExitReason.WEEKEND_CLOSE == ExitReason("weekend_close")
    assert ExitReason.WEEKEND_CLOSE.value == "weekend_close"


def test_is_friday_weekend_close_timings():
    """Verify Friday cutoff and weekend closure boundaries."""
    cutoff_h = 20
    cutoff_m = 45

    # Friday before cutoff (20:44 UTC) -> False
    fri_before = datetime(2026, 9, 18, 20, 44, 0, tzinfo=timezone.utc)
    assert not is_friday_weekend_close(fri_before, cutoff_h, cutoff_m)

    # Friday at cutoff (20:45 UTC) -> True
    fri_cutoff = datetime(2026, 9, 18, 20, 45, 0, tzinfo=timezone.utc)
    assert is_friday_weekend_close(fri_cutoff, cutoff_h, cutoff_m)

    # Friday late evening (22:30 UTC) -> True
    fri_late = datetime(2026, 9, 18, 22, 30, 0, tzinfo=timezone.utc)
    assert is_friday_weekend_close(fri_late, cutoff_h, cutoff_m)

    # Saturday anytime -> True
    sat = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert is_friday_weekend_close(sat, cutoff_h, cutoff_m)

    # Sunday before market open (18:00 UTC) -> True
    sun_early = datetime(2026, 9, 20, 18, 0, 0, tzinfo=timezone.utc)
    assert is_friday_weekend_close(sun_early, cutoff_h, cutoff_m)

    # Sunday after market open (22:05 UTC) -> False
    sun_open = datetime(2026, 9, 20, 22, 5, 0, tzinfo=timezone.utc)
    assert not is_friday_weekend_close(sun_open, cutoff_h, cutoff_m)

    # Regular weekday (Wednesday 14:00 UTC) -> False
    wed = datetime(2026, 9, 16, 14, 0, 0, tzinfo=timezone.utc)
    assert not is_friday_weekend_close(wed, cutoff_h, cutoff_m)


def test_evaluate_h4_macro_bias():
    """Verify H4 macro trend evaluation logic."""
    # Insufficient data
    empty_h4 = TimeframeData(
        tf="H4", time=[], open=[], high=[], low=[], close=[], tick_volume=[], spread=[]
    )
    veto, reason = evaluate_h4_macro_bias(empty_h4, TradeDirection.BUY)
    assert not veto
    assert reason == "insufficient_h4_data"

    # Bullish trend (rising closes)
    bullish_closes = [2000.0 + i * 2.0 for i in range(60)]
    bull_h4 = TimeframeData(
        tf="H4",
        time=[datetime.now(timezone.utc)] * 60,
        open=bullish_closes,
        high=[c + 1.0 for c in bullish_closes],
        low=[c - 1.0 for c in bullish_closes],
        close=bullish_closes,
        tick_volume=[100] * 60,
        spread=[10] * 60,
    )

    # Bullish trend permits BUY
    veto_buy, reason_buy = evaluate_h4_macro_bias(bull_h4, TradeDirection.BUY)
    assert not veto_buy
    assert reason_buy == "aligned"

    # Bullish trend vetos SELL
    veto_sell, reason_sell = evaluate_h4_macro_bias(bull_h4, TradeDirection.SELL)
    assert veto_sell
    assert "BULLISH H4 vetos SELL" in reason_sell

    # Bearish trend (falling closes)
    bearish_closes = [2200.0 - i * 2.0 for i in range(60)]
    bear_h4 = TimeframeData(
        tf="H4",
        time=[datetime.now(timezone.utc)] * 60,
        open=bearish_closes,
        high=[c + 1.0 for c in bearish_closes],
        low=[c - 1.0 for c in bearish_closes],
        close=bearish_closes,
        tick_volume=[100] * 60,
        spread=[10] * 60,
    )

    # Bearish trend permits SELL
    veto_sell_bear, reason_sell_bear = evaluate_h4_macro_bias(bear_h4, TradeDirection.SELL)
    assert not veto_sell_bear
    assert reason_sell_bear == "aligned"

    # Bearish trend vetos BUY
    veto_buy_bear, reason_buy_bear = evaluate_h4_macro_bias(bear_h4, TradeDirection.BUY)
    assert veto_buy_bear
    assert "BEARISH H4 vetos BUY" in reason_buy_bear


def test_optimal_config_defaults():
    """Verify optimal production settings loaded from config."""
    cfg = Config.load()
    tc = cfg.trading

    # 1. XAU_H4_BIAS_GUARD = False (scalp freely for full profits)
    assert getattr(tc, "xau_h4_bias_guard", None) is False

    # 2. Nasdaq 100 active US cash session configuration
    assert getattr(tc, "nas_session_start_hour", None) == 13
    assert getattr(tc, "nas_session_end_hour", None) == 20

    # 3. FRIDAY_WEEKEND_GUARD = True (auto-flat Friday 20:45 UTC)
    assert getattr(tc, "friday_weekend_guard", None) is True
    assert getattr(tc, "friday_close_cutoff_hour", None) == 20
    assert getattr(tc, "friday_close_cutoff_min", None) == 45


def test_backtest_friday_weekend_guard_exit():
    """Verify that BacktestEngine auto-flat closes positions on Friday weekend close."""
    from xauusd_bot.backtesting.engine import BacktestEngine
    from xauusd_bot.models import PyraCluster, TradeLeg, TradeStatus

    cfg = Config.load()
    engine = BacktestEngine(cfg)

    # Friday 20:50 UTC (after 20:45 cutoff)
    fri_close_time = datetime(2026, 9, 18, 20, 50, 0, tzinfo=timezone.utc)
    m1_data = TimeframeData(
        tf="M1",
        time=[fri_close_time],
        open=[2650.0],
        high=[2652.0],
        low=[2649.0],
        close=[2651.0],
        tick_volume=[10],
        spread=[20],
    )
    data_all = {"M1": m1_data}

    cluster = PyraCluster(
        signal_id="sig_test_fw",
        direction=TradeDirection.BUY,
        entry_tf="M1",
        symbol="XAUUSD",
        collective_sl=2640.0,
        open_time=fri_close_time,
        status=TradeStatus.OPEN,
    )
    leg = TradeLeg(
        direction=TradeDirection.BUY,
        entry_price=2650.0,
        lot_size=0.10,
        symbol="XAUUSD",
        sl_price=2640.0,
        tp_price=2670.0,
        open_time=fri_close_time,
        status=TradeStatus.OPEN,
    )
    cluster.legs.append(leg)

    actions = engine._manage_backtest_exits(cluster, data_all, 0, 2651.0)
    assert cluster.status == TradeStatus.CLOSED
    assert leg.status == TradeStatus.CLOSED
    assert leg.exit_reason == ExitReason.WEEKEND_CLOSE
    assert any(a["action"] == "weekend_close" for a in actions)

