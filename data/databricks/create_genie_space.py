#!/usr/bin/env python3
"""
Create (or update) the Zava Genie space over the Unity Catalog tables.

This is the Databricks counterpart of ``data/semantic-model/create_data_agent.py``. A Genie
space is Databricks' natural-language-to-SQL surface over a curated set of tables — the same
role the Fabric Data Agent plays over the Direct Lake semantic model.

The instructions are deliberately close to the Fabric Data Agent's, so a question asked of
both engines is answered under the same rules and the comparison is about plumbing rather
than prompt quality.

``serialized_space`` is a versioned export proto whose shape is undocumented. It is:

    {"version": 2,
     "data_sources": {"tables": [{"identifier": "cat.schema.table"}, ...]},
     "instructions": {"text_instructions": [{"content": ["line", "line", ...]}]}}

Two constraints give unhelpful errors when broken: ``data_sources.tables`` must be sorted by
identifier, and ``text_instructions`` is a *list* whose ``content`` is a *list of strings*.

Prereqs:
    az login
    data/databricks/load_uc_tables.py has been run
    DATABRICKS_HOST in .env

Usage:
    .venv\\Scripts\\python.exe data/databricks/create_genie_space.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _dbx import CATALOG, HOST, SCHEMA, api, warehouse_id  # noqa: E402

SPACE_TITLE = os.getenv("DATABRICKS_GENIE_SPACE_NAME", "Zava Analytics")
FOUNDRY_PROJECT_MI = os.getenv("FOUNDRY_PROJECT_MI_APP_ID", "")

TABLES = sorted(
    f"{CATALOG}.{SCHEMA}.{t}" for t in
    ["product_lines", "facilities", "stores", "customers", "products",
     "inventory", "sales", "orders", "order_items", "dim_date"]
)

DESCRIPTION = (
    "Analytics over Zava's retail apparel business: sales and revenue, current stock "
    "positions across seven distribution centres, and customer order fulfilment."
)

INSTRUCTIONS = [
    "You answer analytical questions about Zava, a direct-to-consumer athletic apparel brand. "
    "The product family is ZavaCore Field, sold in four lines: Core (line_code C), Pro (R), "
    "Premium (P) and Elite (E).",

    "Revenue always comes from sales.revenue, which is already net of discount. Never recompute "
    "it as quantity * unit_price.",

    "Units sold come from sales.quantity; stock on hand comes from inventory.on_hand. Never mix "
    "the two: 'how much did we sell' is sales, 'how much do we have' is inventory.",

    "Facilities are identified by code: FC-MEM Memphis, FC-CLT Charlotte, FC-SEA Seattle, "
    "FC-DFW Dallas, FC-EWR Newark, FC-RNO Reno, FC-CMH Columbus. Users say city names, so "
    "translate the city to its code before filtering.",

    "inventory.status is exactly one of 'in stock', 'low stock', 'critical' - with spaces, not "
    "underscores.",

    "A SKU is at risk when on_hand is at or below reorder_point; projected_stockout_days = 0 "
    "means it is already out of stock.",

    "For time analysis join sales.sale_date or orders.order_date to dim_date.date.",

    "sales.store_code is NULL for online sales, so exclude NULLs when comparing stores.",

    "Answer with the numbers and name the entities involved. If a question is about policy, "
    "procedures or how something should be done, say that this space only covers analytics.",
]


def serialized_space() -> str:
    return json.dumps({
        "version": 2,
        "data_sources": {"tables": [{"identifier": t} for t in TABLES]},
        "instructions": {"text_instructions": [{"content": INSTRUCTIONS}]},
    })


def find_space() -> dict | None:
    r = api("GET", "/api/2.0/genie/spaces")
    if not r.ok:
        return None
    return next((s for s in r.json().get("spaces") or [] if s.get("title") == SPACE_TITLE), None)


def grant_foundry_access(space_id: str) -> None:
    """Without CAN_RUN the Foundry agent reaches the space and gets a 403 back from Genie."""
    if not FOUNDRY_PROJECT_MI:
        print("   (FOUNDRY_PROJECT_MI_APP_ID nao definido — conceda CAN_RUN manualmente)")
        return
    r = api("PATCH", f"/api/2.0/permissions/genie/{space_id}", data=json.dumps({
        "access_control_list": [
            {"service_principal_name": FOUNDRY_PROJECT_MI, "permission_level": "CAN_RUN"}
        ]
    }))
    print(f"   CAN_RUN para {FOUNDRY_PROJECT_MI} -> "
          f"{'OK' if r.ok else f'{r.status_code} {r.text[:200]}'}")


def main() -> None:
    space = find_space()
    body = {
        "title": SPACE_TITLE,
        "description": DESCRIPTION,
        "warehouse_id": warehouse_id(),
        "serialized_space": serialized_space(),
    }

    if space:
        sid = space["space_id"]
        r = api("PATCH", f"/api/2.0/genie/spaces/{sid}", data=json.dumps(body))
        print(f"atualizado '{SPACE_TITLE}' ({sid}) -> {r.status_code}")
        if not r.ok:
            sys.exit(r.text[:400])
    else:
        r = api("POST", "/api/2.0/genie/spaces", data=json.dumps(body))
        if not r.ok:
            sys.exit(f"POST -> {r.status_code} {r.text[:400]}")
        sid = r.json()["space_id"]
        print(f"criado '{SPACE_TITLE}' ({sid})")

    print(f"   {len(TABLES)} tabelas · {len(INSTRUCTIONS)} blocos de instrucao")
    grant_foundry_access(sid)

    print("\nMCP endpoint (e o que o agente Foundry consome):")
    print(f"   https://{HOST}/api/2.0/mcp/genie/{sid}")
    print(f"\nGrave no .env:\n   DATABRICKS_GENIE_SPACE_ID={sid}")


if __name__ == "__main__":
    main()
