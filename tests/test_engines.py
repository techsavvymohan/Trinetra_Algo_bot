import threading
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from xauusd_bot.config import Config
from xauusd_bot.engines import (
    BaseSymbolEngine, XauusdEngine, Nas100Engine, VwapAuctionAgent, MultiEngineCoordinator,
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


def test_vwap_auction_agent_sessions_and_guards(base_components):
    """Verify VwapAuctionAgent initialization, session active logic, and Daily VWAP calculation."""
    c = base_components
    agent = VwapAuctionAgent(
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

    assert agent.engine_id == "XAUUSD_VWAP_SECRET_AGENT"
    assert agent.asset_name == "Gold VWAP Auction Secret Agent (XAUUSD)"
    assert agent.get_risk_per_trade() == 0.0085
    assert agent.get_min_sl_distance(2700.0, 1.0) == 5.0

    # 1. Test Session Active logic
    # London Killzone (08:30 UTC -> True)
    dt_london = datetime(2026, 10, 23, 8, 30, tzinfo=timezone.utc)
    assert agent.is_session_active(dt_london) is True

    # NY Core Session (14:30 UTC -> True)
    dt_ny = datetime(2026, 10, 23, 14, 30, tzinfo=timezone.utc)
    assert agent.is_session_active(dt_ny) is True

    # Asian dead hours (04:00 UTC -> False)
    dt_asian = datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc)
    assert agent.is_session_active(dt_asian) is False

    # 2. Test Consecutive Loss Guard
    assert agent.consec_losses == 0
    agent.on_position_closed(-50.0, dt_london, ExitReason.STOP_LOSS)
    assert agent.consec_losses == 1
    assert agent.london_paused_today is True

    agent.on_position_closed(-50.0, dt_london, ExitReason.STOP_LOSS)
    assert agent.consec_losses == 2
    assert agent.paused_today is True
    assert agent.check_symbol_guards(dt_london, {}, 2700.0) is False

    # Win resets consec_losses
    agent.on_position_closed(100.0, dt_london, ExitReason.TAKE_PROFIT)
    assert agent.consec_losses == 0

    # 3. Test True Daily Rolling VWAP calculation (only includes today's bars)
    today_dt = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
    # Yesterday 23:59 UTC timestamp
    t_yesterday = int(datetime(2026, 10, 22, 23, 59, tzinfo=timezone.utc).timestamp())
    # Today 00:01 and 00:02 UTC timestamps
    t_today1 = int(datetime(2026, 10, 23, 0, 1, tzinfo=timezone.utc).timestamp())
    t_today2 = int(datetime(2026, 10, 23, 0, 2, tzinfo=timezone.utc).timestamp())

    m1_sample = TimeframeData(
        tf="M1",
        time=[t_yesterday, t_today1, t_today2],
        open=[2600.0, 2700.0, 2710.0],
        high=[2605.0, 2705.0, 2715.0],
        low=[2595.0, 2695.0, 2705.0],
        close=[2600.0, 2700.0, 2710.0],
        tick_volume=[1000, 100, 100],  # Yesterday's huge volume should be excluded!
        spread=[10, 10, 10],
    )
    # Today bar 1 typical = (2705 + 2695 + 2700)/3 = 2700.0, vol = 100 -> pv = 270,000
    # Today bar 2 typical = (2715 + 2705 + 2710)/3 = 2710.0, vol = 100 -> pv = 271,000
    # Expected VWAP = (270,000 + 271,000) / 200 = 541,000 / 200 = 2705.0
    calc_vwap = agent.calculate_daily_vwap(m1_sample, today_dt)
    assert round(calc_vwap, 2) == 2705.0


def test_vwap_auction_agent_discount_buy_trigger(base_components):
    """Verify VWAP agent detects BUY in Discount Auction (price < VWAP) after SSL sweep & MSS."""
    c = base_components
    agent = VwapAuctionAgent(
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

    now_utc = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
    base_t = int(now_utc.timestamp())

    # Build M15 data with SSL at 2690.0 at closed bar index -5
    m15_highs = [2710.0] * 20
    m15_lows = [2695.0] * 14 + [2690.0] + [2695.0] * 5  # SSL = 2690.0 inside closed bars
    m15_data = TimeframeData(
        tf="M15",
        time=[base_t - (20 - i) * 900 for i in range(20)],
        open=[2700.0] * 20,
        high=m15_highs,
        low=m15_lows,
        close=[2700.0] * 20,
        tick_volume=[500] * 20,
        spread=[10] * 20,
    )

    # Build M1 data where:
    # 1. Prior bars establish VWAP at ~2705.0 (so price 2693 is in DISCOUNT)
    # 2. Bar at -3, -2 sweeps SSL (low = 2688.0 < 2690.0)
    # 3. Bar at -1 closes strongly above SSL with MSS breakout (open=2690.0, close=2693.0, high=2693.5, low=2689.5)
    # Range of bars ~2.0 so m1_atr ~ 2.0
    m1_times = [base_t - (20 - i) * 60 for i in range(20)]
    m1_opens = [2705.0] * 15 + [2692.0, 2691.0, 2689.0, 2689.0, 2690.0]
    m1_highs = [2706.0] * 15 + [2692.5, 2691.5, 2690.0, 2690.0, 2693.5]
    m1_lows = [2704.0] * 15 + [2690.5, 2689.5, 2688.0, 2688.5, 2689.5]  # swept 2690 at -3, -2
    m1_closes = [2705.0] * 15 + [2691.0, 2690.0, 2688.5, 2689.5, 2693.0]
    m1_vols = [100] * 20

    m1_data = TimeframeData(
        tf="M1",
        time=m1_times,
        open=m1_opens,
        high=m1_highs,
        low=m1_lows,
        close=m1_closes,
        tick_volume=m1_vols,
        spread=[10] * 20,
    )

    fake_cluster = PyraCluster(
        symbol="XAUUSD",
        direction=TradeDirection.BUY,
        collective_sl=2685.0,
        target_tp=2705.0,
    )
    c["trade_mgr"].create_pending_retest_cluster.return_value = fake_cluster

    data_all = {"M15": m15_data, "M1": m1_data}
    account_info = AccountInfo(balance=10000.0, equity=10000.0)

    agent.evaluate_and_trigger(
        now_utc=now_utc,
        ny_dt=datetime(2026, 10, 23, 10, 0),
        data_all=data_all,
        m1_data=m1_data,
        current_price=2693.0,
        pending_clusters=[],
        account_info=account_info,
    )

    # Verify cluster was created and tagged as VWAP_AUCTION
    c["trade_mgr"].create_pending_retest_cluster.assert_called_once()
    assert fake_cluster.strategy == "VWAP_AUCTION"
    assert fake_cluster.engine_id == "XAUUSD_VWAP_SECRET_AGENT"
    assert len(c["cluster_mgr"].active) == 1
    assert c["cluster_mgr"].active[0].strategy == "VWAP_AUCTION"


def test_vwap_auction_agent_premium_sell_trigger(base_components):
    """Verify VWAP agent detects SELL in Premium Auction (price > VWAP) after BSL sweep & MSS."""
    c = base_components
    agent = VwapAuctionAgent(
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

    now_utc = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
    base_t = int(now_utc.timestamp())

    # Build M15 data with BSL at 2710.0 at closed bar index -5
    m15_highs = [2700.0] * 14 + [2710.0] + [2700.0] * 5  # BSL = 2710.0 inside closed bars
    m15_lows = [2685.0] * 20
    m15_data = TimeframeData(
        tf="M15",
        time=[base_t - (20 - i) * 900 for i in range(20)],
        open=[2690.0] * 20,
        high=m15_highs,
        low=m15_lows,
        close=[2690.0] * 20,
        tick_volume=[500] * 20,
        spread=[10] * 20,
    )

    # Build M1 data where:
    # 1. Prior bars establish VWAP at ~2695.0 (so price 2707 is in PREMIUM)
    # 2. Price sweeps BSL (high = 2711.5 > 2710.0)
    # 3. Bar at -1 closes strongly down below BSL with MSS breakdown (open=2710.0, close=2707.0, high=2710.5, low=2706.5)
    # Range of bars ~2.0 so m1_atr ~ 2.0
    m1_times = [base_t - (20 - i) * 60 for i in range(20)]
    m1_opens = [2699.0] * 15 + [2707.5, 2708.0, 2710.0, 2710.0, 2709.5]
    m1_highs = [2700.0] * 15 + [2709.0, 2710.0, 2711.5, 2710.5, 2710.0]  # swept 2710 at -3
    m1_lows = [2698.0] * 15 + [2707.5, 2708.0, 2709.0, 2708.5, 2705.5]
    m1_closes = [2699.0] * 15 + [2708.5, 2709.5, 2710.5, 2709.0, 2706.0]
    m1_vols = [100] * 20

    m1_data = TimeframeData(
        tf="M1",
        time=m1_times,
        open=m1_opens,
        high=m1_highs,
        low=m1_lows,
        close=m1_closes,
        tick_volume=m1_vols,
        spread=[10] * 20,
    )

    fake_cluster = PyraCluster(
        symbol="XAUUSD",
        direction=TradeDirection.SELL,
        collective_sl=2715.0,
        target_tp=2690.0,
    )
    c["trade_mgr"].create_pending_retest_cluster.return_value = fake_cluster

    data_all = {"M15": m15_data, "M1": m1_data}
    account_info = AccountInfo(balance=10000.0, equity=10000.0)

    agent.evaluate_and_trigger(
        now_utc=now_utc,
        ny_dt=datetime(2026, 10, 23, 10, 0),
        data_all=data_all,
        m1_data=m1_data,
        current_price=2706.0,
        pending_clusters=[],
        account_info=account_info,
    )

    # Verify cluster was created for SELL and tagged
    c["trade_mgr"].create_pending_retest_cluster.assert_called_once()
    assert fake_cluster.strategy == "VWAP_AUCTION"
    assert fake_cluster.direction == TradeDirection.SELL
    assert fake_cluster.engine_id == "XAUUSD_VWAP_SECRET_AGENT"


def test_coordinator_triple_engine_threaded_coexistence(base_components):
    """Verify coordinator hosts XauusdEngine, VwapAuctionAgent, and Nas100Engine simultaneously."""
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

    primary_gold = XauusdEngine(
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

    secret_agent_gold = VwapAuctionAgent(
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

    coordinator.register_engine(primary_gold)
    coordinator.register_engine(secret_agent_gold)
    coordinator.register_engine(nas_engine)

    # Verify all 3 are stored under distinct keys
    assert "XAUUSD" in coordinator.engines
    assert "XAUUSD_VWAP_SECRET_AGENT" in coordinator.engines
    assert "USTECH100M" in coordinator.engines
    assert len(coordinator.engines) == 3

    assert coordinator.get_engine("XAUUSD") is primary_gold
    assert coordinator.get_engine("XAUUSD_VWAP_SECRET_AGENT") is secret_agent_gold
    assert coordinator.get_engine("USTECH100M") is nas_engine

    # Mock engine worker loop to run briefly and stop
    with patch.object(coordinator, "_engine_worker_loop", side_effect=lambda eng: time.sleep(0.05)):
        t_coord = threading.Thread(target=coordinator.start, kwargs={"mode": "threaded"}, daemon=True)
        t_coord.start()

        time.sleep(0.1)
        assert coordinator.running is True
        assert len(coordinator.worker_threads) == 3

        coordinator.stop()
        t_coord.join(timeout=2.0)
        assert coordinator.running is False


