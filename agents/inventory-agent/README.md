# Zava InventoryAgent (Foundry prompt agent)

A Foundry **prompt agent** that answers Zava inventory-operations questions by combining a **Foundry IQ
knowledge base** (documents), **live MCP tools** bundled in a Foundry **Toolbox**, and a **Fabric Data
Agent** (warehouse analytics).

```
InventoryAgent
  ├── MCPTool → Toolbox `zava-toolbox`            (versioned bundle, one MCP endpoint)
  │     ├── mcp: zava_tools → Zava MCP server on ACA  → Zava REST APIs
  │     └── mcp: zava_kb    → Foundry IQ knowledge base
  ├── MCPTool → `zava-kb` knowledge base (bound directly — see limitation below)
  └── MicrosoftFabricPreviewTool → Fabric Data Agent `ZavaDataAgent`
```

## Files
| File | Purpose |
|------|---------|
| `setup_foundry_iq_and_toolbox.py` | **Run first.** Creates the knowledge source, the Foundry IQ knowledge base, the two `RemoteTool` connections, and the `zava-toolbox` (idempotent). `--test` exercises both MCP endpoints. |
| `create_agent.py` | Creates/updates the agent and wires the toolbox + knowledge base + Fabric Data Agent. `--test` runs a smoke test; `--test-only` skips creation; `--no-fabric` omits the Fabric tool. |
| `eval.yaml` | Evaluation suite definition (dataset + built-in / custom / rubric evaluators). |
| `evals/inventory_eval.jsonl` | Evaluation dataset: query + ground truth + the facts an answer must contain. |
| `evals/inventory_seed.jsonl` | Older seed set (query + expected_behavior), kept for reference. |
| `run_eval.py` | **Cloud evaluation**: uploads the dataset, registers the custom + rubric evaluators, runs them together with the built-ins against the live agent, and prints the Foundry report URL. |
| `../TOOLBOX.md` | How the MCP tools are exposed (direct MCP vs. Foundry Toolbox). |

## Run
```pwsh
# from repo root, with the venv and a populated .env
.\.venv\Scripts\python.exe agents\inventory-agent\setup_foundry_iq_and_toolbox.py --test
.\.venv\Scripts\python.exe agents\inventory-agent\create_agent.py --test   # create + smoke test
.\.venv\Scripts\python.exe agents\inventory-agent\run_eval.py              # evaluate (results in the Foundry portal)
.\.venv\Scripts\python.exe agents\inventory-agent\run_eval.py --limit 3    # quick smoke evaluation
```

## Tools

| Tool | Backed by | Use for |
|---|---|---|
| `MCPTool` → `zava-toolbox` | Zava MCP server on Azure Container Apps | live stock, alerts, KPIs, product lookup, order lookup, shipment tracking (`zava_tools___*`) |
| `MCPTool` → `zava-kb` | **Foundry IQ** knowledge base over the `zava-docs` search index | policy / how-to answers **with citations** (`knowledge_base_retrieve`) |
| `MicrosoftFabricPreviewTool` | Fabric Data Agent `ZavaDataAgent` over `ZavaSemanticModel` | revenue, trends, aggregates |

### Why Foundry IQ instead of `AzureAISearchTool`

`AzureAISearchTool` issues one raw query against one index and hands back chunks. A **Foundry IQ knowledge
base** takes a natural-language *question*, plans and decomposes it, federates multiple knowledge sources,
and returns a **synthesised answer with citations**, steered by `retrievalInstructions`,
`answerInstructions` and `outputMode: answerSynthesis`.

Foundry IQ objects live on the **Azure AI Search data plane**, not the Foundry project:

- knowledge source `zava-docs-ks` → wraps the `zava-docs` index
- knowledge base `zava-kb` → source + `gpt-4.1` reasoning model + instructions
- consumed by agents through the KB's own MCP endpoint
  (`.../knowledgeBases/zava-kb/mcp?api-version=2026-05-01-preview`, tool `knowledge_base_retrieve`)

### Why a Toolbox

A toolbox is a **versioned bundle** of tools published at a single MCP endpoint
(`{project_endpoint}/toolboxes/{name}/mcp?api-version=v1`). Agents bind to the bundle, so tools can be
added, removed or rolled back **without re-versioning any agent**. Tools are namespaced
`<server_label>___<tool_name>`.

Toolboxes are versioned: `POST /toolboxes/{name}/versions` appends a version and the MCP endpoint serves
`default_version` — promote a new version with `PATCH /toolboxes/{name}`.

## Gotchas found while building this

- **Project MI ≠ account MI.** `RemoteTool` connections with `authType: ProjectManagedIdentity` use the
  **project's** system-assigned identity. It needs:
  - `Foundry User` (or `Azure AI Developer`) on the Foundry **account** → read its own toolbox
  - `Search Index Data Reader` on the **search service** → read the knowledge base

  Get its principal id with:
  ```pwsh
  az rest --method get --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/$ACCT/projects/$PROJ?api-version=2025-06-01" --query identity.principalId -o tsv
  ```
- **`audience` must be a top-level connection property.** Nesting it in `metadata` silently yields
  `audience: null` → 401. Use `https://search.azure.com/` for the KB and `https://ai.azure.com/` for the
  toolbox.
- **401 vs 403.** 401 = no/invalid credential reached the MCP server. 403 = credential accepted, RBAC
  missing.
- **`knowledge_base_retrieve` takes `queries` — a JSON array**, not `query`.
- **Preview limitation:** a knowledge base nested *inside* a toolbox is silently dropped from
  `mcp_list_tools` when the toolbox is enumerated by the project MI (it appears fine with a user token).
  That is why `create_agent.py` also binds `zava-kb` **directly** on the agent.
- **The Fabric tool cannot live in a toolbox** — `ToolboxToolType` only exposes `fabric_iq_preview`, not
  the `fabric_dataagent_preview` type we use. Use `MicrosoftFabricPreviewTool` with a **CustomKeys**
  connection (`fabric_zava_dataagent`); `FabricIQPreviewTool` needs a delegated user token and 401s.
- ⚠️ **One failing tool endpoint breaks *every* request to the agent**, including questions that never
  touch it — Foundry resolves all MCP endpoints on each call. Always smoke-test after changing tools;
  roll back by re-running `create_agent.py`.
- **Routing needs to be explicit.** Without a hard rule the model happily answers policy questions from
  live inventory numbers. The instructions force policy/threshold/SLA keywords to Foundry IQ first.

## Model
`gpt-4.1` (deployment `FOUNDRY_MODEL_DEPLOYMENT_NAME`) — **deliberately pinned, not routed**.

Switching this agent to the `model-router` deployment **breaks tool calling**: the agent still lists the
toolbox (`mcp_list_tools` succeeds) but every tool *call* returns `500 tool_function_not_found`.
Reproduced in isolation with a single MCP tool, with and without `allowed_tools`; the identical agent on
`gpt-4.1` calls `zava_tools___get_inventory_alerts` correctly. The Foundry IQ knowledge base is pinned for
a different reason — AI Search only accepts gpt-4o / gpt-4.1 / gpt-5.x as a knowledge-base model.

Agents in this repo that have **no** tools (Triage, Compliance) *do* use `model-router`.

## Notebook
The full didactic walkthrough is `notebooks/01_inventory_agent.en.ipynb` (and `.pt-BR.ipynb`).
