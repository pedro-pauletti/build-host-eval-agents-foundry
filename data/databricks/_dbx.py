"""
Shared Azure Databricks REST helpers for the Zava demo scripts.

Auth is Microsoft Entra only — no personal access tokens. The Azure Databricks service has a
fixed application ID, so ``az login`` is enough to call the workspace APIs.

Environment:
    DATABRICKS_HOST         workspace hostname, e.g. adb-1234567890.4.azuredatabricks.net
    DATABRICKS_CATALOG      Unity Catalog catalog   (default: zava_workspace)
    DATABRICKS_SCHEMA       Unity Catalog schema    (default: demo)
    DATABRICKS_WAREHOUSE_ID SQL warehouse to run statements on (default: first one found)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=False)

# Fixed application ID of the Azure Databricks service — lets an Entra token stand in for a PAT.
DBX_RESOURCE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"

HOST = (os.getenv("DATABRICKS_HOST") or "").replace("https://", "").rstrip("/")
CATALOG = os.getenv("DATABRICKS_CATALOG", "zava_workspace")
SCHEMA = os.getenv("DATABRICKS_SCHEMA", "demo")

_token: str | None = None
_warehouse: str | None = None


def _require_host() -> str:
    if not HOST:
        sys.exit("Set DATABRICKS_HOST (e.g. adb-1234567890.4.azuredatabricks.net) in .env")
    return HOST


def token() -> str:
    """Entra access token for the Azure Databricks service, cached per process."""
    global _token
    if _token is None:
        out = subprocess.run(
            ["az", "account", "get-access-token", "--resource", DBX_RESOURCE,
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, shell=True,
        )
        if out.returncode != 0:
            sys.exit(f"az account get-access-token failed — run `az login`.\n{out.stderr[:300]}")
        _token = out.stdout.strip()
    return _token


def headers(content_type: str = "application/json") -> dict[str, str]:
    return {"Authorization": f"Bearer {token()}", "Content-Type": content_type}


def api(method: str, path: str, *, timeout: int = 120, **kw) -> requests.Response:
    return requests.request(method, f"https://{_require_host()}{path}",
                            headers=headers(), timeout=timeout, **kw)


def warehouse_id() -> str:
    """The SQL warehouse used for statement execution; serverless ones auto-start on first use."""
    global _warehouse
    if _warehouse:
        return _warehouse
    _warehouse = os.getenv("DATABRICKS_WAREHOUSE_ID") or ""
    if not _warehouse:
        r = api("GET", "/api/2.0/sql/warehouses")
        r.raise_for_status()
        warehouses = r.json().get("warehouses") or []
        if not warehouses:
            sys.exit("No SQL warehouse in the workspace — create a serverless one first.")
        _warehouse = warehouses[0]["id"]
    return _warehouse


class SqlError(RuntimeError):
    pass


def sql(statement: str, *, wait: int = 50) -> dict[str, Any]:
    """Run a statement to completion via the SQL Statement Execution API."""
    r = api("POST", "/api/2.0/sql/statements", data=json.dumps({
        "warehouse_id": warehouse_id(), "statement": statement, "wait_timeout": f"{wait}s",
    }))
    if not r.ok:
        raise SqlError(f"HTTP {r.status_code}: {r.text[:400]}")
    out = r.json()
    sid = out["statement_id"]
    while out.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(3)
        out = api("GET", f"/api/2.0/sql/statements/{sid}").json()
    state = out.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise SqlError(json.dumps(out.get("status", {}))[:500])
    return out


def scalar(statement: str) -> Any:
    """First cell of the first row, or None."""
    rows = (sql(statement).get("result") or {}).get("data_array") or []
    return rows[0][0] if rows and rows[0] else None


def upload_to_volume(local: Path, volume_path: str) -> None:
    """PUT a local file into a Unity Catalog volume (Files API)."""
    url = f"https://{_require_host()}/api/2.0/fs/files{volume_path}?overwrite=true"
    r = requests.put(url, headers={"Authorization": f"Bearer {token()}",
                                   "Content-Type": "application/octet-stream"},
                     data=local.read_bytes(), timeout=300)
    if not r.ok:
        raise SqlError(f"upload {local.name} -> {r.status_code} {r.text[:300]}")


def fq(table: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{table}"
