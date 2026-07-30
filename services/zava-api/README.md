# ZavaCore Field Operational Data API

FastAPI service for Zava's athletic apparel operational data. Canonical CSVs are maintained in `data/structured`; this service bundles a self-contained copy in `app/seed` for local and container runs.

## Run locally

```powershell
python -m venv ..\..\.venv
..\..\.venv\Scripts\python -m pip install -r requirements.txt
..\..\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Environment variables

- `ZAVA_DATA_DIR`: directory containing the Zava apparel CSVs. Defaults to bundled `app/seed`.

Refresh seed data from the canonical source:

```powershell
.\scripts\sync_seed.ps1
```

## Endpoints

- `GET /health`
- `GET /product-lines`
- `GET /products?line=&garment=&gender=&size=&active=`
- `GET /products/{sku}`
- `GET /products/{sku}/stock`
- `GET /inventory?sku=&facility=&status=`
- `GET /inventory/alerts?facility=&severity=critical|low`
- `GET /inventory/summary`
- `GET /inventory/by-line/{line_code}`
- `GET /facilities`, `GET /stores`
- `GET /orders/{order_id}`
- `GET /orders?customer_id=&status=&limit=&offset=`
- `GET /track/{tracking_number}`
- `GET /analytics/sales?line=&gender=&garment=&days=30`

OpenAPI docs are available at `/docs`.
