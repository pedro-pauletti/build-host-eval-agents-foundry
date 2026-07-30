from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

ZAVA_API_BASE_URL = os.environ.get("ZAVA_API_BASE_URL", "http://localhost:8000").rstrip("/")

mcp = FastMCP("zava-tools", host="0.0.0.0", port=8080)


def _get(path: str, params: dict[str, str] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    clean_params = {k: v for k, v in (params or {}).items() if v != ""}
    with httpx.Client(base_url=ZAVA_API_BASE_URL, timeout=10.0) as client:
        response = client.get(path, params=clean_params)
    if response.status_code == 404:
        return {"error": response.json().get("detail", "not found")}
    response.raise_for_status()
    return response.json()


@mcp.tool()
def get_product_stock(sku: str) -> dict[str, Any]:
    """Return per-facility stock and totals for a ZavaCore Field SKU."""
    return _get(f"/products/{quote(sku, safe='')}/stock")


@mcp.tool()
def get_inventory_alerts(facility: str = "", severity: str = "critical") -> dict[str, Any]:
    """Return the most critical or low-stock apparel inventory issues."""
    return {"alerts": _get("/inventory/alerts", {"facility": facility, "severity": severity})}


@mcp.tool()
def get_inventory_summary() -> dict[str, Any]:
    """Return dashboard KPIs for product lines, SKUs, facilities, stores, and stock status."""
    return _get("/inventory/summary")


@mcp.tool()
def get_line_stock(line_code: str) -> dict[str, Any]:
    """Return on-hand units and status counts for one product line code."""
    return _get(f"/inventory/by-line/{quote(line_code, safe='')}")


@mcp.tool()
def list_products(line: str = "", garment: str = "", gender: str = "") -> dict[str, Any]:
    """List products by product line, garment, and gender."""
    return {"products": _get("/products", {"line": line, "garment": garment, "gender": gender})}


@mcp.tool()
def lookup_order(order_id: str) -> dict[str, Any]:
    """Look up a full order tracking card with items for a numeric Zava order ID."""
    return _get(f"/orders/{quote(order_id, safe='')}")


@mcp.tool()
def track_shipment(order_id: str = "", tracking_number: str = "") -> dict[str, Any]:
    """Track a shipment by order ID or tracking number."""
    if tracking_number:
        return _get(f"/track/{quote(tracking_number, safe='')}")
    if order_id:
        return _get(f"/orders/{quote(order_id, safe='')}")
    return {"error": "Provide order_id or tracking_number."}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
