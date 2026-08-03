#!/usr/bin/env python3
"""
Create the **InventoryAgentDatabricks** Foundry agent.

The Fabric twin of this agent (``agents/inventory-agent/create_agent.py``) reaches its
analytics engine through a first-party tool::

    MicrosoftFabricPreviewTool(fabric_dataagent_preview=FabricDataAgentToolParameters(...))

There is no equivalent Databricks tool in Foundry — the SDK has no Databricks class and the
tool catalog has no Databricks entry. So this agent goes through **MCP** instead, which is
the same mechanism the Zava toolbox and knowledge base already use::

    MCPTool(server_url="https://<workspace>/api/2.0/mcp/genie/<space_id>", ...)

That turns out to be less machinery, not more: no CustomKeys connection with magic metadata,
no separate Python 3.11 environment for a vendor SDK, and the tool can live in a toolbox.

Authentication is Microsoft Entra end to end. The connection is created with
``--auth-type project-managed-identity``, which uses the **project's** managed identity — not
the Foundry account's. That identity must be registered in Databricks as a service principal
by its **application id** (not its object id) and granted CAN_RUN on the Genie space; see
``data/databricks/setup_databricks_access.py``.

Prereqs, in order:
    1. data/databricks/load_uc_tables.py        -> the 10 Delta tables in Unity Catalog
    2. data/databricks/setup_databricks_access.py -> Foundry identity + grants
    3. data/databricks/create_genie_space.py    -> the Genie space
    4. azd ai connection create databricks-genie-mcp ... (printed by step 3)

Usage:
    .venv\\Scripts\\python.exe agents/inventory-agent-databricks/create_agent.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=False)

AGENT_NAME = os.getenv("DATABRICKS_AGENT_NAME", "InventoryAgentDatabricks")
MODEL = os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
HOST = (os.environ["DATABRICKS_HOST"]).replace("https://", "").rstrip("/")
SPACE_ID = os.environ["DATABRICKS_GENIE_SPACE_ID"]
GENIE_CONN = os.getenv("DATABRICKS_GENIE_CONNECTION_NAME", "databricks-genie-mcp")
GENIE_MCP_URL = f"https://{HOST}/api/2.0/mcp/genie/{SPACE_ID}"

INSTRUCTIONS = """\
You are the Zava analytics assistant backed by Azure Databricks.

Zava is a direct-to-consumer athletic apparel brand. The ZavaCore Field family ships in four
lines - Core, Pro, Premium and Elite - across 7 distribution centres and 3 retail stores.

Your tools come from a **Databricks Genie space** over the Zava tables in Unity Catalog
(sales, inventory, products, orders, customers, facilities, stores and a date dimension).
Genie turns a question into SQL, runs it on a serverless SQL warehouse and returns rows.

Genie is asynchronous, and this is the rule you must not break:
- `query_space_*` starts the question and often comes back before the answer is ready.
- When it does, call `poll_response_*` with the conversation_id and message_id it gave you,
  and keep polling until you have the rows.
- NEVER reply with "this may take a moment", "please hold on" or any other waiting message.
  The user only sees your final answer, so a waiting message reads as a failure. Poll instead.
- A cold serverless warehouse can add ~30 seconds to the first question. Absorb that by
  polling; only mention it if polling ultimately fails.

How to answer:
- Always call the Genie tool for numbers. Never estimate, never answer stock or revenue
  figures from your own knowledge, and never invent a SKU, facility or order id.
- Pass the user's question through largely as-is. Genie has its own instructions about the
  schema; rewriting the question into SQL-ish language usually makes its answer worse.
- Report the number first, then name the entities behind it (SKU, facility, product line,
  month). Keep it short enough to read out loud.
- You only have analytics. For company policy, returns, shipping SLAs or how-to questions,
  say that this agent covers analytics only and point the user at the InventoryAgent.
- If Genie returns no rows, say so plainly and suggest how to narrow or widen the question.
"""


def main() -> None:
    project = AIProjectClient(
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(exclude_interactive_browser_credential=True,
                                          process_timeout=30),
    )

    try:
        project.connections.get(GENIE_CONN)
    except Exception as exc:
        sys.exit(f"Connection '{GENIE_CONN}' nao encontrada ({type(exc).__name__}). "
                 f"Rode o `azd ai connection create` impresso por create_genie_space.py.")

    version = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL,
            instructions=INSTRUCTIONS,
            tools=[MCPTool(
                server_label="databricks_genie",
                server_url=GENIE_MCP_URL,
                require_approval="never",
                project_connection_id=GENIE_CONN,
            )],
        ),
    )
    print(f"{version.name} v{getattr(version, 'version', '?')}")
    print(f"  model     : {MODEL}")
    print(f"  genie MCP : {GENIE_MCP_URL}")
    print(f"  connection: {GENIE_CONN} (project managed identity)")


if __name__ == "__main__":
    main()
