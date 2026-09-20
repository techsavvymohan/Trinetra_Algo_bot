"""Asset Specifications for Gold (XAUUSD) and Nasdaq 100 (USTECH100M/NAS100)."""

from typing import Dict, Any


def get_asset_spec(symbol: str = "XAUUSD", price: float = 0.0) -> Dict[str, Any]:
    """Return asset specifications for XAUUSD (Gold) or USTECH100M / NAS100 (Nasdaq)."""
    s = (symbol or "").upper()
    is_index = any(idx in s for idx in ["NAS", "USTEC", "TECH", "US100", "NDX", "NQ"]) or (
        price > 5000.0 and "XAU" not in s and "GOLD" not in s
    )

    if is_index:
        return {
            "asset_type": "index",
            "contract_sz": 1.0,
            "tick_sz": 0.1,
            "point_val": 0.1,
            "digits": 1,
            "is_index": True,
            "is_gold": False,
        }
    else:  # Gold (XAUUSD) default
        return {
            "asset_type": "gold",
            "contract_sz": 100.0,
            "tick_sz": 0.01,
            "point_val": 1.0,
            "digits": 2,
            "is_index": False,
            "is_gold": True,
        }

