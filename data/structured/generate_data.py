#!/usr/bin/env python3
"""
Deterministic generator for Zava's canonical structured data (ZavaCore athletic apparel).

Single source of truth for the demo: the Zava REST APIs seed themselves from these CSVs,
the Fabric semantic model is built on them, and the notebooks reference the "hero" entities
in demo_entities.json. The data model mirrors the reference UI in docs/ux-reference/.

Catalog = 4 lines x 3 garments x 3 genders x 4 sizes x 4 colorways = 576 SKUs.

Stdlib only. Reproducible (fixed seed). Run:
    python data/structured/generate_data.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
from datetime import date, datetime, timedelta, timezone

SEED = 2026
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
AS_OF = date(2026, 2, 15)  # fixed "now" (matches reference UI timestamps)

rng = random.Random(SEED)

# --------------------------------------------------------------------------- #
# Reference dimensions
# --------------------------------------------------------------------------- #
# (name, line_code, tier_rank, price_multiplier)
LINES = [
    ("Core", "C", 1, 1.00),
    ("Pro", "R", 2, 1.30),
    ("Premium", "P", 3, 1.70),
    ("Elite", "E", 4, 2.20),
]
# garment_code -> (base_price)
GARMENTS = ["T", "S", "P"]  # Top/Tee, Shorts, Pants
GARMENT_BASE = {"T": 35.0, "S": 30.0, "P": 45.0}
GENDERS = [("Mens", "M"), ("Womens", "W"), ("Youth", "Y")]
SIZES = [("Small", "S"), ("Medium", "M"), ("Large", "L"), ("XL", "XL")]
# (color_name, color_code) — order matters: first two -> SS tops, last two -> LS tops
COLORS = [
    ("Black/Orange", "B0"),
    ("Charcoal/Silver", "CS"),
    ("Deep Red/Red", "RR"),
    ("Teal/Orange", "T0"),
]

FACILITIES = [
    {"facility_code": "FC-MEM", "name": "Zava Memphis Distribution Center", "city": "Memphis", "state": "TN", "type": "distribution_center"},
    {"facility_code": "FC-CLT", "name": "Zava Charlotte Distribution Center", "city": "Charlotte", "state": "NC", "type": "distribution_center"},
    {"facility_code": "FC-SEA", "name": "Zava Seattle Distribution Center", "city": "Seattle", "state": "WA", "type": "distribution_center"},
    {"facility_code": "FC-DFW", "name": "Zava Dallas Distribution Center", "city": "Dallas", "state": "TX", "type": "distribution_center"},
    {"facility_code": "FC-EWR", "name": "Zava Newark Distribution Center", "city": "Newark", "state": "NJ", "type": "distribution_center"},
    {"facility_code": "FC-RNO", "name": "Zava Reno Distribution Center", "city": "Reno", "state": "NV", "type": "distribution_center"},
    {"facility_code": "FC-CMH", "name": "Zava Columbus Distribution Center", "city": "Columbus", "state": "OH", "type": "distribution_center"},
]

STORES = [
    {"store_code": "ST-AUS", "name": "Zava Austin", "city": "Austin", "state": "TX", "channel": "B2C"},
    {"store_code": "ST-MIA", "name": "Zava Miami", "city": "Miami", "state": "FL", "channel": "B2C"},
    {"store_code": "ST-CHI", "name": "Zava Chicago", "city": "Chicago", "state": "IL", "channel": "B2C"},
]

CARRIERS = ["Zava Express", "Swift Post", "Metro Freight"]

FIRST_NAMES = ["Jane", "Priya", "Diego", "Marcus", "Sara", "Maya", "Tom", "Liam", "Emma", "Noah",
               "Olivia", "Ava", "Lucas", "Mia", "Ethan", "Sofia", "James", "Isabella", "Ben", "Chloe",
               "Aiden", "Grace", "Nina", "Omar", "Lena", "Raj", "Ines", "Carlos", "Yara", "Hana",
               "Leo", "Zoe", "Kai", "Ruth", "Cole", "Nora", "Ian", "Tara", "Seth", "Amara"]
LAST_NAMES = ["Smith", "Nair", "Santos", "Lee", "Kim", "Alvarez", "Becker", "Patel", "Nguyen", "Garcia",
              "Silva", "Cohen", "Rossi", "Haddad", "Okafor", "Novak", "Costa", "Mendes", "Larsen", "Fischer"]

# City pool for shipping addresses (city, state, zip)
DEST_CITIES = [
    ("Seattle", "WA", "98101"), ("Austin", "TX", "78701"), ("Miami", "FL", "33101"),
    ("Chicago", "IL", "60601"), ("Denver", "CO", "80202"), ("Boston", "MA", "02108"),
    ("Portland", "OR", "97201"), ("Nashville", "TN", "37201"), ("Phoenix", "AZ", "85004"),
    ("Atlanta", "GA", "30303"), ("Newark", "NJ", "07102"), ("Columbus", "OH", "43215"),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def write_csv(name: str, rows: list[dict], fieldnames: list[str]) -> None:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {name:20s} ({len(rows)} rows)")


def money(v: float) -> float:
    return round(v, 2)


def tracking() -> str:
    return "ZVX-" + "".join(str(rng.randint(0, 9)) for _ in range(13))


# --------------------------------------------------------------------------- #
# Products (576)
# --------------------------------------------------------------------------- #

def build_products():
    products = []
    reorder_by_sku = {}
    for line_name, line_code, _tier, mult in LINES:
        for garment in GARMENTS:
            for gender_name, gender_code in GENDERS:
                for size_label, size_code in SIZES:
                    for color_idx, (color_name, color_code) in enumerate(COLORS):
                        if garment == "T":
                            cut = "SS" if color_idx < 2 else "LS"
                            word = "Tee" if line_name == "Elite" else "Top"
                            display = f"{line_name} {gender_name} {cut} {word} {size_label} {color_name}"
                        elif garment == "S":
                            cut = "AS"
                            display = f"{line_name} {gender_name} Shorts {size_label} {color_name}"
                        else:  # P
                            cut = "AP"
                            display = f"{line_name} {gender_name} Pants {size_label} {color_name}"

                        sku = f"ZC{line_code}{garment}{gender_code}-{cut}-{size_code}-{color_code}"
                        price = GARMENT_BASE[garment] * mult
                        if gender_name == "Youth":
                            price *= 0.85
                        price = money(price * rng.uniform(0.95, 1.08))
                        cost = money(price * 0.42)
                        reorder = rng.choice([40, 60, 80, 100, 120])
                        reorder_by_sku[sku] = reorder
                        products.append({
                            "sku": sku,
                            "product_line": f"ZavaCore Field {line_name}",
                            "line_code": line_code,
                            "garment": {"T": "Top", "S": "Shorts", "P": "Pants"}[garment],
                            "gender": gender_name,
                            "cut": cut,
                            "size": size_code,
                            "size_label": size_label,
                            "color_code": color_code,
                            "color_name": color_name,
                            "name": display,
                            "channel": "B2C",
                            "unit_cost": cost,
                            "unit_price": price,
                            "active": "true",
                        })
    assert len(products) == 576, f"expected 576 SKUs, got {len(products)}"
    return products, reorder_by_sku


PRODUCT_LINES = [
    {"line_code": lc, "product_line": f"ZavaCore Field {ln}", "tier_rank": tr, "channel": "B2C"}
    for (ln, lc, tr, _m) in LINES
]


# --------------------------------------------------------------------------- #
# Inventory (per SKU x facility)
# --------------------------------------------------------------------------- #

def status_for(on_hand: int, reorder: int, projected: int) -> str:
    if on_hand < 0.2 * reorder or projected <= 3:
        return "critical"
    if on_hand < reorder:
        return "low stock"
    return "in stock"


def build_inventory(products, reorder_by_sku):
    rows = []
    for p in products:
        sku = p["sku"]
        reorder = reorder_by_sku[sku]
        safety = int(round(reorder * 0.4))
        daily_demand = max(1, round(reorder / 14))
        for fac in FACILITIES:
            r = rng.random()
            if r < 0.08:          # critical band
                on_hand = rng.randint(0, int(0.2 * reorder))
            elif r < 0.22:        # low band
                on_hand = rng.randint(int(0.2 * reorder), reorder - 1)
            else:                 # healthy
                on_hand = rng.randint(reorder, reorder * 5)
            reserved = rng.randint(0, max(1, on_hand // 6))
            available = on_hand - reserved
            projected = math.floor(on_hand / daily_demand)
            rows.append({
                "sku": sku,
                "facility_code": fac["facility_code"],
                "on_hand": on_hand,
                "reserved": reserved,
                "available": available,
                "reorder_point": reorder,
                "safety_stock": safety,
                "projected_stockout_days": projected,
                "status": status_for(on_hand, reorder, projected),
                "bin_location": f"{fac['facility_code'][-3:]}-{rng.randint(1,60):02d}-{rng.choice('ABCDEF')}",
            })
    # --- Plant the hero critical alert (matches reference UI) ---
    hero_sku = "ZCPTM-LS-L-RR"  # Premium Mens LS Top Large Deep Red/Red
    for row in rows:
        if row["sku"] == hero_sku and row["facility_code"] == "FC-CLT":
            row.update({
                "on_hand": 15, "reserved": 0, "available": 15,
                "reorder_point": 80, "safety_stock": 32,
                "projected_stockout_days": 3, "status": "critical",
            })
            break
    return rows


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #

def build_customers():
    customers = []
    seed_people = [
        ("CUST-0001", "Jane", "Smith", "Seattle", "WA", "98101"),
        ("CUST-0002", "Priya", "Nair", "Austin", "TX", "78701"),
        ("CUST-0003", "Diego", "Santos", "Miami", "FL", "33101"),
        ("CUST-0004", "Marcus", "Lee", "Toronto", "ON", "M5H 2N2"),
        ("CUST-0005", "Sara", "Kim", "Chicago", "IL", "60601"),
    ]
    seen = set()
    for cid, fn, ln, city, state, zc in seed_people:
        customers.append({"customer_id": cid, "first_name": fn, "last_name": ln,
                          "email": f"{fn.lower()}.{ln.lower()}@example.com",
                          "city": city, "state": state, "zip": zc})
        seen.add((fn, ln))
    n = 6
    while len(customers) < 45:
        fn = rng.choice(FIRST_NAMES)
        ln = rng.choice(LAST_NAMES)
        if (fn, ln) in seen:
            continue
        seen.add((fn, ln))
        city, state, zc = rng.choice(DEST_CITIES)
        customers.append({"customer_id": f"CUST-{n:04d}", "first_name": fn, "last_name": ln,
                          "email": f"{fn.lower()}.{ln.lower()}@example.com",
                          "city": city, "state": state, "zip": zc})
        n += 1
    return customers


# --------------------------------------------------------------------------- #
# Sales (last 180 days)
# --------------------------------------------------------------------------- #

def build_sales(products):
    rows = []
    by_sku = {p["sku"]: p for p in products}
    skus = list(by_sku.keys())
    line = 1
    for d in range(180, 0, -1):
        day = AS_OF - timedelta(days=d)
        base = 10 if day.weekday() < 5 else 15
        for _ in range(max(1, base + rng.randint(-4, 6))):
            p = by_sku[rng.choice(skus)]
            online = rng.random() < 0.7
            store = "" if online else rng.choice(STORES)["store_code"]
            qty = rng.randint(1, 5)
            unit = p["unit_price"]
            disc = rng.choice([0, 0, 0, 0.1, 0.2])
            rows.append({
                "sale_id": f"SL-{line:06d}",
                "sale_date": day.isoformat(),
                "channel": "online" if online else "store",
                "store_code": store,
                "sku": p["sku"],
                "product_line": p["product_line"],
                "garment": p["garment"],
                "gender": p["gender"],
                "quantity": qty,
                "unit_price": unit,
                "discount_pct": disc,
                "revenue": money(qty * unit * (1 - disc)),
            })
            line += 1
    return rows


# --------------------------------------------------------------------------- #
# Orders + items
# --------------------------------------------------------------------------- #

def _iso_dt(d: date, hour=12, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute).isoformat()


def build_orders(products, customers):
    by_sku = {p["sku"]: p for p in products}
    cust_by_id = {c["customer_id"]: c for c in customers}
    orders, items = [], []

    def add_items(order_id, skus):
        total = 0.0
        for sku in skus:
            p = by_sku[sku]
            qty = rng.randint(1, 3)
            lt = money(qty * p["unit_price"])
            total += lt
            items.append({"order_id": order_id, "sku": sku, "name": p["name"],
                          "quantity": qty, "unit_price": p["unit_price"], "line_total": lt})
        return money(total)

    def add_order(o):
        o["item_count"] = sum(1 for it in items if it["order_id"] == o["order_id"])
        orders.append(o)

    # ---- Hero orders (stable IDs referenced by notebooks/UI) ----
    heroes = [
        {
            "order_id": 23518, "customer_id": "CUST-0001", "recipient_name": "Jane Smith",
            "order_date": "2026-02-10", "channel": "online", "ship_from_facility": "FC-MEM",
            "carrier": "Zava Express", "tracking_number": "ZVX-7489201374829",
            "status": "delayed", "status_label": "Delayed - Weather",
            "estimated_delivery": "2026-02-17", "last_location": "Zava Memphis Distribution Center",
            "deliver_city": "Seattle", "deliver_state": "WA", "deliver_zip": "98101",
            "delay_reason": "Severe winter storm in Memphis, TN area causing hub delays",
            "notes": "Package is held at distribution center. Expected to resume transit once weather clears. No action required from recipient.",
            "last_updated": "2026-02-15T00:23:00",
            "skus": ["ZCPTM-SS-M-B0", "ZCESM-AS-M-RR"],
        },
        {
            "order_id": 23544, "customer_id": "CUST-0004", "recipient_name": "Marcus Lee",
            "order_date": "2026-02-08", "channel": "online", "ship_from_facility": "FC-EWR",
            "carrier": "Zava Express", "tracking_number": "ZVX-5561203399471",
            "status": "delayed", "status_label": "Delayed - Customs",
            "estimated_delivery": "2026-02-20", "last_location": "International customs (via Newark)",
            "deliver_city": "Toronto", "deliver_state": "ON", "deliver_zip": "M5H 2N2",
            "delay_reason": "Shipment held at customs pending import documentation.",
            "notes": "You may need to provide import documents. Zava Global support will contact you directly.",
            "last_updated": "2026-02-14T18:40:00",
            "skus": ["ZCETM-LS-L-RR", "ZCEPM-AP-L-B0"],
        },
        {
            "order_id": 23561, "customer_id": "CUST-0002", "recipient_name": "Priya Nair",
            "order_date": "2026-02-12", "channel": "app", "ship_from_facility": "FC-DFW",
            "carrier": "Swift Post", "tracking_number": "ZVX-3320948175560",
            "status": "out_for_delivery", "status_label": "Out for Delivery",
            "estimated_delivery": "2026-02-15", "last_location": "Out for delivery - Austin, TX",
            "deliver_city": "Austin", "deliver_state": "TX", "deliver_zip": "78701",
            "delay_reason": "", "notes": "On the delivery vehicle; expected today.",
            "last_updated": "2026-02-15T08:05:00",
            "skus": ["ZCRTW-SS-S-CS"],
        },
        {
            "order_id": 23575, "customer_id": "CUST-0003", "recipient_name": "Diego Santos",
            "order_date": "2026-02-09", "channel": "online", "ship_from_facility": "FC-CMH",
            "carrier": "Metro Freight", "tracking_number": "ZVX-9014772630185",
            "status": "exception", "status_label": "Exception - Address",
            "estimated_delivery": "2026-02-19", "last_location": "Zava Columbus Distribution Center",
            "deliver_city": "Miami", "deliver_state": "FL", "deliver_zip": "33101",
            "delay_reason": "Address could not be verified by the carrier.",
            "notes": "Please confirm your shipping address in your account or contact support to release the package.",
            "last_updated": "2026-02-14T14:12:00",
            "skus": ["ZCCTY-SS-M-B0", "ZCPSW-AS-L-CS"],
        },
        {
            "order_id": 23590, "customer_id": "CUST-0005", "recipient_name": "Sara Kim",
            "order_date": "2026-02-07", "channel": "online", "ship_from_facility": "FC-CMH",
            "carrier": "Zava Express", "tracking_number": "ZVX-1180655472093",
            "status": "delivered", "status_label": "Delivered",
            "estimated_delivery": "2026-02-13", "last_location": "Delivered - Chicago, IL",
            "deliver_city": "Chicago", "deliver_state": "IL", "deliver_zip": "60601",
            "delay_reason": "", "notes": "Delivered and signed for.",
            "last_updated": "2026-02-13T16:47:00",
            "skus": ["ZCPTM-SS-L-B0", "ZCPPY-AP-S-CS"],
        },
    ]
    for h in heroes:
        skus = h.pop("skus")
        h["order_total"] = add_items(h["order_id"], skus)
        add_order(h)

    # ---- Bulk orders ----
    all_skus = list(by_sku.keys())
    status_choices = [
        ("processing", "Processing", ""),
        ("in_transit", "In Transit", ""),
        ("out_for_delivery", "Out for Delivery", ""),
        ("delivered", "Delivered", ""),
        ("delayed", "Delayed - Weather", "Weather delay at regional hub."),
        ("delayed", "Delayed - Volume", "High shipping volume delayed processing."),
        ("exception", "Exception - Address", "Address could not be verified by the carrier."),
    ]
    weights = [6, 16, 10, 40, 6, 6, 4]
    oid = 23600
    for _ in range(85):
        cust = rng.choice(customers)
        status, label, reason = rng.choices(status_choices, weights=weights, k=1)[0]
        order_date = AS_OF - timedelta(days=rng.randint(1, 30))
        fac = rng.choice(FACILITIES)
        skus = rng.sample(all_skus, rng.randint(1, 3))
        if status == "delivered":
            eta = order_date + timedelta(days=rng.randint(2, 5))
            last_loc = f"Delivered - {cust['city']}, {cust['state']}"
        elif status == "delayed":
            eta = order_date + timedelta(days=rng.randint(6, 12))
            last_loc = f"{fac['name']}"
        elif status == "out_for_delivery":
            eta = AS_OF
            last_loc = f"Out for delivery - {cust['city']}, {cust['state']}"
        elif status == "exception":
            eta = order_date + timedelta(days=rng.randint(7, 14))
            last_loc = f"{fac['name']}"
        elif status == "processing":
            eta = order_date + timedelta(days=rng.randint(4, 8))
            last_loc = f"{fac['name']}"
        else:  # in_transit
            eta = order_date + timedelta(days=rng.randint(3, 7))
            last_loc = rng.choice(["Regional hub", f"In transit to {cust['city']}, {cust['state']}"])
        o = {
            "order_id": oid,
            "customer_id": cust["customer_id"],
            "recipient_name": f"{cust['first_name']} {cust['last_name']}",
            "order_date": order_date.isoformat(),
            "channel": rng.choice(["online", "app", "store"]),
            "ship_from_facility": fac["facility_code"],
            "carrier": rng.choice(CARRIERS),
            "tracking_number": tracking(),
            "status": status,
            "status_label": label,
            "estimated_delivery": eta.isoformat(),
            "last_location": last_loc,
            "deliver_city": cust["city"], "deliver_state": cust["state"], "deliver_zip": cust["zip"],
            "delay_reason": reason,
            "notes": "",
            "last_updated": _iso_dt(AS_OF - timedelta(days=rng.randint(0, 2)), rng.randint(6, 22), rng.randint(0, 59)),
            "order_total": add_items(oid, skus),
        }
        add_order(o)
        oid += 1
    return orders, items


# --------------------------------------------------------------------------- #
# demo_entities.json
# --------------------------------------------------------------------------- #

def build_demo_entities():
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": AS_OF.isoformat(),
        "kpis": {"product_lines": 4, "total_skus": 576, "facilities": 7, "retail_stores": 3},
        "hero_skus": [
            {"sku": "ZCPTM-SS-S-B0", "why": "Featured Premium top for live cross-facility stock lookups"},
            {"sku": "ZCPTM-LS-L-RR", "why": "Premium LS Top that is CRITICAL at Charlotte (15 units, reorder 80, ~3 days to stockout)"},
        ],
        "hero_critical_alert": {
            "facility": "FC-CLT", "facility_name": "Zava Charlotte Distribution Center",
            "sku": "ZCPTM-LS-L-RR", "product": "ZavaCore Field Premium LS Top (Large, Deep Red/Red)",
            "on_hand": 15, "reorder_point": 80, "projected_stockout_days": 3, "status": "critical",
        },
        "hero_orders": [
            {"order_id": 23518, "status_label": "Delayed - Weather", "recipient": "Jane Smith",
             "scenario": "Weather delay; held at Memphis DC; no action required"},
            {"order_id": 23544, "status_label": "Delayed - Customs", "recipient": "Marcus Lee",
             "scenario": "Customs hold; import documents; follow-up (memory)"},
            {"order_id": 23561, "status_label": "Out for Delivery", "recipient": "Priya Nair",
             "scenario": "Happy path; arriving today"},
            {"order_id": 23575, "status_label": "Exception - Address", "recipient": "Diego Santos",
             "scenario": "Address exception; customer action needed"},
            {"order_id": 23590, "status_label": "Delivered", "recipient": "Sara Kim",
             "scenario": "Delivered and signed for"},
        ],
        "personas": {
            "inventory": ["Maya Alvarez (Inventory Operations Manager)", "Tom Becker (DC Lead, Charlotte)"],
            "delivery": ["Jane Smith", "Priya Nair", "Diego Santos", "Marcus Lee"],
        },
        "sample_questions": {
            "inventory_agent": [
                "What are my most critical stock issues right now?",
                "How many units of ZCPTM-SS-S-B0 do we have across facilities?",
                "Which SKUs are critical at Charlotte?",
                "What's the total on-hand units for the Premium line?",
                "What's our return policy for worn or opened apparel?",
                "How did Elite line sales this month compare to last month?",
            ],
            "delivery_support_agent": [
                "Hey, what's the status of order 23518?",
                "Why is order 23544 delayed? When will it arrive?",
                "My order 23575 says exception - what do I do?",
            ],
        },
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    print("Generating Zava (ZavaCore apparel) canonical data ...")
    products, reorder_by_sku = build_products()
    customers = build_customers()
    inventory = build_inventory(products, reorder_by_sku)
    sales = build_sales(products)
    orders, items = build_orders(products, customers)

    write_csv("product_lines.csv", PRODUCT_LINES, list(PRODUCT_LINES[0].keys()))
    write_csv("facilities.csv", FACILITIES, list(FACILITIES[0].keys()))
    write_csv("stores.csv", STORES, list(STORES[0].keys()))
    write_csv("products.csv", products, list(products[0].keys()))
    write_csv("customers.csv", customers, list(customers[0].keys()))
    write_csv("inventory.csv", inventory, list(inventory[0].keys()))
    write_csv("sales.csv", sales, list(sales[0].keys()))
    write_csv("orders.csv", orders, list(orders[0].keys()))
    write_csv("order_items.csv", items, list(items[0].keys()))

    with open(os.path.join(OUT_DIR, "demo_entities.json"), "w", encoding="utf-8") as f:
        json.dump(build_demo_entities(), f, indent=2)
    print("  wrote demo_entities.json")

    crit = sum(1 for r in inventory if r["status"] == "critical")
    print(f"Done. {len(products)} SKUs, {len(inventory)} inventory rows ({crit} critical), "
          f"{len(orders)} orders, {len(sales)} sales lines.")


if __name__ == "__main__":
    main()
