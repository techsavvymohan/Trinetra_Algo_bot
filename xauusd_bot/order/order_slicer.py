"""Iceberg & Child-Order Slicing Engine for Whale Capital (> $500,000).

Decomposes large institutional orders (e.g. 25–100+ lots) into randomized micro-child
limit orders to prevent order book exhaustion, adverse selection, and front-running.
"""
import logging
import random
from typing import List

log = logging.getLogger("xauusd_bot.order.slicer")


class IcebergOrderSlicer:
    """Institutional Order Slicing Engine for large capital allocations."""

    @staticmethod
    def needs_slicing(
        total_volume: float,
        threshold: float = 10.0,
        broker_max_lot: float = 100.0,
    ) -> bool:
        """Determine if an order exceeds the liquidity threshold or broker limits."""
        return total_volume >= threshold or total_volume > broker_max_lot

    @staticmethod
    def slice_order(
        total_volume: float,
        max_slice: float = 5.0,
        min_slice: float = 1.0,
        lot_step: float = 0.01,
        randomize: bool = True,
    ) -> List[float]:
        """Decompose total order volume into child slices that sum exactly to total_volume.

        Args:
            total_volume: Total volume to execute (lots).
            max_slice: Maximum volume allowed per child slice (lots).
            min_slice: Minimum volume allowed per child slice (lots).
            lot_step: Broker lot step increment (e.g. 0.01).
            randomize: Whether to add random variance to child slice sizes.

        Returns:
            List of child slice volumes in lots.
        """
        rounded_total = round(round(total_volume / lot_step) * lot_step, 2)
        if rounded_total <= max_slice:
            return [rounded_total]

        slices: List[float] = []
        remaining = rounded_total

        while remaining > 0:
            if remaining <= max_slice:
                slices.append(round(remaining, 2))
                break

            # Calculate slice size with optional randomized jitter (+/- 20%)
            if randomize and max_slice > min_slice:
                jitter = random.uniform(0.8, 1.0)
                target_slice = min_slice + (max_slice - min_slice) * jitter
            else:
                target_slice = max_slice

            target_slice = min(target_slice, max_slice)
            target_slice = min(target_slice, remaining)
            # Ensure remainder isn't an invalid micro-dust amount
            if (remaining - target_slice) < min_slice and (remaining - target_slice) > 0:
                target_slice = remaining / 2.0

            slice_lot = round(round(target_slice / lot_step) * lot_step, 2)
            slice_lot = max(min_slice, slice_lot)
            slice_lot = min(slice_lot, max_slice)
            slice_lot = min(slice_lot, remaining)

            slices.append(slice_lot)
            remaining = round(remaining - slice_lot, 2)

        # Sanity verification: child slices must sum exactly to parent volume
        slice_sum = round(sum(slices), 2)
        diff = round(rounded_total - slice_sum, 2)
        if abs(diff) > 0 and len(slices) > 0:
            slices[-1] = round(slices[-1] + diff, 2)

        log.info(
            "Iceberg Slicer: Decomposed %.2f lots into %d child slices: %s (sum=%.2f)",
            rounded_total, len(slices), slices, sum(slices),
        )
        return slices
