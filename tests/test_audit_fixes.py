from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import pytest

from xauusd_bot.config import Config, TradingConfig, MT5Config
from xauusd_bot.models import AccountInfo, Signal, TradeDirection, TradeStatus, PyraCluster
from xauusd_bot.order.entry import OrderEntry
from xauusd_bot.broker.mt5_connector import MT5Connector
from xauusd_bot.risk.daily_loss import DailyLossTracker
from xauusd_bot.trade.cluster import ClusterManager
from xauusd_bot.risk.pyramid_manager import PyramidManager


def test_place_market_order_custom_comment():
    """Verify place_market_order natively accepts and routes custom comments."""
    connector = MagicMock()
    connector.ensure_connected.return_value = True
    connector.symbol_info_tick.return_value = MagicMock(ask=2650.0, bid=2649.5)
    connector.symbol_info.return_value = MagicMock(
        point=0.01,
        trade_stops_level=0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        filling_mode=2,
    )
    connector.order_send.return_value = MagicMock(price=2650.0, order=123456)

    cfg = TradingConfig()
    entry = OrderEntry(connector, cfg)

    sig = Signal(
        id="sig_moc_test",
        direction=TradeDirection.BUY,
        entry_price=2650.0,
        sl_price=2640.0,
        tp_price=2670.0,
        lot_size=0.10,
        symbol="XAUUSD",
    )
    acc = AccountInfo(balance=10000.0, equity=10000.0, margin=0.0, margin_free=10000.0, margin_level=0.0, leverage=100)

    leg = entry.place_market_order(
        signal=sig,
        account=acc,
        point_value=1.0,
        contract_size=100,
        comment="FVG_MoC",
    )

    assert leg is not None
    assert leg.position_ticket == 123456
    sent_request = connector.order_send.call_args[0][0]
    assert sent_request["comment"] == "FVG_MoC"


def test_modify_sl_tp_with_symbol():
    """Verify modify_sl_tp passes symbol in request for strict broker bridges."""
    connector = MagicMock()
    connector.order_send.return_value = MagicMock(retcode=10009)

    cfg = TradingConfig()
    entry = OrderEntry(connector, cfg)

    ok = entry.modify_sl_tp(ticket=98765, sl=2652.0, tp=2680.0, symbol="XAUUSD")
    assert ok is True
    sent_request = connector.order_send.call_args[0][0]
    assert sent_request["position"] == 98765
    assert sent_request["sl"] == 2652.0
    assert sent_request["tp"] == 2680.0
    assert sent_request["symbol"] == "XAUUSD"


def test_mt5_connector_acceptable_retcodes():
    """Verify order_send accepts 10008 (PLACED), 10009 (DONE), 10010 (PARTIAL), and 10025 (NO_CHANGES)."""
    cfg = MT5Config()
    connector = MT5Connector(cfg)

    with patch("xauusd_bot.broker.mt5_connector.mt5") as mock_mt5:
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.TRADE_RETCODE_PLACED = 10008
        mock_mt5.TRADE_RETCODE_DONE_PARTIAL = 10010
        mock_mt5.TRADE_RETCODE_NO_CHANGES = 10025

        # Retcode 10008 (Pending limit order placed) -> should succeed
        mock_mt5.order_send.return_value = MagicMock(retcode=10008, order=777)
        res_placed = connector.order_send({"action": 5})
        assert res_placed is not None
        assert res_placed.retcode == 10008

        # Retcode 10025 (No changes on modify) -> should succeed
        mock_mt5.order_send.return_value = MagicMock(retcode=10025, order=777)
        res_no_chg = connector.order_send({"action": 6})
        assert res_no_chg is not None
        assert res_no_chg.retcode == 10025

        # Retcode 10013 (Invalid params) -> should fail
        mock_mt5.order_send.return_value = MagicMock(retcode=10013, comment="Invalid params")
        res_fail = connector.order_send({"action": 1})
        assert res_fail is None


def test_mt5_connector_orders_get():
    """Verify orders_get queries MT5 pending orders."""
    cfg = MT5Config()
    connector = MT5Connector(cfg)

    with patch("xauusd_bot.broker.mt5_connector.mt5") as mock_mt5:
        dummy_order = MagicMock(ticket=55555, symbol="XAUUSD", type=2)
        mock_mt5.orders_get.return_value = [dummy_order]

        orders = connector.orders_get(symbol="XAUUSD", magic=123)
        mock_mt5.orders_get.assert_called_once_with(symbol="XAUUSD", magic=123)
        assert len(orders) == 1
        assert orders[0].ticket == 55555


def test_daily_loss_calibration_from_balance():
    """Verify daily loss calibration uses balance - closed deals PnL (ignoring floating PnL)."""
    tracker = DailyLossTracker(daily_limit_pct=5.0, buffer_pct=0.5)

    connector = MagicMock()
    # Deal closed today with +$200 profit
    deal = MagicMock(entry=1, profit=200.0, swap=0.0, commission=0.0)
    connector.history_deals_get.return_value = [deal]

    # Current balance is $10,200, current floating equity is $9,900 (-$300 floating loss)
    account = AccountInfo(
        balance=10200.0,
        equity=9900.0,
        margin=100.0,
        margin_free=9800.0,
        margin_level=9900.0,
        leverage=100,
    )

    tracker.calibrate_from_broker(connector, account)
    # start_equity must equal 10,200 - 200 = $10,000.00
    assert tracker.state.start_equity == 10000.0
    # daily_pnl must equal current equity ($9,900) - start_equity ($10,000) = -$100.00
    assert tracker.state.daily_pnl == -100.0


def test_startup_reconcile_broker_positions():
    """Verify _reconcile_broker_positions imports existing MT5 positions into cluster manager."""
    from xauusd_bot.main import XAUUSDBot

    bot = XAUUSDBot.__new__(XAUUSDBot)
    bot.cfg = Config()
    bot.symbols = ["XAUUSD"]
    bot.cluster_mgr = ClusterManager()
    bot.pyramid_mgr = PyramidManager(3, 1.0)

    dummy_pos = MagicMock(
        ticket=123999,
        symbol="XAUUSD",
        magic=bot.cfg.trading.magic_number,
        type=0,  # BUY
        volume=0.25,
        price_open=2655.50,
        sl=2645.0,
        tp=2675.0,
        time=int(datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc).timestamp()),
    )
    connector = MagicMock()
    connector.positions_get.return_value = [dummy_pos]
    bot.connector = connector

    # Initially empty
    assert len(bot.cluster_mgr.active_clusters_for_symbol("XAUUSD")) == 0

    # Run reconciliation
    bot._reconcile_broker_positions()

    active = bot.cluster_mgr.active_clusters_for_symbol("XAUUSD")
    assert len(active) == 1
    cluster = active[0]
    assert cluster.symbol == "XAUUSD"
    assert cluster.status == TradeStatus.OPEN
    assert cluster.legs[0].position_ticket == 123999
    assert cluster.legs[0].lot_size == 0.25
    assert cluster.legs[0].entry_price == 2655.50
    assert cluster.collective_sl == 2645.0
    assert cluster.target_tp == 2675.0


def test_cluster_manager_remove():
    """Verify ClusterManager.remove removes a cluster without error."""
    cm = ClusterManager()
    cluster = PyraCluster(cluster_id="test_c1", symbol="XAUUSD", direction=TradeDirection.BUY)
    cm.add(cluster)
    assert len(cm.all_clusters) == 1
    cm.remove(cluster)
    assert len(cm.all_clusters) == 0
    # Removing a non-existent cluster should not error
    cm.remove(cluster)


def test_daily_loss_tracker_reset():
    """Verify DailyLossTracker.reset resets state to None for account switches."""
    tracker = DailyLossTracker()
    tracker.state = MagicMock()
    assert tracker.state is not None
    tracker.reset()
    assert tracker.state is None


def test_position_sizer_inverted_sl_returns_zero():
    """Verify PositionSizer returns 0.0 to reject trades with inverted SL."""
    from xauusd_bot.risk.position_sizer import PositionSizer
    sizer = PositionSizer()
    acc = AccountInfo(balance=10000.0, equity=10000.0)
    # BUY with SL above entry
    lot_buy = sizer.calculate_lot_size(
        account=acc, entry_price=2000.0, sl_price=2010.0,
        direction=TradeDirection.BUY, point_value=1.0,
    )
    assert lot_buy == 0.0

    # SELL with SL below entry
    lot_sell = sizer.calculate_lot_size(
        account=acc, entry_price=2000.0, sl_price=1990.0,
        direction=TradeDirection.SELL, point_value=1.0,
    )
    assert lot_sell == 0.0


def test_live_stagnation_exit_in_trade_manager():
    """Verify TradeManager.manage_exits calls stagnation exit when trade stalls."""
    from xauusd_bot.trade.trade_manager import TradeManager
    from xauusd_bot.order.exit import ExitManager
    from xauusd_bot.models import PyraCluster, TradeLeg, TradeDirection, TradeStatus, ExitReason, TimeframeData

    cfg = MagicMock()
    cfg.xau_stagnation_exit_enabled = True
    cfg.xau_stagnation_bars = 20
    cfg.xau_stagnation_min_r = 0.30
    cfg.xau_breakeven_ratchet_enabled = False
    cfg.xau_partial_close_enabled = False
    cfg.strategy_trigger_type = "xau_liquidity_sweep_fvg_m1"

    order_entry = MagicMock()
    order_entry.close_position.return_value = True
    exit_mgr = ExitManager(cfg)
    exit_mgr.check_stagnation_exit = MagicMock(return_value=True)

    tm = TradeManager(
        order_entry=order_entry,
        exit_mgr=exit_mgr,
        partial_close=MagicMock(),
        pyramid_mgr=MagicMock(),
        sizer=MagicMock(),
        daily_loss=MagicMock(),
        max_dd=MagicMock(),
    )

    cluster = PyraCluster(cluster_id="stag_cluster", symbol="XAUUSD", direction=TradeDirection.BUY)
    cluster.status = TradeStatus.OPEN
    cluster.open_time = datetime(2026, 9, 20, 10, 0)
    leg = TradeLeg(position_ticket=888, direction=TradeDirection.BUY, entry_price=2650.0, lot_size=0.10, status=TradeStatus.OPEN)
    cluster.legs.append(leg)

    m1_data = TimeframeData("M1", [datetime.now()], [2650.0], [2652.0], [2649.0], [2650.5], [100], [10])
    actions = tm.manage_exits(cluster, {"M1": m1_data})

    assert any(a.get("action") == "stagnation_exit" for a in actions)
    assert cluster.status == TradeStatus.CLOSED
    assert leg.exit_reason == ExitReason.STAGNATION
    assert order_entry.close_position.called


def test_live_runner_trailing_stop_sync():
    """Verify runner leg trails and synchronizes stop-loss to MT5."""
    from xauusd_bot.trade.trade_manager import TradeManager
    from xauusd_bot.order.exit import ExitManager
    from xauusd_bot.models import PyraCluster, TradeLeg, TradeDirection, TradeStatus, ExitReason, TimeframeData

    cfg = MagicMock()
    cfg.xau_stagnation_exit_enabled = False
    cfg.xau_breakeven_ratchet_enabled = False
    cfg.xau_partial_close_enabled = False
    cfg.strategy_trigger_type = "xau_liquidity_sweep_fvg_m1"
    cfg.runner_trail_atr_mult = 3.0

    order_entry = MagicMock()
    order_entry.modify_sl_tp.return_value = True
    order_entry.close_position.return_value = True

    exit_mgr = ExitManager(cfg)
    exit_mgr.check_chandelier_exit = MagicMock(return_value=2665.0)

    tm = TradeManager(
        order_entry=order_entry,
        exit_mgr=exit_mgr,
        partial_close=MagicMock(),
        pyramid_mgr=MagicMock(),
        sizer=MagicMock(),
        daily_loss=MagicMock(),
        max_dd=MagicMock(),
    )

    cluster = PyraCluster(cluster_id="runner_cluster", symbol="XAUUSD", direction=TradeDirection.BUY)
    cluster.status = TradeStatus.OPEN
    cluster.highest_price = 2670.0
    cluster.fvg_low = 2640.0
    cluster.fvg_high = 2645.0
    runner_leg = TradeLeg(position_ticket=999, direction=TradeDirection.BUY, entry_price=2650.0, lot_size=0.05, sl_price=2650.0, status=TradeStatus.OPEN)
    runner_leg._is_runner = True
    cluster.legs.append(runner_leg)

    # Current price above trail stop (2668.0 > 2665.0): should modify SL to 2665.0, not close
    m1_data = TimeframeData("M1", [datetime.now()] * 30, [2668.0] * 30, [2670.0] * 30, [2666.0] * 30, [2668.0] * 30, [100] * 30, [10] * 30)
    actions = tm.manage_exits(cluster, {"M1": m1_data})
    assert runner_leg.sl_price == 2665.0
    order_entry.modify_sl_tp.assert_called_with(999, 2665.0, runner_leg.tp_price, symbol="XAUUSD")
    assert runner_leg.status == TradeStatus.OPEN
