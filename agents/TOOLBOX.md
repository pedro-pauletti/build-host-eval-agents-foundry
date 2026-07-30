# Zava Tools — MCP tools & the Foundry Toolbox

Zava exposes its live operational capabilities to the agents through the **Zava MCP server**
(`services/zava-mcp`, deployed to Azure Container Apps), and its documents through a **Foundry IQ knowledge
base**. Both are bundled into a single **Toolbox** (`zava-toolbox`) that the InventoryAgent binds to.

## What a Toolbox is

A **toolbox** is a *named, versioned bundle* of tools published at one MCP endpoint:

```
{project_endpoint}/toolboxes/{name}/mcp?api-version=v1
```

Agents attach to it with a normal `MCPTool`. Inside, tools are namespaced `<server_label>___<tool_name>`
(three underscores), e.g. `zava_tools___get_inventory_alerts`.

Why bother instead of attaching each MCP server directly?

- **One binding per agent.** Add, remove or reorder tools without re-versioning every agent.
- **Versioning + rollback.** Each change is a new toolbox version; the endpoint serves `default_version`.
- **Central auth.** Nested tools carry their own `project_connection_id`, so agents never hold credentials.

## The live definition

`agents/inventory-agent/setup_foundry_iq_and_toolbox.py` is the reproducible source of truth:

```json
{
  "name": "zava-toolbox",
  "description": "Zava operations toolbox: live inventory/order tools + Foundry IQ knowledge base.",
  "tools": [
    { "type": "mcp", "server_label": "zava_tools",
      "server_url": "<ZAVA_MCP_URL>",
      "require_approval": "never" },
    { "type": "mcp", "server_label": "zava_kb",
      "server_url": "https://<search>.search.windows.net/knowledgeBases/zava-kb/mcp?api-version=2026-05-01-preview",
      "allowed_tools": ["knowledge_base_retrieve"],
      "require_approval": "never",
      "project_connection_id": "zava-kb-mcp" }
  ]
}
```

## REST surface

| Operation | Call |
|---|---|
| List toolboxes | `GET  {project}/toolboxes?api-version=v1` |
| Create toolbox | `POST {project}/toolboxes?api-version=v1` |
| Append a version | `POST {project}/toolboxes/{name}/versions?api-version=v1` |
| List versions | `GET  {project}/toolboxes/{name}/versions?api-version=v1` |
| **Promote** a version | `PATCH {project}/toolboxes/{name}` with `{"default_version": "N"}` |
| Tool endpoint | `POST {project}/toolboxes/{name}/mcp?api-version=v1` (JSON-RPC) |

`PUT` is **not** supported (405) on either the toolbox or its versions.

> ⚠️ Creating a new version does **not** promote it. Until you `PATCH` `default_version`, the MCP endpoint —
> and therefore every agent — keeps serving the previous tool set.

## Binding an agent to it

```python
from azure.ai.projects.models import MCPTool

MCPTool(
    server_label="zava_toolbox",
    server_url=f"{PROJECT_ENDPOINT}/toolboxes/zava-toolbox/mcp?api-version=v1",
    require_approval="never",
    project_connection_id="zava-toolbox-mcp",   # connection NAME, not an ARM id
)
```

The `zava-toolbox-mcp` connection is a `RemoteTool` connection with
`authType: ProjectManagedIdentity` and `audience: "https://ai.azure.com/"`, so the **project** managed
identity authenticates and no token is stored in the agent definition.

RBAC required on the **project** MI (a different principal from the account MI):

| Scope | Role | Why |
|---|---|---|
| Foundry account | `Foundry User` (or `Azure AI Developer`) | read its own toolbox |
| Search service | `Search Index Data Reader` | read the Foundry IQ knowledge base |

Diagnostics: **401** = no/invalid credential reached the MCP server (usually a missing connection or a
wrong `audience`); **403** = credential accepted but the role is missing.

## Smoke-test the toolbox MCP endpoint

```pwsh
$TOK  = az account get-access-token --resource "https://ai.azure.com" --query accessToken -o tsv
$URL  = "$env:AZURE_AI_PROJECT_ENDPOINT/toolboxes/zava-toolbox/mcp?api-version=v1"
$body = @{ jsonrpc="2.0"; id=1; method="tools/list"; params=@{} } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri $URL -Body $body -Headers @{
  Authorization = "Bearer $TOK"; "Content-Type" = "application/json"
  Accept = "application/json, text/event-stream" }
```

Expected tools: `zava_kb___knowledge_base_retrieve`, `zava_tools___get_inventory_alerts`,
`zava_tools___get_inventory_summary`, `zava_tools___get_line_stock`, `zava_tools___get_product_stock`,
`zava_tools___list_products`, `zava_tools___lookup_order`, `zava_tools___track_shipment`.

## Known preview limitations

- **A nested knowledge base is dropped for the project MI.** `zava_kb` appears in `tools/list` when you
  call the toolbox with a *user* token, but not when the **agent** enumerates it. `create_agent.py`
  therefore also binds the knowledge base **directly** on the agent.
- **`ToolboxToolType` has no `fabric_dataagent_preview`** (only `fabric_iq_preview`), so the Fabric Data
  Agent tool must stay at agent level.
- **`tool_search` is not the toolbox mechanism** — and it is rejected outright on `gpt-4.1`
  (`Tool 'tool_search' is not supported with gpt-4.1-2025-04-14`). Bind with a plain `MCPTool`.
- **The agent must be pinned to `gpt-4.1`, not `model-router`.** On `model-router` the agent lists the
  toolbox fine (`mcp_list_tools` succeeds) but every tool **call** fails with
  `500 tool_function_not_found` — reproduced in isolation with a single MCP tool, with and without
  `allowed_tools`. Preview limitation.

## Direct MCP (no toolbox)

Attaching the Zava MCP server directly is still perfectly valid and is what the DeliverySupport and
orchestration agents do:

```python
MCPTool(server_label="zava_tools", server_url=os.environ["ZAVA_MCP_URL"], require_approval="never")
```

Foundry only accepts **remote** MCP endpoints, which is why the server is deployed to Container Apps.
