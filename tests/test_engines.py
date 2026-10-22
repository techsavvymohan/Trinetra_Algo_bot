import threading
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from xauusd_bot.config import Config
from xauusd_bot.engines import (
    BaseSymbolEngine, XauusdEngine, Nas100Engine, MultiEngineCoordinator,
)
from xauusd_bot.models import (
    AccountInfo, ExitReason, PyraCluster, Signal, SignalGrade,
    TimeframeData, TradeDirection, TradeLeg, TradeStatus,
)
from xauusd_bot.trade.cluster import ClusterManager


@pytest.fixture
def base_components():
    cfg = Config()
    cfg.trading.symbols = ["XAUUSD", "USTECH100M"]

    connector = MagicMock()
    connector.lock = threading.RLock()
    connector.ensure_connected.return_value = True
    connector.connect.return_value = True
    connector.resolve_broker_symbol.side_effect = lambda s: s
    connector.positions_get.return_value = []
    connector.history_deals_get.return_value = []

    account = MagicMock()
    account.refresh.return_value = AccountInfo(balance=10000.0, equity=10000.0)
    account.current_spread.return_value = 1.0
    account.point_value.return_value = 1.0
    account.point_size.return_value = 0.01
    account.contract_size.return_value = 100.0
    account.min_lot.return_value = 0.01
    account.lot_step.return_value = 0.01
    account.max_lot.return_value = 100.0

    data_feed = MagicMock()
    m1_tf = TimeframeData(
        tf="M1",
        time=[1000 + i * 60 for i in range(30)],
        open=[2700.0] * 30,
        high=[2705.0] * 30,
        low=[2695.0] * 30,
        close=[2700.0] * 30,
        tick_volume=[100] * 30,
        spread=[10] * 30,
    )
    m15_tf = TimeframeData(
        tf="M15",
        time=[1000 + i * 900 for i in range(30)],
        open=[2700.0] * 30,
        high=[2710.0] * 30,
        low=[2690.0] * 30,
        close=[2700.0] * 30,
        tick_volume=[500] * 30,
        spread=[10] * 30,
    )
    data_feed.all_tfs.return_value = {"M1": m1_tf, "M15": m15_tf}

    spread_tracker = MagicMock()
    spread_filter = MagicMock()
    spread_filter.is_spread_acceptable.return_value = True

    news_filter = MagicMock()
    news_filter.check.return_value = (True, "No news")

    trigger = MagicMock()
    trigger.detect_xau_scalp_sequence.return_value = None

    trade_mgr = MagicMock()
    cluster_mgr = ClusterManager()
    persistence = MagicMock()

    daily_loss = MagicMock()
    daily_loss.kill_switch_engaged.return_value = False
    daily_loss.state = MagicMock()

    max_dd = MagicMock()
    max_dd.kill_switch_engaged.return_value = False

    sizer = MagicMock()
    sizer.initial_balance = 10000.0

    return {
        "cfg": cfg,
        "connector": connector,
        "account": account,
        "data_feed": data_feed,
        "spread_tracker": spread_tracker,
        "spread_filter": spread_filter,
        "news_filter": news_filter,
        "trigger": trigger,
        "trade_mgr": trade_mgr,
        "cluster_mgr": cluster_mgr,
        "persistence": persistence,
        "daily_loss": daily_loss,
        "max_dd": max_dd,
        "sizer": sizer,
    }


def test_xauusd_engine_sessions_and_guards(base_components):
    c = base_components
    engine = XauusdEngine(
        symbol="XAUUSD",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )

    assert engine.asset_name == "Gold (XAUUSD)"
    assert engine.get_min_sl_distance(2700.0, 1.0) == 5.0

    # Test London Killzone (08:30 UTC -> active)
    dt_london = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)
    assert engine.is_session_active(dt_london) is True

    # Test Asian dead hours (04:00 UTC -> inactive)
    dt_asian = datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)
    assert engine.is_session_active(dt_asian) is False

    # Test US Cash Session Close Cutoff Guard (16:45 UTC -> vetoed)
    dt_london_close = datetime(2026, 7, 15, 16, 45, tzinfo=timezone.utc)
    assert engine.check_symbol_guards(dt_london_close, {}, 2700.0) is False

    # Test G5 Consecutive Loss Guard
    assert engine.consec_losses == 0
    engine.on_position_closed(-50.0, dt_london, ExitReason.STOP_LOSS)
    assert engine.consec_losses == 1
    assert engine.london_paused_today is True  # Lost during London -> London paused

    engine.on_position_closed(-50.0, dt_london, ExitReason.STOP_LOSS)
    assert engine.consec_losses == 2
    assert engine.paused_today is True  # 2 SLs -> Day paused
    assert engine.check_symbol_guards(dt_london, {}, 2700.0) is False


def test_nas100_engine_sessions_and_guards(base_components):
    c = base_components
    engine = Nas100Engine(
        symbol="USTECH100M",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )

    assert engine.asset_name == "Nasdaq 100 (NAS100 / USTECH100M)"
    assert engine.get_risk_per_trade() == 0.02  # 2.0% default

    # US Cash Open (14:00 UTC -> active)
    dt_us_open = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    assert engine.is_session_active(dt_us_open) is True

    # London morning (08:00 UTC -> inactive for US cash session)
    dt_london = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
    assert engine.is_session_active(dt_london) is False

    # Test NAS consecutive loss guard
    assert engine.consec_losses == 0
    engine.on_position_closed(-100.0, dt_us_open, ExitReason.STOP_LOSS)
    assert engine.consec_losses == 1
    assert engine.paused_today is False

    engine.on_position_closed(-100.0, dt_us_open, ExitReason.STOP_LOSS)
    assert engine.consec_losses == 2
    assert engine.paused_today is True
    assert engine.check_symbol_guards(dt_us_open, {}, 19500.0) is False


def test_engine_isolation(base_components):
    """Verify Gold and Nasdaq engines maintain completely isolated state."""
    c = base_components
    gold_engine = XauusdEngine(
        symbol="XAUUSD",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )

    nas_engine = Nas100Engine(
        symbol="USTECH100M",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )

    now_utc = datetime(2026, 7, 15, 14, 30, tzinfo=timezone.utc)

    # 1. Hit 2 SLs on Gold -> Gold is paused
    gold_engine.on_position_closed(-100.0, now_utc, ExitReason.STOP_LOSS)
    gold_engine.on_position_closed(-100.0, now_utc, ExitReason.STOP_LOSS)
    assert gold_engine.paused_today is True
    assert gold_engine.consec_losses == 2

    # Nasdaq MUST NOT be affected!
    assert nas_engine.paused_today is False
    assert nas_engine.consec_losses == 0
    assert nas_engine.check_symbol_guards(now_utc, {}, 19500.0) is True

    # 2. Increment session trades on Nasdaq
    nas_engine.session_trades += 1
    assert nas_engine.session_trades == 1
    assert gold_engine.session_trades == 0  # Gold session trade counter unchanged


def test_multi_engine_coordinator_threaded_and_shutdown(base_components):
    """Verify coordinator registers engines, starts threads, and shuts down cleanly."""
    c = base_components
    coordinator = MultiEngineCoordinator(
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        daily_loss=c["daily_loss"],
        max_dd=c["max_dd"],
        sizer=c["sizer"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        news_filter=c["news_filter"],
        persistence=c["persistence"],
    )

    gold_engine = XauusdEngine(
        symbol="XAUUSD",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )

    nas_engine = Nas100Engine(
        symbol="USTECH100M",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )

    coordinator.register_engine(gold_engine)
    coordinator.register_engine(nas_engine)

    assert "XAUUSD" in coordinator.engines
    assert "USTECH100M" in coordinator.engines

    # Mock engine worker loop to run briefly and stop
    with patch.object(coordinator, "_engine_worker_loop", side_effect=lambda eng: time.sleep(0.05)):
        # Start coordinator in threaded mode in background
        t_coord = threading.Thread(target=coordinator.start, kwargs={"mode": "threaded"}, daemon=True)
        t_coord.start()

        time.sleep(0.1)
        assert coordinator.running is True

        # Stop coordinator
        coordinator.stop()
        t_coord.join(timeout=2.0)
        assert coordinator.running is False


def test_nas_ny_open_blackout_and_symbol_cooldown(base_components):
    """Verify Nasdaq opening-bell blackout (09:30-09:34 NY) and 15-min post-loss cooldown."""
    c = base_components
    nas_engine = Nas100Engine(
        symbol="USTECH100M",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )

    # 1. Test blackout veto during 09:31 NY (13:31 UTC)
    ny_dt_blackout = datetime(2026, 10, 22, 9, 31)
    now_utc_blackout = datetime(2026, 10, 22, 13, 31, tzinfo=timezone.utc)
    nas_engine.evaluate_and_trigger(
        now_utc=now_utc_blackout,
        ny_dt=ny_dt_blackout,
        data_all={},
        m1_data=MagicMock(),
        current_price=20000.0,
        pending_clusters=[],
        account_info=MagicMock(),
    )
    # trigger.detect_xau_scalp_sequence should NOT be called due to blackout
    c["trigger"].detect_xau_scalp_sequence.assert_not_called()

    # 2. Test cooldown length: 15 min for Nasdaq vs 60 min for Gold
    now_test = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
    nas_engine.on_position_closed(-50.0, now_test, ExitReason.STOP_LOSS)
    assert nas_engine.last_loss_time == now_test.replace(tzinfo=None)

    gold_engine = XauusdEngine(
        symbol="XAUUSD",
        config=c["cfg"],
        connector=c["connector"],
        account=c["account"],
        data_feed=c["data_feed"],
        spread_tracker=c["spread_tracker"],
        spread_filter=c["spread_filter"],
        news_filter=c["news_filter"],
        trigger=c["trigger"],
        trade_mgr=c["trade_mgr"],
        cluster_mgr=c["cluster_mgr"],
        persistence=c["persistence"],
    )
    gold_engine.on_position_closed(-50.0, now_test, ExitReason.STOP_LOSS)

    # At 16 minutes after loss:
    t_16m = now_test + timedelta(minutes=16)
    t_16m_naive = t_16m.replace(tzinfo=None)
    nas_cd = getattr(c["cfg"].trading, "nas_post_loss_cooldown_minutes", 15)
    gold_cd = getattr(c["cfg"].trading, "xau_post_loss_cooldown_minutes", 60)

    elapsed_nas = (t_16m_naive - nas_engine.last_loss_time).total_seconds() / 60.0
    elapsed_gold = (t_16m_naive - gold_engine.last_loss_time).total_seconds() / 60.0

    # Nasdaq cooldown should be expired (16 >= 15)
    assert elapsed_nas >= nas_cd
    # Gold cooldown should still be active (16 < 60)
    assert elapsed_gold < gold_cd

