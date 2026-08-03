# Zava on Azure Databricks — the same demo, wired through MCP

This folder is the Databricks counterpart of [`../semantic-model/`](../semantic-model/) (Microsoft
Fabric). **The data is deliberately identical** — same 10 tables, same columns, same types, same row
counts — so both analytics agents answer the same questions and the only thing that differs is the
plumbing. That contrast is the point of the demo.

## Why the wiring differs

Foundry has a first-party tool for Fabric. It has **none for Databricks**: `azure-ai-projects` 2.3.0
exposes `MicrosoftFabricPreviewTool` but no Databricks class, and the Foundry tool catalog lists
*Microsoft Fabric (preview)* with no Databricks entry.

So Databricks goes through **MCP** — and Databricks ships
[managed MCP servers](https://learn.microsoft.com/en-us/azure/databricks/generative-ai/mcp/managed-mcp),
including one per Genie space. That is exactly the mechanism the Zava toolbox and knowledge base
already use, so it needs *less* machinery than the first-party path:

| | Fabric | Databricks |
|---|---|---|
| Mechanism | `MicrosoftFabricPreviewTool` (`fabric_dataagent_preview`) | `MCPTool` |
| Toolbox | ❌ can't go in one — `ToolboxToolType` only exposes `fabric_iq_preview` | ✅ can |
| Connection | `CustomKeys` carrying `metadata.type` | plain `RemoteTool` |
| Auth | project managed identity | project managed identity (Entra, **no PAT**) |
| Client SDK | `fabric-data-agent-sdk`, **Python 3.10–3.12 only** → separate venv | none |
| Compute | F8 capacity | serverless SQL warehouse, auto-stop |
| Per-principal data access | model-level | **Unity Catalog grants** |

That last row is the extra axis Databricks gives you: revoke `SELECT` from the Foundry identity and
the agent stops being able to answer, without any change to the agent.

## Run order

```powershell
az login                                             # workspace admin

.\.venv\Scripts\python.exe data/databricks/load_uc_tables.py           # 1. tables
.\.venv\Scripts\python.exe data/databricks/verify_uc_tables.py         # 2. parity with Fabric
.\.venv\Scripts\python.exe data/databricks/setup_databricks_access.py  # 3. identity + grants
.\.venv\Scripts\python.exe data/databricks/create_genie_space.py       # 4. Genie space

# 5. the connection the agent uses (URL is printed by step 4)
azd ai connection create databricks-genie-mcp `
  --kind remote-tool `
  --target "https://<workspace>/api/2.0/mcp/genie/<space_id>" `
  --auth-type project-managed-identity `
  --audience "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"

.\.venv\Scripts\python.exe agents/inventory-agent-databricks/create_agent.py   # 6. agent
.\.venv\Scripts\python.exe agents/inventory-agent-databricks/test_agent.py     # 7. smoke test
```

`2ff814a6-3304-4ab8-85cb-cd0e6f879c1d` is the fixed application id of the Azure Databricks service.
Using it as the token audience is what lets Entra stand in for a personal access token.

## Files

| File | What it does |
|---|---|
| `_dbx.py` | Entra auth + REST/SQL/Files helpers shared by the scripts |
| `load_uc_tables.py` | CSV → UC volume → `read_files` → typed Delta tables, with comments and PK/FK |
| `verify_uc_tables.py` | Asserts the loaded numbers match what the Fabric side reports |
| `setup_databricks_access.py` | Registers the Foundry project identity and grants it what it needs |
| `create_genie_space.py` | Creates/updates the Genie space over the 10 tables |

## Things that cost us time

**The identity is the project's, not the account's.** A connection created with
`--auth-type project-managed-identity` presents the managed identity of the *Foundry project*
(`<account>/projects/<project>`), which is a different principal from the Foundry account's own
managed identity.

**Databricks wants the application id, not the object id.** `identity.principalId` from ARM is an
object id; Databricks SCIM needs the app id from `az ad sp show --id <objectId> --query appId`.

Both mistakes look identical from Foundry: **HTTP 403, never 401**. A 401 would mean the token was
rejected — a 403 means it was accepted but the principal is unknown to the workspace, or a grant is
missing. Grants needed are `USE CATALOG`, `USE SCHEMA`, `SELECT`, `EXECUTE`, `CAN_USE` on the
warehouse and `CAN_RUN` on the Genie space; missing `SELECT` produces a polite "I don't have
permission" answer from Genie rather than an error.

**`serialized_space` is an undocumented versioned proto.** For reference:

```json
{"version": 2,
 "data_sources": {"tables": [{"identifier": "cat.schema.table"}]},
 "instructions": {"text_instructions": [{"content": ["line", "line"]}]}}
```

`data_sources.tables` must be **sorted by identifier**, and `text_instructions` is a *list* whose
`content` is a *list of strings*. Breaking either gives an error that doesn't say so.

**Genie is asynchronous.** `query_space_*` frequently returns before the answer exists; the caller
must poll `poll_response_*`. Without an explicit instruction the agent tends to reply *"this may
take a moment"* — which the user sees as the final answer. The agent instructions forbid that.

## Data

Same 10 tables as Fabric, in `zava_workspace.demo`:

| Table | Rows | Grain |
|---|---|---|
| `product_lines` | 4 | product line |
| `facilities` | 7 | distribution centre |
| `stores` | 3 | retail store |
| `customers` | 45 | customer |
| `products` | 576 | SKU |
| `inventory` | 4032 | SKU × facility |
| `sales` | 2222 | sale line (fact) |
| `orders` | 90 | order header (fact) |
| `order_items` | 190 | order line (fact) |
| `dim_date` | 190 | day (2025-08-19 … 2026-02-24) |

Column comments and 8 primary keys / 11 foreign keys are not decoration: Genie reads them to choose
tables and infer joins, so they directly drive answer quality.
