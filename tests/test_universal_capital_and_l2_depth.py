"""Unit tests for Universal Capital Adapter, Whale Iceberg Slicing, and Level-2 Order Book Imbalance.
"""
import math
import pytest

from xauusd_bot.risk.capital_adapter import CapitalAdapter, TrancheMode, TranchePlan
from xauusd_bot.order.order_slicer import IcebergOrderSlicer
from xauusd_bot.indicators.order_book import OrderBookAnalyzer, OrderBookSnapshot
from xauusd_bot.models import TradeDirection


def test_micro_capital_single_lot():
    """Test 0.01 lot position triggers Single-Tranche Breakeven model."""
    plan = CapitalAdapter.adapt_tranches(0.01)
    assert plan.mode == TrancheMode.SINGLE_TRANCHE_BE
    assert plan.total_lots == 0.01
    assert plan.runner_lots == 0.01
    assert plan.tranche1_lots == 0.0
    assert plan.tranche2_lots == 0.0
    assert plan.be_trigger_r == 1.0


def test_micro_capital_collapsed_two_tranche():
    """Test 0.02 lot position triggers Collapsed 2-Tranche model."""
    plan = CapitalAdapter.adapt_tranches(0.02)
    assert plan.mode == TrancheMode.COLLAPSED_2_TRANCHE
    assert plan.total_lots == 0.02
    assert plan.tranche1_lots == 0.01
    assert plan.tranche1_r == 1.50
    assert plan.runner_lots == 0.01
    assert plan.tranche2_lots == 0.0
    assert math.isclose(plan.tranche1_lots + plan.runner_lots, 0.02, rel_tol=1e-5)


def test_micro_capital_balanced_three_tranche():
    """Test 0.03 lot position triggers Balanced 3-way split."""
    plan = CapitalAdapter.adapt_tranches(0.03)
    assert plan.mode == TrancheMode.BALANCED_3_TRANCHE
    assert plan.total_lots == 0.03
    assert plan.tranche1_lots == 0.01
    assert plan.tranche2_lots == 0.01
    assert plan.runner_lots == 0.01
    assert math.isclose(plan.tranche1_lots + plan.tranche2_lots + plan.runner_lots, 0.03, rel_tol=1e-5)


def test_standard_capital_tranches():
    """Test standard accounts (0.05, 0.50, 5.00 lots) divide cleanly into 25/35/40%."""
    for total in (0.05, 0.50, 1.25, 2.50, 5.00, 10.00):
        plan = CapitalAdapter.adapt_tranches(total, base_t1_pct=25.0, base_t2_pct=35.0)
        assert plan.mode == TrancheMode.STANDARD_3_TRANCHE
        assert plan.tranche1_lots >= 0.01
        assert plan.tranche2_lots >= 0.01
        assert plan.runner_lots >= 0.01
        sum_lots = round(plan.tranche1_lots + plan.tranche2_lots + plan.runner_lots, 2)
        assert math.isclose(sum_lots, total, rel_tol=1e-5), f"Failed for total={total}: sum={sum_lots}"


def test_cent_account_normalization():
    """Test Cent account normalization (10,000 USC = $100.00 USD)."""
    norm_b, norm_e, mult = CapitalAdapter.normalize_cent_account(10000.0, 10000.0, is_cent=True)
    assert norm_b == 100.0
    assert norm_e == 100.0
    assert mult == 0.01

    norm_b2, norm_e2, mult2 = CapitalAdapter.normalize_cent_account(100.0, 100.0, is_cent=False)
    assert norm_b2 == 100.0
    assert norm_e2 == 100.0
    assert mult2 == 1.0


def test_whale_iceberg_slicing():
    """Test institutional large-order decomposition into child slices."""
    assert not IcebergOrderSlicer.needs_slicing(5.0, threshold=10.0)
    assert IcebergOrderSlicer.needs_slicing(10.0, threshold=10.0)
    assert IcebergOrderSlicer.needs_slicing(25.0, threshold=10.0)

    for total in (15.0, 25.0, 50.0, 100.0):
        slices = IcebergOrderSlicer.slice_order(total, max_slice=5.0, min_slice=1.0)
        assert len(slices) > 1
        for s in slices:
            assert s <= 5.01
            assert s >= 0.50
        assert math.isclose(sum(slices), total, rel_tol=1e-5), f"Failed for {total}: sum={sum(slices)}"


def test_order_book_imbalance_calculation():
    """Test Level-2 Order Book Imbalance (OBI) formula and boundary checks."""
    analyzer = OrderBookAnalyzer(depth_levels=5, min_obi_threshold=0.15)

    # Synthetic snapshot: Bullish imbalance (Bids = 80 lots, Asks = 20 lots)
    # OBI = (80 - 20) / (80 + 20) = +60 / 100 = +0.60
    snap_bull = OrderBookSnapshot(
        symbol="XAUUSD",
        bids=[(2650.0, 30.0), (2649.9, 25.0), (2649.8, 25.0)],
        asks=[(2650.2, 10.0), (2650.3, 5.0), (2650.4, 5.0)],
        obi=0.60,
        micro_price=2650.15,
        is_dom_active=True,
    )
    ok_buy, msg_buy = analyzer.validate_order_flow_alignment(snap_bull, "BUY")
    assert ok_buy
    assert "confirmed Bullish" in msg_buy

    ok_sell, msg_sell = analyzer.validate_order_flow_alignment(snap_bull, "SELL")
    assert not ok_sell
    assert "unaligned" in msg_sell

    # Test inactive DOM fallback
    ok_fallback, msg_fallback = analyzer.validate_order_flow_alignment(None, "BUY")
    assert ok_fallback
    assert "tick delta" in msg_fallback
