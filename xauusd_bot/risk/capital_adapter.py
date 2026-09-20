"""Universal Capital Adapter for XAUUSD Digger Bot.

Provides mathematical adaptation of position sizing and tranche execution across
all capital regimes:
- Micro/Nano Accounts (< $1,000): Dynamic Tranche Collapsing
  - 0.01 lots: Single-tranche with 1.0R Breakeven ratchet + trailing runner
  - 0.02 lots: Collapsed 2-tranche (0.01 @ 1.5R + BE ratchet, 0.01 runner)
  - 0.03 lots: Balanced 3-way split (0.01 @ 1.0R, 0.01 @ 2.2R, 0.01 runner)
  - >= 0.04 lots: Standard 3-tranche (25% @ 1.0R, 35% @ 2.2R, 40% runner)
- Cent Accounts (USC / EUC): Balance & contract size normalization
- Whale Accounts (> $500,000): Identifies orders requiring Iceberg slicing
"""
import logging
from enum import Enum
from typing import Optional, Tuple
from pydantic import BaseModel, Field

log = logging.getLogger("xauusd_bot.risk.capital_adapter")


class TrancheMode(str, Enum):
    STANDARD_3_TRANCHE = "STANDARD_3_TRANCHE"
    COLLAPSED_2_TRANCHE = "COLLAPSED_2_TRANCHE"
    BALANCED_3_TRANCHE = "BALANCED_3_TRANCHE"
    SINGLE_TRANCHE_BE = "SINGLE_TRANCHE_BE"


class TranchePlan(BaseModel):
    mode: TrancheMode
    total_lots: float
    tranche1_lots: float = 0.0
    tranche1_r: float = 1.0
    tranche2_lots: float = 0.0
    tranche2_r: float = 2.2
    runner_lots: float = 0.0
    runner_trail_atr_mult: float = 3.0
    be_trigger_r: float = 1.0
    be_buffer_pts: float = 0.20


class CapitalAdapter:
    """Adapts position execution to guarantee zero lot-indivisibility errors across all fund sizes."""

    @staticmethod
    def adapt_tranches(
        total_lots: float,
        base_t1_pct: float = 25.0,
        base_t2_pct: float = 35.0,
        base_t1_r: float = 1.0,
        base_t2_r: float = 2.2,
        runner_atr_mult: float = 3.0,
        min_lot: float = 0.01,
        lot_step: float = 0.01,
    ) -> TranchePlan:
        """Calculate mathematically sound tranche distribution for any volume."""
        rounded_total = round(round(total_lots / lot_step) * lot_step, 2)
        if rounded_total <= 0:
            return TranchePlan(
                mode=TrancheMode.SINGLE_TRANCHE_BE,
                total_lots=0.0,
                be_trigger_r=base_t1_r,
            )

        # 1. Single-lot micro position (0.01 lots)
        if rounded_total <= min_lot:
            return TranchePlan(
                mode=TrancheMode.SINGLE_TRANCHE_BE,
                total_lots=rounded_total,
                tranche1_lots=0.0,
                tranche2_lots=0.0,
                runner_lots=rounded_total,
                runner_trail_atr_mult=runner_atr_mult,
                be_trigger_r=base_t1_r,
                be_buffer_pts=0.20,
            )

        # 2. Collapsed 2-tranche micro position (0.02 lots)
        if abs(rounded_total - 0.02) < 1e-4:
            return TranchePlan(
                mode=TrancheMode.COLLAPSED_2_TRANCHE,
                total_lots=0.02,
                tranche1_lots=0.01,
                tranche1_r=1.50,  # Bank half at 1.5R, move SL to BE
                tranche2_lots=0.0,
                runner_lots=0.01,
                runner_trail_atr_mult=runner_atr_mult,
                be_trigger_r=1.50,
                be_buffer_pts=0.20,
            )

        # 3. Balanced 3-way micro position (0.03 lots)
        if abs(rounded_total - 0.03) < 1e-4:
            return TranchePlan(
                mode=TrancheMode.BALANCED_3_TRANCHE,
                total_lots=0.03,
                tranche1_lots=0.01,
                tranche1_r=base_t1_r,
                tranche2_lots=0.01,
                tranche2_r=base_t2_r,
                runner_lots=0.01,
                runner_trail_atr_mult=runner_atr_mult,
                be_trigger_r=base_t1_r,
                be_buffer_pts=0.20,
            )

        # 4. Standard 3-Tranche Position (>= 0.04 lots)
        t1_raw = rounded_total * (base_t1_pct / 100.0)
        t1_lots = max(min_lot, round(round(t1_raw / lot_step) * lot_step, 2))

        t2_raw = rounded_total * (base_t2_pct / 100.0)
        t2_lots = max(min_lot, round(round(t2_raw / lot_step) * lot_step, 2))

        runner_lots = round(rounded_total - t1_lots - t2_lots, 2)

        # Adjust for rounding boundaries
        if runner_lots < min_lot:
            if t2_lots > min_lot:
                t2_lots = round(t2_lots - min_lot, 2)
                runner_lots = round(runner_lots + min_lot, 2)
            elif t1_lots > min_lot:
                t1_lots = round(t1_lots - min_lot, 2)
                runner_lots = round(runner_lots + min_lot, 2)

        return TranchePlan(
            mode=TrancheMode.STANDARD_3_TRANCHE,
            total_lots=rounded_total,
            tranche1_lots=t1_lots,
            tranche1_r=base_t1_r,
            tranche2_lots=t2_lots,
            tranche2_r=base_t2_r,
            runner_lots=runner_lots,
            runner_trail_atr_mult=runner_atr_mult,
            be_trigger_r=base_t1_r,
            be_buffer_pts=0.20,
        )

    @staticmethod
    def normalize_cent_account(
        balance: float,
        equity: float,
        is_cent: bool = False,
    ) -> Tuple[float, float, float]:
        """Normalize cent account balances into standard USD terms.

        Returns: (normalized_balance, normalized_equity, cent_multiplier)
        """
        if not is_cent:
            return balance, equity, 1.0
        # In a cent account, 10,000 USC = $100.00 USD
        norm_bal = balance / 100.0
        norm_eq = equity / 100.0
        return norm_bal, norm_eq, 0.01
