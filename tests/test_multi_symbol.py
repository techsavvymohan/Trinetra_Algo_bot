from unittest.mock import MagicMock
import os
import pytest

from xauusd_bot.config import Config, TradingConfig
from xauusd_bot.models import (
    AccountInfo, Bias, PyraCluster, Regime, Session, Signal, SignalGrade,
    TradeDirection, TradeLeg, TradeStatus,
)
from xauusd_bot.risk.position_sizer import PositionSizer
from xauusd_bot.trade.cluster import ClusterManager
from xauusd_bot.filters.session_filter import SessionFilter
from xauusd_bot.broker.account import AccountManager


def test_config_multi_symbol_parsing():
    os.environ["SYMBOLS"] = "XAUUSD, USTECH100M"
    tc = TradingConfig.from_env()
    assert "XAUUSD" in tc.symbols
    assert "USTECH100M" in tc.symbols
    assert tc.enable_session_filter is False
    assert tc.enable_sideways_filter is True
    del os.environ["SYMBOLS"]


def test_multi_symbol_position_sizing():
    sizer = PositionSizer(initial_risk_pct=1.0)
    account = AccountInfo(balance=10000.0, equity=10000.0)

    # 1. XAUUSD: Risk 10 dollars ($2700 - $2690)
    # tick_size = 0.01, tick_value = $1.0 (per 1.0 lot)
    # 10.0 / 0.01 = 1000 ticks * $1 = $1000 risk per 1 lot.
    # Risk budget = 1% of 10000 = $100.
    # Expected lot = 100 / 1000 = 0.10 lot
    lot_gold = sizer.calculate_lot_size(
        account=account,
        entry_price=2700.0,
        sl_price=2690.0,
        direction=TradeDirection.BUY,
        point_value=1.0,
        tick_size=0.01,
    )
    assert lot_gold == 0.10

    # 2. USTECH100M: Risk 20 points (19500 - 19480 = 20.0 pts)
    # tick_size = 0.1, point_value = 0.1 (per 1.0 lot)
    # 20.0 / 0.1 = 200 ticks * $0.1 = $20 risk per 1 lot.
    # Risk budget = 1% of 10000 = $100.
    # Expected lot = 100 / 20 = 5.0 lots
    lot_nas = sizer.calculate_lot_size(
        account=account,
        entry_price=19500.0,
        sl_price=19480.0,
        direction=TradeDirection.BUY,
        point_value=0.1,
        tick_size=0.1,
    )
    assert lot_nas == 5.0


def test_cluster_manager_multi_symbol():
    cm = ClusterManager()

    c_gold = PyraCluster(signal_id="sig1", symbol="XAUUSD", direction=TradeDirection.BUY)
    leg_gold = TradeLeg(position_ticket=101, symbol="XAUUSD", lot_size=0.1, status=TradeStatus.OPEN)
    c_gold.legs.append(leg_gold)

    c_nas = PyraCluster(signal_id="sig2", symbol="USTECH100M", direction=TradeDirection.BUY)
    leg_nas = TradeLeg(position_ticket=102, symbol="USTECH100M", lot_size=0.5, status=TradeStatus.OPEN)
    c_nas.legs.append(leg_nas)

    cm.add(c_gold)
    cm.add(c_nas)

    assert cm.has_active_for_direction(TradeDirection.BUY, symbol="XAUUSD")
    assert cm.has_active_for_direction(TradeDirection.BUY, symbol="USTECH100M")
    assert not cm.has_active_for_direction(TradeDirection.SELL, symbol="XAUUSD")

    gold_clusters = cm.active_clusters_for_symbol("XAUUSD")
    assert len(gold_clusters) == 1
    assert gold_clusters[0].symbol == "XAUUSD"

    nas_clusters = cm.active_clusters_for_symbol("USTECH100M")
    assert len(nas_clusters) == 1
    assert nas_clusters[0].symbol == "USTECH100M"

    assert cm.total_open_lots("XAUUSD") == 0.1
    assert cm.total_open_lots("USTECH100M") == 0.5
    assert cm.total_open_lots() == 0.6


def test_session_freedom_no_restrictions():
    # When enabled=False (no restrictions), all sessions and timezones are allowed
    sf = SessionFilter(enabled=False)
    ok, msg = sf.check()
    assert ok
    assert msg == "all_sessions_allowed"

    tfs = sf.allowed_entry_tfs()
    assert "M1" in tfs
    assert "M5" in tfs
    assert "M15" in tfs
    assert "M30" in tfs


def test_signal_symbol_support():
    sig = Signal(symbol="USTECH100M", direction=TradeDirection.BUY, grade=SignalGrade.A)
    assert sig.symbol == "USTECH100M"
    assert sig.is_tradeable()

    # Blocked by sideways
    sig.sideways_blocked = True
    assert sig.blocked()
    assert not sig.is_tradeable()


def test_nas100_scalp_sequence_stop_calculation():
    from xauusd_bot.strategy.trigger import TriggerDetector
    from xauusd_bot.models import TimeframeData

    engine = TriggerDetector()

    # Synthetic Nasdaq 100 data (price ~ 19500)
    n = 30
    times = [1705300000 + i * 60 for i in range(n)]
    highs = [19510.0] * (n - 6) + [19515.0, 19512.0, 19510.0, 19508.0, 19506.0, 19504.0]
    lows = [19490.0] * (n - 6) + [19495.0, 19496.0, 19494.0, 19492.0, 19490.0, 19488.0]
    closes = [19500.0] * (n - 6) + [19514.0, 19510.0, 19508.0, 19505.0, 19502.0, 19500.0]
    opens = [19495.0] * (n - 6) + [19498.0, 19514.0, 19510.0, 19508.0, 19505.0, 19502.0]
    volumes = [100.0] * n

    m1_data = TimeframeData("M1", times, opens, highs, lows, closes, volumes, [1.0] * n)
    m15_data = TimeframeData("M15", times, opens, highs, lows, closes, volumes, [1.0] * n)

    seq = engine.detect_xau_scalp_sequence(
        m15_data=m15_data,
        m1_data=m1_data,
        m1_atr=3.0,
        point_value=0.1,
        stops_level_points=10.0,
        target_r=2.0,
        min_sl_distance=5.0,
    )
    if seq:
        assert seq["entry_price"] > 10000.0
        assert seq["sl_price"] > 10000.0
        assert seq["tp_price"] > 0.0


def test_pending_cluster_immune_to_manage_exits():
    from xauusd_bot.trade.trade_manager import TradeManager
    from xauusd_bot.order.entry import OrderEntry
    from xauusd_bot.order.exit import ExitManager
    from xauusd_bot.order.partial_close import PartialCloseManager
    from xauusd_bot.risk.position_sizer import PositionSizer
    from xauusd_bot.risk.daily_loss import DailyLossTracker
    from xauusd_bot.risk.max_dd import MaxDDTracker
    from xauusd_bot.risk.pyramid_manager import PyramidManager
    from xauusd_bot.models import TimeframeData

    conn = MagicMock()
    conn.ensure_connected.return_value = True
    cfg = TradingConfig()
    order_entry = OrderEntry(conn, cfg)
    exit_mgr = ExitManager(cfg)
    trade_mgr = TradeManager(
        order_entry=order_entry,
        exit_mgr=exit_mgr,
        partial_close=PartialCloseManager(),
        pyramid_mgr=PyramidManager(cfg),
        sizer=PositionSizer(),
        daily_loss=DailyLossTracker(),
        max_dd=MaxDDTracker(5.0, 1.0),
    )

    cluster = PyraCluster(signal_id="sig_test", symbol="XAUUSD", direction=TradeDirection.SELL)
    leg = TradeLeg(position_ticket=12345, symbol="XAUUSD", lot_size=0.03, status=TradeStatus.PENDING)
    cluster.legs.append(leg)
    cluster.status = TradeStatus.PENDING

    # Data with PSAR suggesting reversal
    n = 20
    times = list(range(n))
    highs = [4330.0 + i * 0.5 for i in range(n)]
    lows = [4328.0 + i * 0.5 for i in range(n)]
    closes = [4329.0 + i * 0.5 for i in range(n)]
    data_all = {"M1": TimeframeData("M1", times, closes, highs, lows, closes, [100.0] * n, [1.0] * n)}

    actions = trade_mgr.manage_exits(cluster, data_all)
    # Pending cluster must NEVER be exited or cancelled by manage_exits
    assert actions == []
    assert cluster.status == TradeStatus.PENDING
    assert leg.status == TradeStatus.PENDING
    conn.order_send.assert_not_called()


def test_broker_spec_stops_validation():
    from xauusd_bot.order.entry import OrderEntry
    conn = MagicMock()
    conn.symbol_info.return_value = None
    entry = OrderEntry(conn, TradingConfig())

    # 1. Invalid Negative TP
    ok, msg = entry.validate_broker_spec("USTECH100M", 19500.0, 19550.0, tp_price=-30.85, direction=TradeDirection.SELL)
    assert not ok
    assert "Invalid TP price" in msg

    # 2. Invalid Stop side: SELL with SL below entry
    ok, msg = entry.validate_broker_spec("USTECH100M", 19500.0, 19450.0, tp_price=19400.0, direction=TradeDirection.SELL)
    assert not ok
    assert "Invalid SELL stop" in msg

    # 3. Valid normal USTECH100M order
    ok, msg = entry.validate_broker_spec("USTECH100M", 19500.0, 19550.0, tp_price=19400.0, direction=TradeDirection.SELL)
    assert ok

