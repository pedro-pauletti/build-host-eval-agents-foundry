#!/usr/bin/env python3
"""
Generate the TMDL definition for the Zava Direct Lake semantic model.

Direct Lake on OneLake over the ZavaLakehouse (non-schema lakehouse -> no schemaName).
Emits a full TMDL folder under ./ZavaSemanticModel/ that is deployed with deploy_semantic_model.py.

Environment parameterization (dev/test/prod) via env vars:
    FABRIC_WORKSPACE_ID   required
    FABRIC_LAKEHOUSE_ID   required
"""
from __future__ import annotations

import os

WS = os.environ["FABRIC_WORKSPACE_ID"]
LH = os.environ["FABRIC_LAKEHOUSE_ID"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ZavaSemanticModel")

T = "\t"
CUR = r"\$#,##0.00"
PCT = "0.0%"
INT = "#,##0"
DEC1 = "#,##0.0"


def q(name: str) -> str:
    """Quote a TMDL object name if it has spaces / special chars."""
    if any(c in name for c in " .=:'/") or name[0].isdigit():
        return "'" + name.replace("'", "''") + "'"
    return name


# ------------------------------------------------------------------ tables ----
# col tuple: (name, source, dataType, summarizeBy, flags dict)
def col(name, src, dt, sb="none", key=False, hidden=False, sort=None, fmt=None, desc=None):
    return dict(name=name, src=src, dt=dt, sb=sb, key=key, hidden=hidden, sort=sort, fmt=fmt, desc=desc)


def mea(name, dax, fmt, desc=None):
    return dict(name=name, dax=dax, fmt=fmt, desc=desc)


TABLES = [
    dict(name="Calendar", entity="dim_date",
         desc="Contiguous daily calendar (date dimension) derived from sales and order dates. Named 'Calendar' to avoid the DAX reserved word 'Date'.",
         columns=[
             col("Date", "date", "dateTime", key=True, desc="Calendar date (grain of the table)."),
             col("Year", "year", "int64"),
             col("Quarter", "quarter", "int64"),
             col("Month", "month", "int64"),
             col("Month Name", "month_name", "string", sort="Month"),
             col("Year Month", "year_month", "string"),
             col("Day", "day", "int64"),
             col("Day Of Week", "day_of_week", "int64"),
             col("Day Name", "day_name", "string"),
             col("Is Weekend", "is_weekend", "boolean"),
         ], measures=[]),

    dict(name="Product Lines", entity="product_lines",
         desc="ZavaCore Field product-line tiers (Core, Pro, Premium, Elite).",
         columns=[
             col("Line Code", "line_code", "string", key=True, hidden=True),
             col("Product Line", "product_line", "string", hidden=True),
             col("Tier Rank", "tier_rank", "int64", desc="1=Core .. 4=Elite."),
             col("Channel", "channel", "string", hidden=True),
         ], measures=[]),

    dict(name="Products", entity="products",
         desc="Product (SKU) dimension: line, garment, gender, cut, size, colour and price.",
         columns=[
             col("SKU", "sku", "string", key=True, hidden=True),
             col("Product Line", "product_line", "string"),
             col("Line Code", "line_code", "string", hidden=True),
             col("Garment", "garment", "string"),
             col("Gender", "gender", "string"),
             col("Cut", "cut", "string"),
             col("Size", "size", "string"),
             col("Size Label", "size_label", "string"),
             col("Color Code", "color_code", "string", hidden=True),
             col("Color Name", "color_name", "string"),
             col("Product Name", "name", "string"),
             col("Channel", "channel", "string"),
             col("Unit Cost", "unit_cost", "decimal", fmt=CUR),
             col("Unit Price", "unit_price", "decimal", fmt=CUR),
             col("Is Active", "active", "boolean"),
         ], measures=[
             mea("Product Count", "DISTINCTCOUNT(Products[SKU])", INT, "Distinct SKUs in the catalogue."),
             mea("Active Product Count", "CALCULATE(DISTINCTCOUNT(Products[SKU]), Products[Is Active] = TRUE())", INT),
         ]),

    dict(name="Facilities", entity="facilities",
         desc="Distribution centres that hold inventory and ship orders.",
         columns=[
             col("Facility Code", "facility_code", "string", key=True),
             col("Facility Name", "name", "string"),
             col("City", "city", "string"),
             col("State", "state", "string"),
             col("Type", "type", "string"),
         ], measures=[]),

    dict(name="Stores", entity="stores",
         desc="Physical Zava retail stores (in-store sales channel).",
         columns=[
             col("Store Code", "store_code", "string", key=True),
             col("Store Name", "name", "string"),
             col("City", "city", "string"),
             col("State", "state", "string"),
             col("Channel", "channel", "string"),
         ], measures=[]),

    dict(name="Customers", entity="customers",
         desc="Customers who place fulfilment orders.",
         columns=[
             col("Customer ID", "customer_id", "string", key=True),
             col("First Name", "first_name", "string"),
             col("Last Name", "last_name", "string"),
             col("Email", "email", "string"),
             col("City", "city", "string"),
             col("State", "state", "string"),
             col("Zip", "zip", "string"),
         ], measures=[]),

    dict(name="Sales", entity="sales",
         desc="Sales transaction fact (online + in-store). Grain = one sale line.",
         columns=[
             col("Sale ID", "sale_id", "string", hidden=True),
             col("Sale Date", "sale_date", "dateTime", hidden=True),
             col("Channel", "channel", "string"),
             col("Store Code", "store_code", "string", hidden=True),
             col("SKU", "sku", "string", hidden=True),
             col("Product Line", "product_line", "string", hidden=True),
             col("Garment", "garment", "string", hidden=True),
             col("Gender", "gender", "string", hidden=True),
             col("Quantity", "quantity", "int64", sb="sum"),
             col("Unit Price", "unit_price", "decimal", fmt=CUR),
             col("Discount Pct", "discount_pct", "decimal", fmt=PCT, desc="Discount fraction (0.10 = 10%)."),
             col("Revenue", "revenue", "decimal", sb="sum", fmt=CUR),
         ], measures=[
             mea("Total Revenue", "SUM(Sales[Revenue])", CUR, "Total sales revenue (net of discount)."),
             mea("Total Units", "SUM(Sales[Quantity])", INT, "Total units sold."),
             mea("Number of Sales", "COUNTROWS(Sales)", INT),
             mea("Distinct SKUs Sold", "DISTINCTCOUNT(Sales[SKU])", INT),
             mea("Avg Discount %", "AVERAGE(Sales[Discount Pct])", PCT, "Average discount fraction across sale lines."),
             mea("Avg Selling Price", "DIVIDE([Total Revenue], [Total Units])", CUR),
         ]),

    dict(name="Inventory", entity="inventory",
         desc="On-hand inventory fact by SKU x facility. Grain = one SKU at one facility.",
         columns=[
             col("SKU", "sku", "string", hidden=True),
             col("Facility Code", "facility_code", "string", hidden=True),
             col("On Hand", "on_hand", "int64", sb="sum"),
             col("Reserved", "reserved", "int64", sb="sum"),
             col("Available", "available", "int64", sb="sum"),
             col("Reorder Point", "reorder_point", "int64"),
             col("Safety Stock", "safety_stock", "int64"),
             col("Projected Stockout Days", "projected_stockout_days", "int64",
                 desc="Estimated days until this SKU stocks out at this facility."),
             col("Status", "status", "string", desc="in stock | low stock | critical."),
             col("Bin Location", "bin_location", "string"),
         ], measures=[
             mea("Total On-Hand", "SUM(Inventory[On Hand])", INT, "Total on-hand units."),
             mea("Total Available", "SUM(Inventory[Available])", INT),
             mea("Total Reserved", "SUM(Inventory[Reserved])", INT),
             mea("Avg Days-to-Stockout", "AVERAGE(Inventory[Projected Stockout Days])", DEC1,
                 "Average projected days-to-stockout across SKU/facility rows."),
             mea("Critical or Low SKU Count",
                 'CALCULATE(DISTINCTCOUNT(Inventory[SKU]), Inventory[Status] IN {"critical", "low stock"})', INT,
                 "Distinct SKUs in critical or low-stock status."),
             mea("SKUs Below Reorder Point",
                 "CALCULATE(COUNTROWS(Inventory), FILTER(Inventory, Inventory[Available] < Inventory[Reorder Point]))",
                 INT),
         ]),

    dict(name="Orders", entity="orders",
         desc="Fulfilment order header fact. Grain = one order. One side of Order Items.",
         columns=[
             col("Order ID", "order_id", "string", key=True, hidden=True),
             col("Customer ID", "customer_id", "string", hidden=True),
             col("Recipient Name", "recipient_name", "string"),
             col("Order Date", "order_date", "dateTime", hidden=True),
             col("Channel", "channel", "string"),
             col("Ship From Facility", "ship_from_facility", "string", hidden=True),
             col("Carrier", "carrier", "string"),
             col("Tracking Number", "tracking_number", "string"),
             col("Status", "status", "string", desc="processing|in_transit|out_for_delivery|delivered|delayed|exception."),
             col("Status Label", "status_label", "string"),
             col("Estimated Delivery", "estimated_delivery", "dateTime"),
             col("Last Location", "last_location", "string"),
             col("Deliver City", "deliver_city", "string"),
             col("Deliver State", "deliver_state", "string"),
             col("Deliver Zip", "deliver_zip", "string"),
             col("Delay Reason", "delay_reason", "string"),
             col("Notes", "notes", "string"),
             col("Last Updated", "last_updated", "dateTime"),
             col("Order Total", "order_total", "decimal", sb="sum", fmt=CUR),
             col("Item Count", "item_count", "int64", sb="sum"),
         ], measures=[
             mea("Total Orders", "DISTINCTCOUNT(Orders[Order ID])", INT),
             mea("Total Order Value", "SUM(Orders[Order Total])", CUR),
             mea("Avg Order Value", "DIVIDE([Total Order Value], [Total Orders])", CUR),
             mea("Delayed Orders", 'CALCULATE([Total Orders], Orders[Status] = "delayed")', INT),
             mea("Delivered Orders", 'CALCULATE([Total Orders], Orders[Status] = "delivered")', INT),
         ]),

    dict(name="Order Items", entity="order_items",
         desc="Fulfilment order line fact. Grain = one order line (order x SKU).",
         columns=[
             col("Order ID", "order_id", "string", hidden=True),
             col("SKU", "sku", "string", hidden=True),
             col("Product Name", "name", "string"),
             col("Quantity", "quantity", "int64", sb="sum"),
             col("Unit Price", "unit_price", "decimal", fmt=CUR),
             col("Line Total", "line_total", "decimal", sb="sum", fmt=CUR),
         ], measures=[
             mea("Order Line Units", "SUM('Order Items'[Quantity])", INT),
             mea("Order Line Value", "SUM('Order Items'[Line Total])", CUR),
         ]),
]

# from(many/fact).col  ->  to(one/dim).col
RELS = [
    ("Sales", "SKU", "Products", "SKU"),
    ("Sales", "Store Code", "Stores", "Store Code"),
    ("Sales", "Sale Date", "Calendar", "Date"),
    ("Inventory", "SKU", "Products", "SKU"),
    ("Inventory", "Facility Code", "Facilities", "Facility Code"),
    ("Products", "Line Code", "Product Lines", "Line Code"),
    ("Orders", "Customer ID", "Customers", "Customer ID"),
    ("Orders", "Ship From Facility", "Facilities", "Facility Code"),
    ("Orders", "Order Date", "Calendar", "Date"),
    ("Order Items", "Order ID", "Orders", "Order ID"),
    ("Order Items", "SKU", "Products", "SKU"),
]


def emit_column(c) -> list[str]:
    lines = []
    if c["desc"]:
        lines.append(f"{T}/// {c['desc']}")
    lines.append(f"{T}column {q(c['name'])}")
    lines.append(f"{T}{T}dataType: {c['dt']}")
    if c["key"]:
        lines.append(f"{T}{T}isKey")
    if c["hidden"]:
        lines.append(f"{T}{T}isHidden")
    lines.append(f"{T}{T}summarizeBy: {c['sb']}")
    lines.append(f"{T}{T}sourceColumn: {c['src']}")
    if c["sort"]:
        lines.append(f"{T}{T}sortByColumn: {q(c['sort'])}")
    if c["fmt"]:
        lines.append(f"{T}{T}formatString: {c['fmt']}")
    lines.append("")
    return lines


def emit_measure(m) -> list[str]:
    lines = []
    if m["desc"]:
        lines.append(f"{T}/// {m['desc']}")
    lines.append(f"{T}measure {q(m['name'])} = {m['dax']}")
    lines.append(f"{T}{T}formatString: {m['fmt']}")
    lines.append("")
    return lines


def emit_table(t) -> str:
    lines = []
    if t["desc"]:
        lines.append(f"/// {t['desc']}")
    lines.append(f"table {q(t['name'])}")
    lines.append("")
    for m in t["measures"]:
        lines += emit_measure(m)
    for c in t["columns"]:
        lines += emit_column(c)
    lines.append(f"{T}partition {q(t['name'])} = entity")
    lines.append(f"{T}{T}mode: directLake")
    lines.append(f"{T}{T}source")
    lines.append(f"{T}{T}{T}entityName: {t['entity']}")
    lines.append(f"{T}{T}{T}expressionSource: DL_Zava")
    lines.append("")
    return "\n".join(lines)


def emit_model() -> str:
    lines = [
        "model Model",
        f"{T}culture: en-US",
        f"{T}defaultPowerBIDataSourceVersion: powerBI_V3",
        f"{T}sourceQueryCulture: en-US",
        "",
    ]
    for t in TABLES:
        lines.append(f"ref table {q(t['name'])}")
    lines.append("")
    return "\n".join(lines)


def emit_expressions() -> str:
    url = f"https://onelake.dfs.fabric.microsoft.com/{WS}/{LH}"
    return "\n".join([
        "/// Direct Lake on OneLake connection to the ZavaLakehouse Tables area.",
        "expression DL_Zava =",
        f"{T}let",
        f'{T}{T}Source = AzureStorage.DataLake("{url}", [HierarchicalNavigation=true])',
        f"{T}in",
        f"{T}{T}Source",
        "",
    ])


def emit_relationships() -> str:
    lines = []
    for i, (ft, fc, tt, tc) in enumerate(RELS, 1):
        lines.append(f"relationship rel_{i:02d}_{ft.replace(' ', '')}_{tt.replace(' ', '')}")
        lines.append(f"{T}fromColumn: {q(ft)}.{q(fc)}")
        lines.append(f"{T}toColumn: {q(tt)}.{q(tc)}")
        lines.append("")
    return "\n".join(lines)


def main():
    os.makedirs(os.path.join(OUT, "definition", "tables"), exist_ok=True)
    write = lambda p, s: open(os.path.join(OUT, p), "w", encoding="utf-8", newline="\n").write(s)

    write("definition.pbism", '{\n  "version": "4.2",\n  "settings": {\n    "qnaEnabled": true\n  }\n}\n')
    write("definition/database.tmdl", "database\n\tcompatibilityLevel: 1702\n\tcompatibilityMode: powerBI\n")
    write("definition/model.tmdl", emit_model())
    write("definition/expressions.tmdl", emit_expressions())
    write("definition/relationships.tmdl", emit_relationships())
    for t in TABLES:
        write(f"definition/tables/{t['name']}.tmdl", emit_table(t))

    print(f"TMDL written to {OUT}")
    print(f"  tables: {len(TABLES)}  relationships: {len(RELS)}")
    total_m = sum(len(t["measures"]) for t in TABLES)
    print(f"  measures: {total_m}")


if __name__ == "__main__":
    main()
