"""Tests for the Zava reorder service. These FAIL against the seeded defect and
must PASS once the Code Fix agent repairs ``reorder.py``."""
from reorder import Sku, reorder_quantity, build_reorder_plan


def test_no_reorder_when_well_stocked():
    # on_hand (200) is above the reorder point (50) -> order nothing.
    item = Sku(sku="ZCPTM-SS-M-B0", on_hand=200, reorder_point=50, target_level=150, case_pack=24)
    assert reorder_quantity(item) == 0


def test_reorder_rounds_up_to_whole_case_pack():
    # deficit = 150 - 20 = 130 units; case pack 24 -> ceil(130/24) = 6 cases -> 144 units.
    item = Sku(sku="ZCPTM-SS-S-B0", on_hand=20, reorder_point=50, target_level=150, case_pack=24)
    assert reorder_quantity(item) == 144


def test_reorder_quantity_is_never_negative():
    items = [
        Sku("ZCPTM-SS-M-B0", on_hand=500, reorder_point=50, target_level=150, case_pack=24),
        Sku("ZCPSH-05-L-C1", on_hand=10, reorder_point=50, target_level=100, case_pack=10),
    ]
    plan = build_reorder_plan(items)
    assert all(qty >= 0 for qty in plan.values()), f"negative reorder qty in {plan}"
    assert plan["ZCPTM-SS-M-B0"] == 0


def test_reorder_reaches_at_least_target():
    # After reordering, on_hand + reorder must be >= target_level.
    item = Sku(sku="ZCPPA-02-XL-K2", on_hand=12, reorder_point=40, target_level=90, case_pack=16)
    qty = reorder_quantity(item)
    assert item.on_hand + qty >= item.target_level
