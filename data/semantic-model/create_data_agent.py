#!/usr/bin/env python3
"""
Create + configure + publish the **ZavaDataAgent** Fabric Data Agent over the
ZavaSemanticModel, using the official `fabric-data-agent-sdk` (preview).

The script is **idempotent**: if the agent already exists it is reused and
re-configured, so you can safely re-run it after editing the instructions or the
few-shot examples below.

    # the SDK requires Python 3.10-3.12 (it does not support 3.13 yet)
    uv venv --python 3.11 .venv-fabric
    uv pip install --python .venv-fabric\\Scripts\\python.exe fabric-data-agent-sdk azure-identity
    .venv-fabric\\Scripts\\python.exe data/semantic-model/create_data_agent.py

Auth: uses AzureCliCredential (you are already `az login`-ed). No secrets in code.

Note on the SDK surface: the convenience helpers (`get_datasources()`,
`update_configuration()`, `publish()`) route through a *legacy* endpoint that only
resolves inside a Fabric notebook (it imports `synapse.ml.fabric`). Running from a
laptop we therefore drive the modern **staging** REST surface directly
(`update_settings`, `add_staging_datasource`, `patch_staging_element`,
`post_staging_fewshot`, `publish_staging`), which is fully supported outside Fabric.

Environment parameterization (dev/test/prod):
    FABRIC_WORKSPACE_ID    required  (e.g. the Zava-Demos workspace)
    SEMANTIC_MODEL_NAME    default ZavaSemanticModel
    DATA_AGENT_NAME        default ZavaDataAgent
"""
from __future__ import annotations

import os
import time

WS = os.environ["FABRIC_WORKSPACE_ID"]
SM = os.environ.get("SEMANTIC_MODEL_NAME", "ZavaSemanticModel")
AGENT = os.environ.get("DATA_AGENT_NAME", "ZavaDataAgent")

AGENT_INSTRUCTIONS = """You are ZavaDataAgent, the analytics copilot for Zava, a direct-to-consumer
athletic apparel brand (the "ZavaCore Field" collection: Core, Pro, Premium and Elite product lines;
garments are Tops/Tees, Shorts and Pants; genders Mens/Womens/Youth; sizes S/M/L/XL; colourways such as
Black/Orange, Charcoal/Silver, Deep Red/Red and Teal/Orange). You answer questions over the
ZavaSemanticModel, a Direct Lake star schema.

Model contents:
- Sales fact (online + in-store). Measures: Total Revenue, Total Units, Avg Discount %, Avg Selling Price.
- Inventory fact (SKU x facility). Measures: Total On-Hand, Total Available, Avg Days-to-Stockout,
  Critical or Low SKU Count, SKUs Below Reorder Point.
- Orders / Order Items fulfilment facts. Measures: Total Orders, Delayed Orders, Total Order Value.
- Dimensions: Products (product line, garment, gender, cut, size, colour, price), Product Lines (tier),
  Facilities (7 distribution centres), Stores (3 retail stores), Customers, Calendar (date dimension).

Guidance:
- Always prefer the predefined measures over summing base columns.
- The date dimension is named **Calendar**, not Date ("Date" is a reserved DAX keyword).
- "Product line" = Products[Product Line]; "facility" / "distribution centre" = Facilities; "store" = Stores.
- Online sales have no store. Inventory status values are 'in stock', 'low stock' and 'critical'.
- Order status values are processing, in_transit, out_for_delivery, delivered, delayed and exception.
- Lead with the number, then one or two sentences of explanation. Render multi-row answers as a
  markdown table. Keep answers concise.
- Never invent SKUs, quantities or policies - answer only from the model. If the model cannot answer
  the question, say so explicitly.
"""

# Fabric rejects the /fewshots endpoint for SemanticModel data sources
# ("Few shot examples are not supported for SemanticModel data sources"), so the
# NL -> DAX exemplars are folded into the data-source instructions instead.
DATASOURCE_INSTRUCTIONS = """This Direct Lake model is the source of truth for Zava sales, inventory
and fulfilment. Use the predefined measures for aggregations instead of summing base columns, and
filter time ranges through the Calendar table rather than raw date columns on the facts.

Reference NL -> DAX patterns:
- "total revenue and units" ->
  EVALUATE ROW("Total Revenue", [Total Revenue], "Total Units", [Total Units])
- "revenue and units by product line" ->
  EVALUATE SUMMARIZECOLUMNS(Products[Product Line], "Revenue", [Total Revenue], "Units", [Total Units])
- "which distribution centre has the most critical or low-stock SKUs" ->
  EVALUATE TOPN(1, SUMMARIZECOLUMNS(Facilities[Facility Name], "CritLow", [Critical or Low SKU Count]), [CritLow], DESC)
- "total on-hand inventory and average days to stockout" ->
  EVALUATE ROW("On Hand", [Total On-Hand], "Avg Days To Stockout", [Avg Days-to-Stockout])
- "delayed orders by customer" ->
  EVALUATE FILTER(SUMMARIZECOLUMNS(Customers[Last Name], "Delayed", [Delayed Orders]), [Delayed] > 0)
- "top 5 selling SKUs by revenue" ->
  EVALUATE TOPN(5, SUMMARIZECOLUMNS(Products[Product Name], "Revenue", [Total Revenue]), [Revenue], DESC)
- "monthly revenue trend" ->
  EVALUATE TOPN(6, SUMMARIZECOLUMNS(Calendar[Year], Calendar[Month], "Revenue", [Total Revenue]), Calendar[Year], DESC, Calendar[Month], DESC)
"""


def _auth_outside_fabric() -> None:
    """No-op inside a Fabric notebook; sets AzureCliCredential when run locally."""
    try:
        from azure.identity import AzureCliCredential
        from fabric.analytics.environment.credentials import (
            SetFabricAnalyticsDefaultTokenCredentialsGlobally,
        )
        SetFabricAnalyticsDefaultTokenCredentialsGlobally(AzureCliCredential())
        print("Auth: AzureCliCredential set as Fabric default.")
    except Exception as e:  # inside Fabric, or module layout differs
        print(f"Auth: skipping explicit credential setup ({e}).")


def _get_or_create(name: str):
    """`create_data_agent` returns the existing agent when the name is taken, so a
    plain constructor attempt first keeps the output clean and the run idempotent."""
    from fabric.dataagent.client import FabricDataAgentManagement, create_data_agent

    try:
        agent = FabricDataAgentManagement(name, WS)
        agent.get_settings()  # forces a real call so a missing agent fails here
        print(f"Reusing existing data agent '{name}'.")
        return agent
    except Exception:
        print(f"Creating data agent '{name}' in workspace {WS} ...")
        create_data_agent(name, workspace_id=WS)
        return FabricDataAgentManagement(name, WS)


def _wait_for_datasource(client, display_name: str, timeout: int = 180) -> dict:
    """`add_staging_datasource` is asynchronous (HTTP 202); poll until it lands."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ds in client.get_staging_datasources().get("value", []):
            if ds.get("displayName") == display_name:
                return ds
        time.sleep(5)
    raise TimeoutError(f"datasource '{display_name}' did not appear within {timeout}s")


def _select_all_elements(client, ds_id: str) -> int:
    """A freshly attached semantic model has every element unselected, which leaves
    the agent with nothing to query. Select each table and its sub-elements."""
    count = 0

    def walk(root_id: str | None) -> None:
        nonlocal count
        token = None
        while True:
            page = client.get_staging_elements(ds_id, root_id=root_id, continuation_token=token)
            for el in page.get("value", []):
                if not el.get("isSelected"):
                    client.patch_staging_element(ds_id, el["id"], {"isSelected": True})
                count += 1
                if el.get("hasSubElements"):
                    walk(el["id"])
            token = page.get("continuationToken")
            if not token:
                return

    walk(None)
    return count


def main() -> None:
    _auth_outside_fabric()

    agent = _get_or_create(AGENT)
    client = agent._client

    agent.update_settings(ai_instructions=AGENT_INSTRUCTIONS)
    print("  agent instructions set")

    attached = {d.get("displayName") for d in client.get_staging_datasources().get("value", [])}
    if SM not in attached:
        agent.add_staging_datasource(SM, workspace_id_or_name=WS, type="semantic_model")
        print(f"  semantic model '{SM}' attached (async) ...")
    ds = _wait_for_datasource(client, SM)
    ds_id = ds["id"]
    print(f"  datasource ready: {ds_id}")

    client.patch_staging_datasource(ds_id, {"instructions": DATASOURCE_INSTRUCTIONS})
    print(f"  datasource instructions set; {_select_all_elements(client, ds_id)} elements selected")

    client.publish_staging(description="Zava sales/inventory/orders analytics.")
    print("  published")

    print(f"\nFABRIC_WORKSPACE_ID={WS}")
    print(f"FABRIC_DATA_AGENT_NAME={AGENT}")


if __name__ == "__main__":
    main()
