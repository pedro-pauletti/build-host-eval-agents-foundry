#!/usr/bin/env python3
"""
Load the Zava structured CSVs into Unity Catalog as Delta tables.

This is the Databricks counterpart of ``data/semantic-model/load_delta.py`` (Fabric/OneLake):
same 10 tables, same columns, same types — so the two analytics agents answer the same
questions from equivalent data and only the plumbing differs.

The load goes CSV -> Unity Catalog volume -> ``read_files`` -> typed Delta table. Everything
runs through the SQL Statement Execution API, so no Spark session and no cluster are needed.

Table and column COMMENTs plus informational PK/FK constraints are not decoration here: the
Genie space reads them to pick tables and infer joins, so they directly drive answer quality.

Prereqs:
    az login
    DATABRICKS_HOST in .env  (e.g. adb-1234567890.4.azuredatabricks.net)

Usage:
    .venv\\Scripts\\python.exe data/databricks/load_uc_tables.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _dbx import CATALOG, SCHEMA, REPO, fq, scalar, sql, upload_to_volume  # noqa: E402

SRC = REPO / "data" / "structured"
VOLUME = "raw"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"

# Databricks SQL type per logical kind — mirrors the pyarrow types used on the Fabric side.
TYPES = {
    "str": "STRING", "int": "INT", "bool": "BOOLEAN",
    "dec2": "DECIMAL(18,2)", "dec4": "DECIMAL(9,4)",
    "date": "DATE", "ts": "TIMESTAMP",
}

# table -> (csv, comment, {column: (kind, comment)})
SPECS: dict[str, tuple[str, str, dict[str, tuple[str, str]]]] = {
    "product_lines": ("product_lines.csv", "The four ZavaCore Field product lines (tiers).", {
        "line_code": ("str", "One-letter line code: C=Core, R=Pro, P=Premium, E=Elite."),
        "product_line": ("str", "Full product line name, e.g. 'ZavaCore Field Elite'."),
        "tier_rank": ("int", "1=entry (Core) through 4=top (Elite)."),
        "channel": ("str", "Primary sales channel for the line."),
    }),
    "facilities": ("facilities.csv", "Distribution centres that hold inventory.", {
        "facility_code": ("str", "Facility code such as FC-MEM (Memphis) or FC-CLT (Charlotte). "
                                 "Users often say the city name; map city -> code before filtering."),
        "name": ("str", "Facility display name."),
        "city": ("str", "City the facility is in."),
        "state": ("str", "US state code."),
        "type": ("str", "Facility type, e.g. distribution centre."),
    }),
    "stores": ("stores.csv", "Physical retail stores where in-store sales happen.", {
        "store_code": ("str", "Store code."),
        "name": ("str", "Store display name."),
        "city": ("str", "City."),
        "state": ("str", "US state code."),
        "channel": ("str", "Channel classification for the store."),
    }),
    "customers": ("customers.csv", "Customers who placed orders.", {
        "customer_id": ("str", "Customer identifier."),
        "first_name": ("str", "First name."),
        "last_name": ("str", "Last name."),
        "email": ("str", "Email address."),
        "city": ("str", "City."),
        "state": ("str", "US state code."),
        "zip": ("str", "Postal code."),
    }),
    "products": ("products.csv", "Product catalogue at SKU (size/colour variant) grain.", {
        "sku": ("str", "Stock keeping unit, e.g. ZCPTM-SS-S-B0. Unique per size/colour variant."),
        "product_line": ("str", "Full product line name."),
        "line_code": ("str", "Line code joining to product_lines."),
        "garment": ("str", "Garment type, e.g. tee, shorts, long-sleeve top."),
        "gender": ("str", "Target gender."),
        "cut": ("str", "Garment cut."),
        "size": ("str", "Size code."),
        "size_label": ("str", "Human readable size."),
        "color_code": ("str", "Colour code."),
        "color_name": ("str", "Colour name."),
        "name": ("str", "Full product name."),
        "channel": ("str", "Channel the SKU is sold through."),
        "unit_cost": ("dec2", "Cost per unit in USD."),
        "unit_price": ("dec2", "List price per unit in USD."),
        "active": ("bool", "Whether the SKU is currently active."),
    }),
    "inventory": ("inventory.csv", "Current stock position, one row per SKU per facility.", {
        "sku": ("str", "SKU held."),
        "facility_code": ("str", "Facility holding the stock (FC-xxx code, not the city name)."),
        "on_hand": ("int", "Units physically on hand."),
        "reserved": ("int", "Units reserved against open orders."),
        "available": ("int", "on_hand minus reserved."),
        "reorder_point": ("int", "Level at or below which the SKU must be reordered."),
        "safety_stock": ("int", "Buffer stock level."),
        "projected_stockout_days": ("int", "Estimated days until stockout; 0 means already out."),
        "status": ("str", "Stock status. Exactly one of 'in stock', 'low stock', 'critical' "
                          "- note the spaces, there are no underscores."),
        "bin_location": ("str", "Bin location inside the facility."),
    }),
    "sales": ("sales.csv", "Sales fact table, one row per sale line. Use this for revenue.", {
        "sale_id": ("str", "Sale line identifier."),
        "sale_date": ("date", "Date of sale; join to dim_date.date for time analysis."),
        "channel": ("str", "Sales channel: online or in-store."),
        "store_code": ("str", "Store for in-store sales; NULL for online sales."),
        "sku": ("str", "SKU sold."),
        "product_line": ("str", "Product line name, denormalised for convenience."),
        "garment": ("str", "Garment type, denormalised."),
        "gender": ("str", "Target gender, denormalised."),
        "quantity": ("int", "Units sold on this line."),
        "unit_price": ("dec2", "Price per unit actually charged, USD."),
        "discount_pct": ("dec4", "Discount as a fraction, e.g. 0.10 means 10 percent."),
        "revenue": ("dec2", "Line revenue in USD after discount. Sum this for total revenue."),
    }),
    "orders": ("orders.csv", "Customer order headers with shipment and delivery status.", {
        "order_id": ("str", "Order identifier."),
        "customer_id": ("str", "Customer who placed the order."),
        "recipient_name": ("str", "Name of the recipient."),
        "order_date": ("date", "Date the order was placed."),
        "channel": ("str", "Channel the order came through."),
        "ship_from_facility": ("str", "Facility the order ships from."),
        "carrier": ("str", "Carrier handling the shipment."),
        "tracking_number": ("str", "Carrier tracking number, ZVX-... format."),
        "status": ("str", "Machine status, e.g. delayed_weather, out_for_delivery, delivered."),
        "status_label": ("str", "Human readable status."),
        "estimated_delivery": ("date", "Current estimated delivery date."),
        "last_location": ("str", "Last known location of the shipment."),
        "deliver_city": ("str", "Destination city."),
        "deliver_state": ("str", "Destination state."),
        "deliver_zip": ("str", "Destination postal code."),
        "delay_reason": ("str", "Why the shipment is delayed, when it is."),
        "notes": ("str", "Free-text notes."),
        "last_updated": ("ts", "When the order record was last updated (UTC)."),
        "order_total": ("dec2", "Order total in USD."),
        "item_count": ("int", "Number of items on the order."),
    }),
    "order_items": ("order_items.csv", "Order lines, one row per SKU per order.", {
        "order_id": ("str", "Order the line belongs to."),
        "sku": ("str", "SKU ordered."),
        "name": ("str", "Product name."),
        "quantity": ("int", "Units ordered."),
        "unit_price": ("dec2", "Price per unit, USD."),
        "line_total": ("dec2", "Line total, USD."),
    }),
}

# (table, column) -> (referenced table, referenced column)
FOREIGN_KEYS = [
    ("sales", "sku", "products", "sku"),
    ("sales", "store_code", "stores", "store_code"),
    ("sales", "sale_date", "dim_date", "date"),
    ("inventory", "sku", "products", "sku"),
    ("inventory", "facility_code", "facilities", "facility_code"),
    ("products", "line_code", "product_lines", "line_code"),
    ("orders", "customer_id", "customers", "customer_id"),
    ("orders", "ship_from_facility", "facilities", "facility_code"),
    ("orders", "order_date", "dim_date", "date"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "sku", "products", "sku"),
]

PRIMARY_KEYS = {
    "product_lines": "line_code", "facilities": "facility_code", "stores": "store_code",
    "customers": "customer_id", "products": "sku", "orders": "order_id",
    "sales": "sale_id", "dim_date": "date",
}


def create_schema_and_volume() -> None:
    sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} "
        f"COMMENT 'Zava demo: retail apparel sales, inventory and orders.'")
    sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME} "
        f"COMMENT 'Raw CSV landing zone for the Zava demo load.'")
    print(f"schema {CATALOG}.{SCHEMA} + volume {VOLUME} ready")


def load_table(name: str, csv: str, comment: str, cols: dict[str, tuple[str, str]]) -> int:
    local = SRC / csv
    upload_to_volume(local, f"{VOLUME_PATH}/{csv}")

    # Read every column as STRING so parsing is deterministic, then cast explicitly.
    read_schema = ", ".join(f"{c} STRING" for c in cols)
    select = ",\n    ".join(
        # Empty strings must become NULL, otherwise the cast silently yields 0 / garbage.
        f"CAST(NULLIF({c}, '') AS {TYPES[kind]}) AS {c}" for c, (kind, _) in cols.items()
    )
    sql(f"""
        CREATE OR REPLACE TABLE {fq(name)}
        COMMENT '{comment.replace("'", "''")}'
        AS SELECT
    {select}
        FROM read_files('{VOLUME_PATH}/{csv}',
                        format => 'csv', header => true, schema => '{read_schema}')
    """)
    for col, (_, col_comment) in cols.items():
        sql(f"ALTER TABLE {fq(name)} ALTER COLUMN {col} "
            f"COMMENT '{col_comment.replace(chr(39), chr(39) * 2)}'")
    n = int(scalar(f"SELECT count(*) FROM {fq(name)}"))
    print(f"  {name:14s} rows={n}")
    return n


def build_dim_date() -> int:
    """Contiguous daily calendar spanning every date key in the model."""
    bounds = sql(f"""
        SELECT min(d), max(d) FROM (
          SELECT sale_date AS d FROM {fq('sales')}
          UNION ALL SELECT order_date FROM {fq('orders')}
          UNION ALL SELECT estimated_delivery FROM {fq('orders')}
        ) WHERE d IS NOT NULL
    """)
    lo, hi = bounds["result"]["data_array"][0]
    sql(f"""
        CREATE OR REPLACE TABLE {fq('dim_date')}
        COMMENT 'Daily calendar dimension covering every date in the model. Join sales.sale_date and orders.order_date to this table for time analysis.'
        AS SELECT
            d                                   AS date,
            year(d)                             AS year,
            quarter(d)                          AS quarter,
            month(d)                            AS month,
            date_format(d, 'MMMM')              AS month_name,
            date_format(d, 'yyyy-MM')           AS year_month,
            day(d)                              AS day,
            dayofweek(d)                        AS day_of_week,
            date_format(d, 'EEEE')              AS day_name,
            dayofweek(d) IN (1, 7)              AS is_weekend
        FROM (SELECT explode(sequence(DATE'{lo}', DATE'{hi}', INTERVAL 1 DAY)) AS d)
    """)
    n = int(scalar(f"SELECT count(*) FROM {fq('dim_date')}"))
    print(f"  {'dim_date':14s} rows={n}  ({lo} .. {hi})")
    return n


def add_constraints() -> None:
    """Informational PK/FK — Unity Catalog does not enforce them, but Genie uses them for joins."""
    for table, col in PRIMARY_KEYS.items():
        try:
            sql(f"ALTER TABLE {fq(table)} ALTER COLUMN {col} SET NOT NULL")
            sql(f"ALTER TABLE {fq(table)} ADD CONSTRAINT pk_{table} PRIMARY KEY ({col})")
            print(f"  PK  {table}.{col}")
        except Exception as exc:
            print(f"  PK  {table}.{col} -> skipped ({str(exc)[:90]})")

    for table, col, ref_table, ref_col in FOREIGN_KEYS:
        name = f"fk_{table}_{col}"
        try:
            sql(f"ALTER TABLE {fq(table)} ADD CONSTRAINT {name} "
                f"FOREIGN KEY ({col}) REFERENCES {fq(ref_table)}({ref_col})")
            print(f"  FK  {table}.{col} -> {ref_table}.{ref_col}")
        except Exception as exc:
            print(f"  FK  {table}.{col} -> skipped ({str(exc)[:90]})")


def main() -> None:
    print(f"Loading Zava tables -> {CATALOG}.{SCHEMA}")
    create_schema_and_volume()

    counts = {}
    for name, (csv, comment, cols) in SPECS.items():
        counts[name] = load_table(name, csv, comment, cols)
    counts["dim_date"] = build_dim_date()

    print("\nConstraints:")
    add_constraints()

    print("\nDONE. Row counts:")
    for k, v in counts.items():
        print(f"    {k} = {v}")


if __name__ == "__main__":
    main()
