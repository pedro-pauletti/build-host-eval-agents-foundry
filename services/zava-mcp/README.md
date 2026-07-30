# Zava MCP Server

FastMCP streamable-HTTP server for ZavaCore Field apparel demos. It calls the Zava API with `httpx` and exposes inventory and order-tracking tools for Foundry.

## Run locally

Install dependencies in a venv:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Start the API first:

```powershell
cd ..\zava-api
..\..\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Start MCP:

```powershell
cd ..\zava-mcp
.\.venv\Scripts\python server.py
```

The streamable HTTP endpoint is `http://localhost:8080/mcp`.

## Environment variables

- `ZAVA_API_BASE_URL`: base URL for the API. Defaults to `http://localhost:8000`.

## Tools

- `get_product_stock(sku)`
- `get_inventory_alerts(facility="", severity="critical")`
- `get_inventory_summary()`
- `get_line_stock(line_code)`
- `list_products(line="", garment="", gender="")`
- `lookup_order(order_id)`
- `track_shipment(order_id="", tracking_number="")`

## Test client

```powershell
.\.venv\Scripts\python test_client.py
```
