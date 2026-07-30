"""Zava nightly **reorder service** — computes purchase-order quantities per SKU.

Given the current stock position of each SKU, decide how many units to reorder so
the SKU is brought back up to its target level, ordering only in whole supplier
**case packs**.

NOTE: This module is intentionally seeded with a defect for the incident-response
demo. The nightly batch produced NEGATIVE reorder quantities for well-stocked SKUs
and rounded deficits DOWN below target. The Code Fix agent repairs it in a sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Sku:
    sku: str
    on_hand: int         # units currently in stock
    reorder_point: int   # reorder only when on_hand <= reorder_point
    target_level: int    # bring stock back up to this level
    case_pack: int       # supplier ships in multiples of this many units


def reorder_quantity(item: Sku) -> int:
    """Units to reorder for one SKU, rounded up to whole case packs.

    Business rules:
      - If ``on_hand`` is above ``reorder_point``, order nothing (0).
      - Otherwise order enough to reach ``target_level``, rounded UP to a whole
        number of case packs.
      - The result must NEVER be negative.
    """
    # DEFECT: no "above reorder point -> 0" guard, integer floor division instead
    # of a ceiling, and no clamp. Well-stocked SKUs get a negative deficit and a
    # negative reorder quantity; genuine deficits are rounded DOWN below target.
    deficit = item.target_level - item.on_hand
    cases = deficit // item.case_pack
    return cases * item.case_pack


def build_reorder_plan(items: list[Sku]) -> dict[str, int]:
    """Return a {sku: reorder_quantity} plan for the nightly batch."""
    return {item.sku: reorder_quantity(item) for item in items}
