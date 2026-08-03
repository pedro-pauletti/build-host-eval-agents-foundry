#!/usr/bin/env python3
"""
Give the Foundry project identity everything it needs inside Azure Databricks.

Run this once per environment. It is idempotent.

The identity that matters is the **project's** managed identity, not the Foundry account's.
A connection created with ``--auth-type project-managed-identity`` presents that identity,
and Databricks needs it registered as a service principal by its **application id** — the
value from ``az ad sp show --id <principalId> --query appId``, *not* the principalId itself.

Both mistakes surface the same way: HTTP 403 from the MCP endpoint, never 401. A 401 would
mean the token was rejected; a 403 means the token was accepted but the principal is unknown
to the workspace or is missing a grant.

Grants applied:
    workspace     workspace-access + databricks-sql-access entitlements
    catalog       USE CATALOG
    schema        USE SCHEMA, SELECT, EXECUTE
    warehouse     CAN_USE            (Genie runs its SQL here)
    genie space   CAN_RUN            (if DATABRICKS_GENIE_SPACE_ID is set)

Prereqs:
    az login  (as a Databricks workspace admin)
    DATABRICKS_HOST in .env

Usage:
    .venv\\Scripts\\python.exe data/databricks/setup_databricks_access.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _dbx import CATALOG, SCHEMA, api, warehouse_id  # noqa: E402

ACCOUNT = os.getenv("AZURE_AI_ACCOUNT_NAME", "")
PROJECT = os.getenv("AZURE_AI_PROJECT_NAME", "zava-project")
RG = os.getenv("AZURE_RESOURCE_GROUP", "")
SPACE_ID = os.getenv("DATABRICKS_GENIE_SPACE_ID", "")
APP_ID_ENV = os.getenv("FOUNDRY_PROJECT_MI_APP_ID", "")


def _az(args: list[str]) -> str:
    out = subprocess.run(["az", *args], capture_output=True, text=True, shell=True)
    if out.returncode != 0:
        sys.exit(f"az {' '.join(args)} falhou:\n{out.stderr[:300]}")
    return out.stdout.strip()


def project_mi_app_id() -> str:
    """Application id of the Foundry *project* managed identity."""
    if APP_ID_ENV:
        return APP_ID_ENV
    if not (ACCOUNT and RG):
        sys.exit("Defina FOUNDRY_PROJECT_MI_APP_ID, ou AZURE_AI_ACCOUNT_NAME + AZURE_RESOURCE_GROUP.")
    principal = _az([
        "resource", "show",
        "--ids", f"/subscriptions/{os.environ['AZURE_SUBSCRIPTION_ID']}/resourceGroups/{RG}"
                 f"/providers/Microsoft.CognitiveServices/accounts/{ACCOUNT}/projects/{PROJECT}",
        "--query", "identity.principalId", "-o", "tsv",
    ])
    # principalId is the object id; Databricks SCIM wants the application (client) id.
    return _az(["ad", "sp", "show", "--id", principal, "--query", "appId", "-o", "tsv"])


def ensure_service_principal(app_id: str) -> str:
    r = api("GET", f'/api/2.0/preview/scim/v2/ServicePrincipals?filter=applicationId eq "{app_id}"')
    r.raise_for_status()
    found = (r.json().get("Resources") or [None])[0]
    if found:
        print(f"  service principal ja existe (scim id {found['id']})")
        return found["id"]
    r = api("POST", "/api/2.0/preview/scim/v2/ServicePrincipals", data=json.dumps({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal"],
        "applicationId": app_id,
        "displayName": f"{PROJECT} (Foundry project managed identity)",
        "entitlements": [{"value": "workspace-access"}, {"value": "databricks-sql-access"}],
        "active": True,
    }))
    if not r.ok:
        sys.exit(f"criar service principal -> {r.status_code} {r.text[:300]}")
    print(f"  service principal criado (scim id {r.json()['id']})")
    return r.json()["id"]


def grant_uc(app_id: str) -> None:
    for securable, name, privs in [
        ("catalog", CATALOG, ["USE CATALOG"]),
        ("schema", f"{CATALOG}.{SCHEMA}", ["USE SCHEMA", "SELECT", "EXECUTE"]),
    ]:
        r = api("PATCH", f"/api/2.1/unity-catalog/permissions/{securable}/{name}",
                data=json.dumps({"changes": [{"principal": app_id, "add": privs}]}))
        print(f"  {','.join(privs):28s} on {securable} {name:26s} -> "
              f"{'OK' if r.ok else f'{r.status_code} {r.text[:140]}'}")


def grant_warehouse(app_id: str) -> None:
    wid = warehouse_id()
    r = api("PATCH", f"/api/2.0/permissions/warehouses/{wid}", data=json.dumps({
        "access_control_list": [{"service_principal_name": app_id, "permission_level": "CAN_USE"}]}))
    print(f"  CAN_USE on warehouse {wid:26s} -> {'OK' if r.ok else f'{r.status_code} {r.text[:140]}'}")


def grant_genie(app_id: str) -> None:
    if not SPACE_ID:
        print("  (DATABRICKS_GENIE_SPACE_ID nao definido — pule ate criar o space)")
        return
    r = api("PATCH", f"/api/2.0/permissions/genie/{SPACE_ID}", data=json.dumps({
        "access_control_list": [{"service_principal_name": app_id, "permission_level": "CAN_RUN"}]}))
    print(f"  CAN_RUN on genie space {SPACE_ID[:12]}...      -> "
          f"{'OK' if r.ok else f'{r.status_code} {r.text[:140]}'}")


def main() -> None:
    app_id = project_mi_app_id()
    print(f"identidade do projeto Foundry (applicationId): {app_id}\n")
    ensure_service_principal(app_id)
    grant_uc(app_id)
    grant_warehouse(app_id)
    grant_genie(app_id)
    print("\npronto.")


if __name__ == "__main__":
    main()
