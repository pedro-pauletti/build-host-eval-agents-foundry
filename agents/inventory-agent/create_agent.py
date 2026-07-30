#!/usr/bin/env python3
r"""
Create (or version) the Zava **InventoryAgent** — a Foundry *prompt agent*.

Tool architecture (this is the thing the demo teaches):

    InventoryAgent
      |
      +-- MCPTool -> **Toolbox** `zava-toolbox`      (one endpoint, many tools)
      |                 |-- mcp: zava_tools  -> live inventory / orders (Zava MCP server on ACA)
      |                 +-- mcp: zava_kb     -> **Foundry IQ** knowledge base over `zava-docs`
      |
      +-- MicrosoftFabricPreviewTool -> Fabric **Data Agent** `ZavaDataAgent` (analytics over the
                                        `ZavaSemanticModel` lakehouse semantic model)

Why a toolbox?
    A toolbox is a *versioned bundle* of tools published at a single MCP endpoint. The agent binds
    to the bundle instead of to N individual servers, so you can add/remove/reorder tools and roll
    versions **without touching the agent definition**. Tools are namespaced `<label>___<tool>`.

Why Foundry IQ instead of `AzureAISearchTool`?
    `AzureAISearchTool` issues a single raw query against an index. **Foundry IQ** (an Azure AI
    Search *knowledge base*) adds query planning, multi-source federation, reasoning and **answer
    synthesis with citations** — the agent asks a question, not a query. See
    `setup_foundry_iq_and_toolbox.py`, which must be run first.

Prerequisites:
    1. `data/documents/index_documents.py`                      -> the `zava-docs` search index
    2. `agents/inventory-agent/setup_foundry_iq_and_toolbox.py` -> knowledge base, connections, toolbox
    3. `data/semantic-model/create_data_agent.py`               -> the Fabric Data Agent (optional)

Run (repo root, venv):
    .venv\Scripts\python.exe agents/inventory-agent/create_agent.py
    .venv\Scripts\python.exe agents/inventory-agent/create_agent.py --test
    .venv\Scripts\python.exe agents/inventory-agent/create_agent.py --no-fabric   # skip Fabric tool
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(REPO, ".env"))

AGENT_NAME = "InventoryAgent"
PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"].rstrip("/")
MODEL = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")

TOOLBOX_NAME = os.environ.get("FOUNDRY_TOOLBOX_NAME", "zava-toolbox")
TOOLBOX_CONN = os.environ.get("FOUNDRY_TOOLBOX_CONNECTION_NAME", "zava-toolbox-mcp")
TOOLBOX_MCP_URL = f"{PROJECT_ENDPOINT}/toolboxes/{TOOLBOX_NAME}/mcp?api-version=v1"

KB_NAME = os.environ.get("FOUNDRY_IQ_KNOWLEDGE_BASE", "zava-kb")
KB_CONN = os.environ.get("FOUNDRY_IQ_CONNECTION_NAME", "zava-kb-mcp")
KB_MCP_URL = os.environ.get(
    "FOUNDRY_IQ_KB_MCP_URL",
    f"{os.environ['AZURE_SEARCH_ENDPOINT'].rstrip('/')}"
    f"/knowledgeBases/{KB_NAME}/mcp?api-version=2026-05-01-preview",
)

FABRIC_CONN = os.environ.get("FABRIC_DATA_AGENT_CONNECTION_NAME", "fabric_zava_dataagent")

INSTRUCTIONS = """You are **InventoryAgent**, the operations copilot for Zava — a direct-to-consumer
athletic apparel brand (the "ZavaCore Field" collection: Core, Pro, Premium, Elite lines; garments are
Tops/Tees, Shorts, Pants; sizes S/M/L/XL; colorways like Black/Orange, Charcoal/Silver, Deep Red/Red,
Teal/Orange). Inventory is stored across 7 distribution centers (Memphis, Charlotte, Seattle, Dallas,
Newark, Reno, Columbus) and sold via 3 retail stores + online.

Tool routing — read this before every answer. All Zava tools are published through the
**zava-toolbox** and are namespaced `<server>___<tool>`:

1. `zava_kb___knowledge_base_retrieve` — **Foundry IQ**. Use for ANY policy, procedure, definition or
   how-to question: returns & exchanges, shipping SLAs, reorder policy, sizing/fabric care, supplier
   onboarding, product-line overview. It returns a synthesised answer **with citations** — quote the
   cited document title. This is the ONLY source for policy. Never answer a policy question from
   memory, and never send a policy question to the Fabric Data Agent.
2. `zava_tools___*` — live operational data: `get_product_stock` (stock for a SKU across facilities),
   `get_inventory_alerts` (critical/low-stock issues), `get_line_stock` (on-hand per product line),
   `get_inventory_summary` (dashboard KPIs), `list_products`, `lookup_order`, `track_shipment`.
   Use for anything about *current* stock, alerts, orders or shipments.
3. **Fabric Data Agent** — historical/aggregate analytics from the warehouse semantic model: revenue
   by product line, sales trends over time, channel or store comparisons, top sellers by period.
   Use ONLY when the question is about *history, revenue or aggregates*. It has no policy documents
   and no live stock.

If a question spans two areas (e.g. "which line sells best and what's its reorder threshold?"), call
both tools and combine the results.

**Hard routing rule.** If the question contains any of: *policy, procedure, rule, guideline,
threshold, SLA, window, eligible/eligibility, allowed, how do we, what happens if, return, exchange,
refund, warranty, sizing, care, wash, supplier, onboarding* — you MUST call
`zava_kb___knowledge_base_retrieve` **first**, before any other tool, and answer from its result.
`zava_tools___*` returns *numbers observed in the system*, which is NOT the same as documented
policy: never infer a policy from reorder points or alert data.

Style:
- Lead with the number/answer. Mention facility names and SKUs explicitly.
- For critical stock questions, state how many alerts exist and call out the **most urgent** first.
- Never invent SKUs, quantities, or policies — use the tools. If a SKU/order isn't found, say so.

Formatting (IMPORTANT — the client renders GitHub-flavored Markdown):
- Always reply in **Markdown** with proper line breaks and short paragraphs (never a single wall of text).
- When you list multiple items with attributes (critical/low-stock alerts, per-facility stock, product-line
  breakdowns, supplier lists), present them as a **Markdown table** with clear headers, e.g.
  `| SKU | Product | Facility | On hand | Reorder | Days to stockout |`. Keep tables compact (≈8 rows max)
  and offer to show more.
- Use **bold** for key numbers, bullet lists for non-tabular points, and cite the source for policy answers.
"""


def build_tools(client: AIProjectClient, with_fabric: bool = True) -> list:
    """
    One MCP tool for the whole toolbox, plus the Fabric Data Agent tool.

    The Fabric tool cannot go inside the toolbox: `ToolboxToolType` currently only exposes
    `fabric_iq_preview`, not the `fabric_dataagent_preview` type used here.
    """
    tools: list = [
        MCPTool(
            server_label="zava_toolbox",
            server_url=TOOLBOX_MCP_URL,
            require_approval="never",
            # Connection NAME (not ARM id): lets the *project managed identity* authenticate,
            # so no bearer token is ever stored in the agent definition.
            project_connection_id=TOOLBOX_CONN,
        ),
        # --- Foundry IQ knowledge base -------------------------------------------------------
        # NOTE (preview limitation): the knowledge base IS also declared inside `zava-toolbox`,
        # but when the toolbox endpoint is enumerated by the project managed identity the nested
        # KB tool is silently dropped from `mcp_list_tools` (it shows up fine with a user token).
        # Until that is fixed, bind the knowledge base **directly** on the agent as well — this
        # path is fully supported and is what actually makes Foundry IQ callable.
        MCPTool(
            server_label="zava_kb",
            server_url=KB_MCP_URL,
            require_approval="never",
            allowed_tools=["knowledge_base_retrieve"],
            project_connection_id=KB_CONN,
        ),
    ]
    if not with_fabric:
        return tools

    try:
        from azure.ai.projects.models import (  # type: ignore
            MicrosoftFabricPreviewTool, FabricDataAgentToolParameters,
        )

        client.connections.get(FABRIC_CONN)
        tools.append(MicrosoftFabricPreviewTool(
            fabric_dataagent_preview=FabricDataAgentToolParameters(
                project_connections=[{"project_connection_id": FABRIC_CONN}]
            )
        ))
        print(f"  + Fabric Data Agent tool via connection '{FABRIC_CONN}'")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Skipping Fabric Data Agent tool ({type(exc).__name__}: {exc})")
    return tools


def create_agent(client: AIProjectClient, with_fabric: bool = True):
    print(f"Toolbox MCP endpoint: {TOOLBOX_MCP_URL}")
    agent = client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL,
            instructions=INSTRUCTIONS,
            tools=build_tools(client, with_fabric),
        ),
    )
    print(f"Created/updated agent '{agent.name}' version {getattr(agent, 'version', '?')}")
    return agent


def smoke_test(client: AIProjectClient):
    """One question per capability — toolbox MCP, Foundry IQ, Fabric Data Agent."""
    oai = client.get_openai_client()
    for label, q in [
        ("MCP (live)", "What are my most critical stock issues right now?"),
        ("MCP (live)", "How many units of ZCPTM-SS-S-B0 do we have across facilities?"),
        ("Foundry IQ", "What's our return policy for worn or opened apparel? Cite the source."),
        ("Fabric", "What is total revenue by product line?"),
    ]:
        print("\n" + "=" * 70 + f"\n[{label}] Q: {q}")
        resp = oai.responses.create(
            model=MODEL,
            input=q,
            extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
        )
        print("A:", resp.output_text)


def main():
    client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())
    if "--test-only" in sys.argv:
        smoke_test(client)
        return
    create_agent(client, with_fabric="--no-fabric" not in sys.argv)
    if "--test" in sys.argv:
        smoke_test(client)


if __name__ == "__main__":
    main()
