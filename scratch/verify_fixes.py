import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from xauusd_bot.models import (
    AccountInfo, Bias, ExitReason, PyraCluster, Regime, Signal, SignalGrade,
    TimeframeData, TradeDirection, TradeLeg, TradeStatus,
)
from xauusd_bot.order.entry import OrderEntry, SignalReservation
from xauusd_bot.order.partial_close import PartialCloseManager
from xauusd_bot.risk.daily_loss import DailyLossTracker
from xauusd_bot.strategy.bias_detector import BiasDetector
from xauusd_bot.strategy.trigger import TriggerDetector
from xauusd_bot.trade.trade_manager import TradeManager


class TestAlgorithmFixes(unittest.TestCase):

    def test_signal_reservation_lifecycle(self):
        """Verify SignalReservation allows subsequent orders after market/limit placement."""
        res = SignalReservation()
        self.assertTrue(res.reserve("sig_1", "XAUUSD"))
        # Same symbol blocked while in flight
        self.assertFalse(res.reserve("sig_2", "XAUUSD"))
        # Once order is submitted to broker, release symbol lock
        res.release_symbol("XAUUSD")
        # Now new signal on XAUUSD can be submitted
        self.assertTrue(res.reserve("sig_2", "XAUUSD"))
        # Duplicate signal id remains blocked
        self.assertFalse(res.reserve("sig_1", "XAUUSD"))

    def test_phantom_breakeven_synchronization(self):
        """Verify that after Partial TP, order_entry.modify_sl_tp is called on the broker."""
        mock_connector = MagicMock()
        mock_connector.ensure_connected.return_value = True
        mock_entry = MagicMock()
        mock_entry.close_position.return_value = True

        partial_mgr = PartialCloseManager(take_profit_r=1.0, close_pct=50.0)
        from xauusd_bot.risk.pyramid_manager import PyramidManager
        pyra_mgr = PyramidManager()
        from xauusd_bot.order.exit import ExitManager
        from xauusd_bot.config import TradingConfig
        cfg = TradingConfig()
        cfg.xau_partial_close_enabled = True
        exit_mgr = ExitManager(cfg)
        from xauusd_bot.risk.position_sizer import PositionSizer
        from xauusd_bot.risk.daily_loss import DailyLossTracker
        from xauusd_bot.risk.max_dd import MaxDDTracker
        sizer = PositionSizer()
        daily = DailyLossTracker()
        max_dd = MaxDDTracker()

        tm = TradeManager(
            order_entry=mock_entry,
            exit_mgr=exit_mgr,
            partial_close=partial_mgr,
            pyramid_mgr=pyra_mgr,
            sizer=sizer,
            daily_loss=daily,
            max_dd=max_dd,
        )

        cluster = PyraCluster(
            cluster_id="cluster_1",
            direction=TradeDirection.BUY,
            collective_sl=2640.0,
            initial_r_dist=10.0,
            symbol="XAUUSD",
        )
        leg = TradeLeg(
            position_ticket=12345,
            symbol="XAUUSD",
            direction=TradeDirection.BUY,
            entry_price=2650.0,
            lot_size=0.10,
            sl_price=2640.0,
            tp_price=2680.0,
            status=TradeStatus.OPEN,
        )
        cluster.legs.append(leg)

        # Simulate price moving to 2661.0 (1.1R > 1.0R target)
        m1_data = TimeframeData(
            tf="M1",
            time=[datetime.now()],
            open=[2660.0],
            high=[2662.0],
            low=[2659.0],
            close=[2661.0],
            tick_volume=[100],
            spread=[10],
        )
        actions = tm.manage_exits(cluster, {"M1": m1_data})

        # Verify partial close executed
        mock_entry.close_position.assert_called_once()
        # Verify breakeven stop-loss was sent to broker
        mock_entry.modify_sl_tp.assert_called_once_with(12345, 2650.0, 2680.0, symbol="XAUUSD")
        self.assertTrue(cluster.breakeven_activated)

    def test_daily_loss_midnight_rollover_anchoring(self):
        """Verify FTMO rule: rollover anchors start_equity to max(balance, equity)."""
        tracker = DailyLossTracker(daily_limit_pct=3.0)
        # Day 1
        acct_day1 = AccountInfo(balance=100000.0, equity=100000.0, server_time=datetime(2026, 6, 1, 15, 0))
        tracker.update(acct_day1)
        self.assertEqual(tracker.state.start_equity, 100000.0)

        # Day 2 rollover with floating loss: balance=100000, equity=98000
        acct_day2 = AccountInfo(balance=100000.0, equity=98000.0, server_time=datetime(2026, 6, 2, 0, 1))
        tracker.update(acct_day2)
        # Must anchor to 100000 (balance), NOT 98000 (equity), so the $2000 floating loss is counted
        self.assertEqual(tracker.state.start_equity, 100000.0)
        self.assertEqual(tracker.state.daily_pnl, -2000.0)
        self.assertAlmostEqual(float(tracker.loss_used_pct()), 2.0)

    def test_bias_detector_regime_gold_calibration(self):
        """Verify Gold trending regime is detected with calibrated min_dist=0.35%."""
        bd = BiasDetector(regime_min_dist=0.35)
        # Create synthetic trending data for Gold around 2700 where price is 15 points (0.55%) above 50 EMA
        closes = [2650.0 + i * 0.8 for i in range(160)]  # Clear strong upward slope
        data = TimeframeData(
            tf="H4",
            time=[datetime.now()] * len(closes),
            open=closes,
            high=[c + 2.0 for c in closes],
            low=[c - 2.0 for c in closes],
            close=closes,
            tick_volume=[100] * len(closes),
            spread=[10] * len(closes),
        )
        regime = bd.detect_regime(data)
        self.assertEqual(regime, Regime.TRENDING_BULL)

    def test_trigger_micro_structure_break_closed_candle(self):
        """Verify check_micro_structure_break confirms on closed candle to prevent wick fakeouts."""
        td = TriggerDetector()
        # Highs: prior swing high was 2650.0
        # Candle [-2] closed at 2652.0 (confirmed break)
        highs = [2645.0, 2650.0, 2648.0, 2653.0, 2651.0]
        closes = [2644.0, 2649.0, 2647.0, 2652.0, 2650.0]
        data = TimeframeData(
            tf="M1",
            time=[datetime.now()] * len(highs),
            open=closes,
            high=highs,
            low=[h - 5.0 for h in highs],
            close=closes,
            tick_volume=[100] * len(highs),
            spread=[10] * len(highs),
        )
        broken, price = td.check_micro_structure_break(data, TradeDirection.BUY, lookback=2, confirm_closed=True)
        self.assertTrue(broken)
        self.assertEqual(price, 2652.0)

    def test_partial_close_cluster_persistence(self):
        """Verify partial close state is recorded on PyraCluster and prevents duplicate execution."""
        pm = PartialCloseManager(take_profit_r=1.0)
        cluster = PyraCluster(
            cluster_id="cluster_persist",
            direction=TradeDirection.BUY,
            collective_sl=2640.0,
            initial_r_dist=10.0,
        )
        leg = TradeLeg(entry_price=2650.0, lot_size=0.10, sl_price=2640.0, status=TradeStatus.OPEN)
        cluster.legs.append(leg)

        # Trigger 1.0R partial TP (entry=2650, sl=2640, r_dist=10, at 2660 move_r=1.0)
        self.assertTrue(pm.check_partial_tp(cluster, 2660.0))
        self.assertTrue(cluster.partial_tp1_hit)

        # Simulate bot restart: create a new PartialCloseManager instance
        pm_restarted = PartialCloseManager(take_profit_r=1.0)
        # Because cluster.partial_tp1_hit is True, it must NOT trigger again
        self.assertFalse(pm_restarted.check_partial_tp(cluster, 2662.0))


if __name__ == "__main__":
    unittest.main()
