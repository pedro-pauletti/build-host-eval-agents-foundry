from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class ProductLine(BaseModel):
    line_code: str
    product_line: str
    tier_rank: int
    channel: str


class Facility(BaseModel):
    facility_code: str
    name: str
    city: str
    state: str
    type: str


class Store(BaseModel):
    store_code: str
    name: str
    city: str
    state: str
    channel: str


class Product(BaseModel):
    sku: str
    product_line: str
    line_code: str
    garment: str
    gender: str
    cut: str
    size: str
    size_label: str
    color_code: str
    color_name: str
    name: str
    channel: str
    unit_cost: float
    unit_price: float
    active: bool


class InventoryItem(BaseModel):
    sku: str
    facility_code: str
    on_hand: int
    reserved: int
    available: int
    reorder_point: int
    safety_stock: int
    projected_stockout_days: int
    status: str
    bin_location: str
    product: Product | None = None
    facility_name: str | None = None


class OrderItem(BaseModel):
    order_id: str
    sku: str
    name: str
    quantity: int
    unit_price: float
    line_total: float


class Order(BaseModel):
    order_id: str
    customer_id: str
    recipient_name: str
    order_date: str
    channel: str
    ship_from_facility: str
    carrier: str
    tracking_number: str
    status: str
    status_label: str
    estimated_delivery: str
    last_location: str
    deliver_city: str
    deliver_state: str
    deliver_zip: str
    delay_reason: str = ""
    notes: str = ""
    last_updated: str
    order_total: float
    item_count: int
    delivering_to: str


class OrderDetail(Order):
    items: list[OrderItem]


class StockFacility(BaseModel):
    facility_code: str
    facility_name: str | None = None
    on_hand: int
    reserved: int
    available: int
    reorder_point: int
    safety_stock: int
    projected_stockout_days: int
    status: str
    bin_location: str
    cost_value: float
    retail_value: float


class ProductStock(BaseModel):
    sku: str
    name: str
    product_line: str
    line_code: str
    facilities: list[StockFacility]
    totals: dict[str, float]


class InventoryAlert(BaseModel):
    sku: str
    name: str
    product_line: str
    line_code: str
    facility_code: str
    facility_name: str
    on_hand: int
    reorder_point: int
    projected_stockout_days: int
    status: str
    shortfall: int


class InventorySummary(BaseModel):
    product_lines: int
    total_skus: int
    facilities: int
    retail_stores: int
    status_counts: dict[str, int]
    by_line: list[dict]


class LineStock(BaseModel):
    line_code: str
    product_line: str
    on_hand: int
    status_counts: dict[str, int]


class SalesCategoryBreakdown(BaseModel):
    product_line: str
    garment: str | None = None
    gender: str | None = None
    revenue: float
    units: int


class SalesAnalytics(BaseModel):
    days: int
    line: str | None = None
    garment: str | None = None
    gender: str | None = None
    start_date: str
    end_date: str
    total_revenue: float
    units: int
    breakdown: list[SalesCategoryBreakdown]


class ZavaData:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.product_lines: list[dict] = []
        self.facilities: list[dict] = []
        self.stores: list[dict] = []
        self.products: list[dict] = []
        self.customers: list[dict] = []
        self.inventory: list[dict] = []
        self.sales: list[dict] = []
        self.orders: list[dict] = []
        self.order_items: list[dict] = []
        self.product_lines_by_code: dict[str, dict] = {}
        self.facilities_by_code: dict[str, dict] = {}
        self.products_by_sku: dict[str, dict] = {}
        self.inventory_by_sku: dict[str, list[dict]] = defaultdict(list)
        self.orders_by_id: dict[str, dict] = {}
        self.orders_by_tracking: dict[str, dict] = {}
        self.items_by_order: dict[str, list[dict]] = defaultdict(list)
        self.load()

    def _read_csv(self, name: str) -> list[dict]:
        path = self.data_dir / name
        if not path.exists():
            raise RuntimeError(f"Missing seed data file: {path}")
        with path.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def load(self) -> None:
        self.product_lines = [self._coerce_product_line(r) for r in self._read_csv("product_lines.csv")]
        self.facilities = self._read_csv("facilities.csv")
        self.stores = self._read_csv("stores.csv")
        self.products = [self._coerce_product(r) for r in self._read_csv("products.csv")]
        self.customers = self._read_csv("customers.csv")
        self.inventory = [self._coerce_inventory(r) for r in self._read_csv("inventory.csv")]
        self.sales = [self._coerce_sale(r) for r in self._read_csv("sales.csv")]
        self.orders = [self._coerce_order(r) for r in self._read_csv("orders.csv")]
        self.order_items = [self._coerce_order_item(r) for r in self._read_csv("order_items.csv")]
        self.product_lines_by_code = {r["line_code"]: r for r in self.product_lines}
        self.facilities_by_code = {r["facility_code"]: r for r in self.facilities}
        self.products_by_sku = {r["sku"]: r for r in self.products}
        self.orders_by_id = {str(r["order_id"]): r for r in self.orders}
        self.orders_by_tracking = {r["tracking_number"]: r for r in self.orders}
        for row in self.inventory:
            self.inventory_by_sku[row["sku"]].append(row)
        for row in self.order_items:
            self.items_by_order[str(row["order_id"])].append(row)

    @staticmethod
    def _coerce_product_line(row: dict) -> dict:
        return row | {"tier_rank": int(row["tier_rank"])}

    @staticmethod
    def _coerce_product(row: dict) -> dict:
        return row | {"unit_cost": float(row["unit_cost"]), "unit_price": float(row["unit_price"]), "active": row["active"].lower() == "true"}

    @staticmethod
    def _coerce_inventory(row: dict) -> dict:
        numeric = {k: int(row[k]) for k in ("on_hand", "reserved", "available", "reorder_point", "safety_stock", "projected_stockout_days")}
        return row | numeric

    @staticmethod
    def _coerce_sale(row: dict) -> dict:
        return row | {"quantity": int(row["quantity"]), "unit_price": float(row["unit_price"]), "discount_pct": float(row["discount_pct"]), "revenue": float(row["revenue"])}

    @staticmethod
    def _coerce_order(row: dict) -> dict:
        order = row | {"order_id": str(row["order_id"]), "order_total": float(row["order_total"]), "item_count": int(row["item_count"])}
        order["delivering_to"] = f"{order['deliver_city']}, {order['deliver_state']} {order['deliver_zip']}"
        return order

    @staticmethod
    def _coerce_order_item(row: dict) -> dict:
        return row | {"order_id": str(row["order_id"]), "quantity": int(row["quantity"]), "unit_price": float(row["unit_price"]), "line_total": float(row["line_total"])}

    def counts(self) -> dict[str, int]:
        return {name: len(getattr(self, name)) for name in ("product_lines", "facilities", "stores", "products", "customers", "inventory", "sales", "orders", "order_items")}


def resolve_data_dir() -> Path:
    return Path(os.environ.get("ZAVA_DATA_DIR", str(Path(__file__).parent / "seed"))).resolve()


data = ZavaData(resolve_data_dir())
app = FastAPI(title="ZavaCore Field Operational Data API", version="2.0.0", description="Athletic apparel operations API for Microsoft Foundry agent demos.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


def not_found(entity: str, key: str) -> None:
    raise HTTPException(status_code=404, detail=f"{entity} not found: {key}")


def severity_to_status(severity: str) -> str:
    value = severity.strip().lower()
    if value == "low":
        return "low stock"
    if value == "critical":
        return "critical"
    return value


@app.get("/health", tags=["health"])
def health() -> dict:
    """Return service health, data directory, and loaded entity counts."""
    return {"status": "ok", "data_dir": str(data.data_dir), "counts": data.counts()}


@app.get("/product-lines", response_model=list[ProductLine], tags=["catalog"])
def product_lines() -> list[dict]:
    """List ZavaCore Field product lines."""
    return sorted(data.product_lines, key=lambda r: r["tier_rank"])


@app.get("/products", response_model=list[Product], tags=["catalog"])
def list_products(line: str = "", garment: str = "", gender: str = "", size: str = "", active: bool | None = None) -> list[dict]:
    """List products filtered by line code/name, garment, gender, size, and active flag."""
    rows = data.products
    if line:
        lv = line.strip().lower()
        words = set(lv.replace("-", " ").split())
        rows = [r for r in rows
                if r["line_code"].lower() == lv
                or r["product_line"].lower() == lv
                or r["product_line"].lower().split()[-1] in words]
    if garment:
        rows = [r for r in rows if r["garment"].lower() == garment.lower()]
    if gender:
        rows = [r for r in rows if r["gender"].lower() == gender.lower()]
    if size:
        rows = [r for r in rows if r["size"].lower() == size.lower() or r["size_label"].lower() == size.lower()]
    if active is not None:
        rows = [r for r in rows if r["active"] is active]
    return rows


@app.get("/products/{sku}", response_model=Product, tags=["catalog"])
def get_product(sku: str) -> dict:
    """Get a product by SKU."""
    product = data.products_by_sku.get(sku)
    if not product:
        not_found("product", sku)
    return product


@app.get("/products/{sku}/stock", response_model=ProductStock, tags=["inventory"])
def product_stock(sku: str) -> dict:
    """Get per-facility stock and total units/value for a SKU."""
    product = data.products_by_sku.get(sku)
    if not product:
        not_found("product", sku)
    facilities = []
    totals = {"on_hand": 0, "reserved": 0, "available": 0, "cost_value": 0.0, "retail_value": 0.0}
    for item in data.inventory_by_sku.get(sku, []):
        facility = data.facilities_by_code.get(item["facility_code"], {})
        cost_value = round(item["on_hand"] * product["unit_cost"], 2)
        retail_value = round(item["available"] * product["unit_price"], 2)
        facilities.append(item | {"facility_name": facility.get("name"), "cost_value": cost_value, "retail_value": retail_value})
        totals["on_hand"] += item["on_hand"]
        totals["reserved"] += item["reserved"]
        totals["available"] += item["available"]
        totals["cost_value"] += cost_value
        totals["retail_value"] += retail_value
    totals["cost_value"] = round(totals["cost_value"], 2)
    totals["retail_value"] = round(totals["retail_value"], 2)
    return {"sku": sku, "name": product["name"], "product_line": product["product_line"], "line_code": product["line_code"], "facilities": facilities, "totals": totals}


@app.get("/inventory", response_model=list[InventoryItem], tags=["inventory"])
def list_inventory(sku: str = "", facility: str = "", status: str = "") -> list[dict]:
    """List inventory rows filtered by SKU, facility, and status."""
    rows = data.inventory
    if sku:
        rows = [r for r in rows if r["sku"] == sku]
    if facility:
        rows = [r for r in rows if r["facility_code"] == facility]
    if status:
        target = severity_to_status(status)
        rows = [r for r in rows if r["status"].lower() == target]
    return [r | {"product": data.products_by_sku.get(r["sku"]), "facility_name": data.facilities_by_code.get(r["facility_code"], {}).get("name")} for r in rows]


@app.get("/inventory/alerts", response_model=list[InventoryAlert], tags=["inventory"])
def inventory_alerts(facility: str = "", severity: Annotated[str, Query(pattern="^(critical|low)?$")] = "") -> list[dict]:
    """Return urgent inventory alerts at or under reorder point, sorted by soonest stockout."""
    target_status = severity_to_status(severity) if severity else ""
    alerts = []
    for item in data.inventory:
        if facility and item["facility_code"] != facility:
            continue
        if item["on_hand"] > item["reorder_point"]:
            continue
        if target_status and item["status"].lower() != target_status:
            continue
        product = data.products_by_sku[item["sku"]]
        facility_row = data.facilities_by_code[item["facility_code"]]
        alerts.append({"sku": item["sku"], "name": product["name"], "product_line": product["product_line"], "line_code": product["line_code"], "facility_code": item["facility_code"], "facility_name": facility_row["name"], "on_hand": item["on_hand"], "reorder_point": item["reorder_point"], "projected_stockout_days": item["projected_stockout_days"], "status": item["status"], "shortfall": item["reorder_point"] - item["on_hand"]})
    return sorted(alerts, key=lambda r: (r["projected_stockout_days"], -r["shortfall"], r["facility_code"], r["sku"]))


@app.get("/inventory/summary", response_model=InventorySummary, tags=["inventory"])
def inventory_summary() -> dict:
    """Return dashboard KPIs and status counts by line."""
    statuses = ["in stock", "low stock", "critical"]
    counts = {s: 0 for s in statuses}
    by_line: dict[str, dict] = {}
    for line in data.product_lines:
        by_line[line["line_code"]] = {"line_code": line["line_code"], "product_line": line["product_line"], "channel": line["channel"], "status_counts": {s: 0 for s in statuses}, "on_hand": 0}
    for item in data.inventory:
        product = data.products_by_sku[item["sku"]]
        status = item["status"]
        counts[status] = counts.get(status, 0) + 1
        line = by_line[product["line_code"]]
        line["status_counts"][status] = line["status_counts"].get(status, 0) + 1
        line["on_hand"] += item["on_hand"]
    return {"product_lines": len(data.product_lines), "total_skus": len(data.products), "facilities": len(data.facilities), "retail_stores": len(data.stores), "status_counts": counts, "by_line": list(by_line.values())}


@app.get("/inventory/by-line/{line_code}", response_model=LineStock, tags=["inventory"])
def inventory_by_line(line_code: str) -> dict:
    """Return total on-hand units and status counts for one product line (by code OR name)."""
    key = (line_code or "").strip()
    line = data.product_lines_by_code.get(key.upper())
    if not line:
        words = set(key.lower().replace("-", " ").split())
        for pl in data.product_lines:
            name = pl["product_line"].lower()          # e.g. "zavacore field elite"
            if key.lower() == name or name.split()[-1] in words:  # tier as a whole word
                line = pl
                break
    if not line:
        not_found("product line", line_code)
    counts = {"in stock": 0, "low stock": 0, "critical": 0}
    on_hand = 0
    for item in data.inventory:
        product = data.products_by_sku[item["sku"]]
        if product["line_code"] == line["line_code"]:
            on_hand += item["on_hand"]
            counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"line_code": line["line_code"], "product_line": line["product_line"], "on_hand": on_hand, "status_counts": counts}


@app.get("/facilities", response_model=list[Facility], tags=["locations"])
def facilities() -> list[dict]:
    """List distribution facilities."""
    return data.facilities


@app.get("/stores", response_model=list[Store], tags=["locations"])
def stores() -> list[dict]:
    """List retail stores."""
    return data.stores


@app.get("/orders/{order_id}", response_model=OrderDetail, tags=["orders"])
def get_order(order_id: str) -> dict:
    """Get a tracking-card-ready order with line items."""
    order = data.orders_by_id.get(str(order_id))
    if not order:
        not_found("order", str(order_id))
    return order | {"items": data.items_by_order.get(str(order_id), [])}


@app.get("/orders", response_model=list[Order], tags=["orders"])
def list_orders(customer_id: str = "", status: str = "", limit: Annotated[int, Query(ge=1, le=500)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> list[dict]:
    """List orders filtered by customer/status with limit/offset pagination."""
    rows = data.orders
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows[offset: offset + limit]


@app.get("/track/{tracking_number}", response_model=OrderDetail, tags=["orders"])
def track(tracking_number: str) -> dict:
    """Track an order by carrier tracking number."""
    order = data.orders_by_tracking.get(tracking_number)
    if not order:
        not_found("tracking number", tracking_number)
    return order | {"items": data.items_by_order.get(order["order_id"], [])}


@app.get("/analytics/sales", response_model=SalesAnalytics, tags=["analytics"])
def sales_analytics(line: str = "", gender: str = "", garment: str = "", days: Annotated[int, Query(ge=1, le=365)] = 30) -> dict:
    """Return simple sales aggregates over the latest data window."""
    dates = [datetime.strptime(r["sale_date"], "%Y-%m-%d").date() for r in data.sales]
    end = max(dates) if dates else date.today()
    start = end - timedelta(days=days - 1)
    total_revenue = 0.0
    units = 0
    groups: dict[tuple[str, str, str], dict] = {}
    for row in data.sales:
        sale_date = datetime.strptime(row["sale_date"], "%Y-%m-%d").date()
        if sale_date < start or sale_date > end:
            continue
        product = data.products_by_sku.get(row["sku"], {})
        if line and product.get("line_code", "").lower() != line.lower() and row["product_line"].lower() != line.lower():
            continue
        if gender and row["gender"].lower() != gender.lower():
            continue
        if garment and row["garment"].lower() != garment.lower():
            continue
        key = (row["product_line"], row["garment"] if not garment else "", row["gender"] if not gender else "")
        group = groups.setdefault(key, {"product_line": row["product_line"], "garment": key[1] or None, "gender": key[2] or None, "revenue": 0.0, "units": 0})
        group["revenue"] += row["revenue"]
        group["units"] += row["quantity"]
        total_revenue += row["revenue"]
        units += row["quantity"]
    for group in groups.values():
        group["revenue"] = round(group["revenue"], 2)
    return {"days": days, "line": line or None, "garment": garment or None, "gender": gender or None, "start_date": start.isoformat(), "end_date": end.isoformat(), "total_revenue": round(total_revenue, 2), "units": units, "breakdown": sorted(groups.values(), key=lambda g: (g["product_line"], g.get("garment") or "", g.get("gender") or ""))}
