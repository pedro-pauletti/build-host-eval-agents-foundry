#!/usr/bin/env python3
"""
Load the Zava structured CSVs into the Fabric ``ZavaLakehouse`` as typed Delta tables.

Runs locally (Windows / PowerShell) using delta-rs (the ``deltalake`` package) writing
directly to OneLake. No Spark session required. Reproducible: re-running overwrites the
tables in place.

Prereqs:
    pip install deltalake pandas pyarrow
    $env:ONELAKE_TOKEN = az account get-access-token --resource https://storage.azure.com --query accessToken -o tsv

Environment parameterization (override via env vars for dev/test/prod):
    FABRIC_WORKSPACE_ID   required  (e.g. the Zava-Demos workspace)
    FABRIC_LAKEHOUSE_ID   required  (e.g. the ZavaLakehouse)
    ONELAKE_TOKEN         AAD bearer token for https://storage.azure.com  (required)
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal, InvalidOperation

import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

WS = os.environ["FABRIC_WORKSPACE_ID"]
LH = os.environ["FABRIC_LAKEHOUSE_ID"]
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "structured")
TOKEN = os.environ["ONELAKE_TOKEN"]
STORAGE = {"bearer_token": TOKEN, "use_fabric_endpoint": "true"}

DEC2 = pa.decimal128(18, 2)   # currency
DEC4 = pa.decimal128(9, 4)    # fractions / percentages (0..1)


def _uri(table: str) -> str:
    return f"abfss://{WS}@onelake.dfs.fabric.microsoft.com/{LH}/Tables/{table}"


# ---- per-column converters (source is read as all-string) -------------------
def _s(v):      # nullable string
    return None if v is None or v == "" else v

def _i(v):      # nullable int
    return None if v is None or v == "" else int(float(v))

def _b(v):      # boolean
    if v is None or v == "":
        return None
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t")

def _dec(v, places):
    if v is None or v == "":
        return None
    try:
        q = Decimal(1).scaleb(-places)  # e.g. 0.01
        return Decimal(str(v)).quantize(q)
    except (InvalidOperation, ValueError):
        return None

def _d(v):      # date
    return None if v is None or v == "" else dt.date.fromisoformat(v[:10])

def _ts(v):     # timestamp (UTC)
    if v is None or v == "":
        return None
    return dt.datetime.fromisoformat(v).replace(tzinfo=dt.timezone.utc)


CONV = {
    "str":  (_s, pa.string()),
    "int":  (_i, pa.int32()),
    "bool": (_b, pa.bool_()),
    "dec2": (lambda v: _dec(v, 2), DEC2),
    "dec4": (lambda v: _dec(v, 4), DEC4),
    "date": (_d, pa.date32()),
    "ts":   (_ts, pa.timestamp("us", tz="UTC")),
}


def build_table(df: pd.DataFrame, spec: dict[str, str]) -> pa.Table:
    arrays, fields = [], []
    for col, kind in spec.items():
        fn, patype = CONV[kind]
        arrays.append(pa.array([fn(x) for x in df[col].tolist()], type=patype))
        fields.append(pa.field(col, patype))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def load(name: str, csv: str, spec: dict[str, str]) -> int:
    df = pd.read_csv(os.path.join(SRC, csv), dtype=str, keep_default_na=False)
    tbl = build_table(df, spec)
    write_deltalake(_uri(name), tbl, mode="overwrite", storage_options=STORAGE,
                    schema_mode="overwrite")
    n = DeltaTable(_uri(name), storage_options=STORAGE).to_pyarrow_table().num_rows
    print(f"  {name:14s} rows={n}")
    return n


SPECS = {
    "product_lines": ("product_lines.csv", {
        "line_code": "str", "product_line": "str", "tier_rank": "int", "channel": "str"}),
    "facilities": ("facilities.csv", {
        "facility_code": "str", "name": "str", "city": "str", "state": "str", "type": "str"}),
    "stores": ("stores.csv", {
        "store_code": "str", "name": "str", "city": "str", "state": "str", "channel": "str"}),
    "customers": ("customers.csv", {
        "customer_id": "str", "first_name": "str", "last_name": "str", "email": "str",
        "city": "str", "state": "str", "zip": "str"}),
    "products": ("products.csv", {
        "sku": "str", "product_line": "str", "line_code": "str", "garment": "str",
        "gender": "str", "cut": "str", "size": "str", "size_label": "str",
        "color_code": "str", "color_name": "str", "name": "str", "channel": "str",
        "unit_cost": "dec2", "unit_price": "dec2", "active": "bool"}),
    "inventory": ("inventory.csv", {
        "sku": "str", "facility_code": "str", "on_hand": "int", "reserved": "int",
        "available": "int", "reorder_point": "int", "safety_stock": "int",
        "projected_stockout_days": "int", "status": "str", "bin_location": "str"}),
    "sales": ("sales.csv", {
        "sale_id": "str", "sale_date": "date", "channel": "str", "store_code": "str",
        "sku": "str", "product_line": "str", "garment": "str", "gender": "str",
        "quantity": "int", "unit_price": "dec2", "discount_pct": "dec4", "revenue": "dec2"}),
    "orders": ("orders.csv", {
        "order_id": "str", "customer_id": "str", "recipient_name": "str", "order_date": "date",
        "channel": "str", "ship_from_facility": "str", "carrier": "str", "tracking_number": "str",
        "status": "str", "status_label": "str", "estimated_delivery": "date",
        "last_location": "str", "deliver_city": "str", "deliver_state": "str",
        "deliver_zip": "str", "delay_reason": "str", "notes": "str", "last_updated": "ts",
        "order_total": "dec2", "item_count": "int"}),
    "order_items": ("order_items.csv", {
        "order_id": "str", "sku": "str", "name": "str", "quantity": "int",
        "unit_price": "dec2", "line_total": "dec2"}),
}


def build_dim_date() -> int:
    """Contiguous daily calendar covering every date key in the model."""
    dmin, dmax = dt.date(9999, 1, 1), dt.date(1, 1, 1)
    for csv, cols in (("sales.csv", ["sale_date"]),
                      ("orders.csv", ["order_date", "estimated_delivery"])):
        df = pd.read_csv(os.path.join(SRC, csv), dtype=str, keep_default_na=False)
        for c in cols:
            for v in df[c]:
                if v:
                    d = dt.date.fromisoformat(v[:10])
                    dmin, dmax = min(dmin, d), max(dmax, d)
    rows = []
    d = dmin
    while d <= dmax:
        rows.append(d)
        d += dt.timedelta(days=1)
    names_m = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
    names_d = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    tbl = pa.table({
        "date": pa.array(rows, pa.date32()),
        "year": pa.array([d.year for d in rows], pa.int32()),
        "quarter": pa.array([(d.month - 1) // 3 + 1 for d in rows], pa.int32()),
        "month": pa.array([d.month for d in rows], pa.int32()),
        "month_name": pa.array([names_m[d.month - 1] for d in rows], pa.string()),
        "year_month": pa.array([f"{d.year}-{d.month:02d}" for d in rows], pa.string()),
        "day": pa.array([d.day for d in rows], pa.int32()),
        "day_of_week": pa.array([d.isoweekday() for d in rows], pa.int32()),
        "day_name": pa.array([names_d[d.weekday()] for d in rows], pa.string()),
        "is_weekend": pa.array([d.weekday() >= 5 for d in rows], pa.bool_()),
    })
    write_deltalake(_uri("dim_date"), tbl, mode="overwrite", storage_options=STORAGE,
                    schema_mode="overwrite")
    n = DeltaTable(_uri("dim_date"), storage_options=STORAGE).to_pyarrow_table().num_rows
    print(f"  {'dim_date':14s} rows={n}  ({dmin} .. {dmax})")
    return n


def main():
    print(f"Loading Zava Delta tables -> workspace {WS} / lakehouse {LH}")
    total = {}
    for name, (csv, spec) in SPECS.items():
        total[name] = load(name, csv, spec)
    total["dim_date"] = build_dim_date()
    print("DONE. Row counts:")
    for k, v in total.items():
        print(f"    {k} = {v}")


if __name__ == "__main__":
    main()
