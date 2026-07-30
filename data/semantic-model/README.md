# Zava — Fabric Lakehouse, Semantic Model & Data Agent

This folder contains everything needed to load the **Zava** demo's structured data into
**Microsoft Fabric**, build a star-schema **semantic model** over it, and stand up a
**Fabric Data Agent** that answers natural-language analytics questions — which the Foundry
**InventoryAgent** can then call through the **Fabric IQ** tool.

> **Zava** is a fictitious direct-to-consumer athletic-apparel brand (the *ZavaCore Field*
> collection). All data under `data/structured/*.csv` is synthetic.

---

## 0. Status at a glance

| Deliverable | Status | Key id / note |
|---|---|---|
| Workspace `Zava-Demos` | ✅ existing | `<FABRIC_WORKSPACE_ID>` (capacity **F8** `<your-f-capacity>`) |
| Lakehouse `ZavaLakehouse` | ✅ created | `<FABRIC_LAKEHOUSE_ID>` |
| Delta tables (10) | ✅ loaded | see [§1](#1-lakehouse--delta-tables) — row counts match source exactly |
| Semantic model `ZavaSemanticModel` | ✅ created + validated | `db7b285a-7260-4485-b20b-b907f8bf6ce3` (Direct Lake) |
| Fabric Data Agent `ZavaDataAgent` | ✅ **created + published + answering** | `<FABRIC_DATA_AGENT_ID>` — see [§3](#3-fabric-data-agent-zavadataagent) |
| Fabric IQ wiring into InventoryAgent | 🟡 blocked on **tenant admin consent** | connection + script ready — [§4](#4-wire-fabric-iq-into-the-inventoryagent) |

**Data Agents now work on this F8 capacity.** The old `UnsupportedCapacitySKU: FTL64 SKU Not Supported`
error came from the *Trial* capacity, not from the SKU size; once `Zava-Demos` was moved to the paid
F8 capacity, `POST /v1/workspaces/{ws}/items` with `"type":"DataAgent"` succeeded. The agent is
created, configured (instructions + all 104 semantic-model elements selected), published, and
verified answering real questions over its MCP endpoint.

**The one remaining blocker is tenant-level:** Fabric IQ calls the Data Agent's MCP endpoint
**on behalf of the signed-in user**, which needs an Entra app with delegated Power BI permissions and
**tenant admin consent**. Until that consent exists the endpoint returns `401` — see
[§4](#4-wire-fabric-iq-into-the-inventoryagent).

---

## 1. Lakehouse & Delta tables

- **Lakehouse:** `ZavaLakehouse` — id `<FABRIC_LAKEHOUSE_ID>`
- **SQL analytics endpoint:** id `f7990865-9c51-49b4-99fd-439f28ddfe80`
  - connection string: `c4jjnxxolezuffopb3mwesoeyu-i3fbyco4zthufbyp4rzsqh3n6i.datawarehouse.fabric.microsoft.com`
- **OneLake Tables path:**
  `https://onelake.dfs.fabric.microsoft.com/<FABRIC_WORKSPACE_ID>/<FABRIC_LAKEHOUSE_ID>/Tables`

The 9 source CSVs were loaded as **10 managed Delta tables** (a `dim_date` calendar is derived from
`sales.sale_date` + `orders.order_date`). Row counts match the source files exactly:

| Delta table | Rows | Grain / role |
|---|---:|---|
| `product_lines` | 4 | dimension — line tier & channel |
| `facilities` | 7 | dimension — distribution centres |
| `stores` | 3 | dimension — retail stores |
| `customers` | 45 | dimension |
| `products` | 576 | dimension — SKU catalogue |
| `inventory` | 4,032 | **fact** — on-hand by SKU × facility |
| `sales` | 2,222 | **fact** — sale lines |
| `orders` | 90 | **fact** — fulfilment order headers |
| `order_items` | 190 | **fact** — fulfilment order lines |
| `dim_date` | 190 | dimension — contiguous daily calendar (2025-08-19 → 2026-02-24) |

### Type decisions (applied in `load_delta.py`)

- **Money** (`unit_cost`, `unit_price`, `revenue`, `order_total`, `line_total`) → `decimal(18,2)`.
- **`discount_pct`** → `decimal(9,4)` — it is a **fraction** (0, 0.10, 0.20), *not* a percentage.
- **Counts / quantities** (`quantity`, `on_hand`, `reserved`, `available`, reorder/safety, item_count)
  → `int32`.
- **Dates** (`sale_date`) → `date32`; **timestamps** (`last_updated`, `estimated_delivery`,
  `order_date`) → `timestamp[us, UTC]`.
- **`active`** → `boolean`.
- **Codes/ids/zips** (`sku`, `*_code`, `order_id`, `zip`) → `string` (preserve leading zeros).
- **`sales.store_code`** is blank for 1,580 online rows → converted to **null** (so the
  Sales→Stores relationship is clean and online sales don't map to a fake store).

Loader mechanics: writes go **directly to OneLake** via **delta-rs** (`deltalake`), no Spark
required — `storage_options={"bearer_token": <storage-token>, "use_fabric_endpoint": "true"}` and
URI `abfss://{workspace}@onelake.dfs.fabric.microsoft.com/{lakehouse}/Tables/{table}`. Fabric
auto-discovers anything written under `Tables/` as a **managed** Delta table.

---

## 2. Semantic model — `ZavaSemanticModel`

- **Id:** `db7b285a-7260-4485-b20b-b907f8bf6ce3`
- **Storage mode:** **Direct Lake on OneLake** (`AzureStorage.DataLake`, `HierarchicalNavigation=true`)
  — reads the Delta tables in place, no import/copy.
- **Definition:** TMDL under [`ZavaSemanticModel/`](./ZavaSemanticModel) (source of truth), generated
  by [`build_tmdl.py`](./build_tmdl.py) and deployed by [`deploy_semantic_model.py`](./deploy_semantic_model.py).

### Tables (10)

Facts: **Sales**, **Inventory**, **Orders**, **Order Items**.
Dimensions: **Products**, **Product Lines**, **Facilities**, **Stores**, **Customers**, **Calendar**.

> **⚠️ The date dimension is named `Calendar`, not `Date`.** `Date` is a **reserved word** in DAX
> (the `DATE()` function), so an unquoted `Date[...]` reference throws *"The syntax for '[…]' is
> incorrect."* Naming it `Calendar` lets the Data Agent's LLM-generated DAX reference
> `Calendar[Date]` / `Calendar[Year Month]` **without quoting** — a real reliability win for
> natural-language querying. (The date **column** inside the table is still called `Date`.)

### Relationships (11, all single-direction many→one from fact/child to dimension/parent)

| From (many) | Column | → To (one) | Column |
|---|---|---|---|
| Sales | SKU | Products | SKU |
| Sales | Store Code | Stores | Store Code |
| Sales | Sale Date | Calendar | Date |
| Inventory | SKU | Products | SKU |
| Inventory | Facility Code | Facilities | Facility Code |
| Products | Line Code | Product Lines | Line Code |
| Orders | Customer ID | Customers | Customer ID |
| Orders | Ship From Facility | Facilities | Facility Code |
| Orders | Order Date | Calendar | Date |
| Order Items | Order ID | Orders | Order ID |
| Order Items | SKU | Products | SKU |

This gives a clean snowflake-ish star: `Sales` fans out to Products→Product Lines, Stores, and
Calendar; `Inventory` to Products and Facilities; the order pair (`Orders`/`Order Items`) to
Customers, Facilities, Products, and Calendar.

### Measures (21)

The **four required** measures (validated values in parentheses, whole-model / no filter):

| Measure | DAX | Format | Value |
|---|---|---|---|
| **Total Revenue** | `SUM(Sales[Revenue])` | `$#,##0.00` | **$343,010.37** |
| **Total Units** | `SUM(Sales[Quantity])` | `#,##0` | **6,664** |
| **Total On-Hand** | `SUM(Inventory[On Hand])` | `#,##0` | **802,501** |
| **Avg Days-to-Stockout** | `AVERAGE(Inventory[Projected Stockout Days])` | `#,##0.0` | **33.26** |

Plus 17 more, grouped by home table:

- **Sales:** Number of Sales, Distinct SKUs Sold, Avg Discount %, Avg Selling Price
- **Inventory:** Total Available, Total Reserved, Critical or Low SKU Count, SKUs Below Reorder Point
- **Orders:** Total Orders, Total Order Value, Avg Order Value, Delayed Orders, Delivered Orders
- **Order Items:** Order Line Units, Order Line Value
- **Products:** Product Count, Active Product Count

Every measure carries a `formatString`; hidden key columns keep the model tidy for NL querying.

### Two Direct Lake gotchas (already handled, keep in mind for changes)

1. **Initial reframe required.** A freshly (re)deployed Direct Lake model returns *"table … not
   refreshed / fallback to DirectQuery disabled"* until it is **reframed** once:
   ```powershell
   # resource: https://analysis.windows.net/powerbi/api
   POST https://api.powerbi.com/v1.0/myorg/groups/{workspaceId}/datasets/{modelId}/refreshes
   body: {"type":"full"}     # → refreshType = DirectLakeFraming, status = Completed
   ```
2. **`Calendar`, not `Date`.** See the warning above — reference the date table as `Calendar[...]`.

### Validate with DAX (read-only)

```powershell
# resource: https://analysis.windows.net/powerbi/api ; dataset = db7b285a-7260-4485-b20b-b907f8bf6ce3
EVALUATE ROW("Revenue",[Total Revenue],"Units",[Total Units],"OnHand",[Total On-Hand],"AvgDTS",[Avg Days-to-Stockout])
EVALUATE TOPN(5, SUMMARIZECOLUMNS(Calendar[Year Month], "Revenue",[Total Revenue]), [Revenue], DESC)
EVALUATE TOPN(5, SUMMARIZECOLUMNS('Product Lines'[Product Line], Products[Gender], "Rev",[Total Revenue]), [Rev], DESC)
```

---

## 3. Fabric Data Agent — `ZavaDataAgent`

### Current status: ✅ created, configured, published and answering

| | |
|---|---|
| Data Agent id | `<FABRIC_DATA_AGENT_ID>` |
| Data source | `ZavaSemanticModel` (`db7b285a-7260-4485-b20b-b907f8bf6ce3`), **104 elements selected** |
| MCP tool exposed | `DataAgent_ZavaDataAgent` (input `userQuestion`) |
| Capacity | `<your-f-capacity>` (**F8**) — sufficient; the earlier failure was the *Trial* SKU |

### ➡️ Recreate it with one command

[`create_data_agent.py`](./create_data_agent.py) is **idempotent** — it reuses the agent if it already
exists, then re-applies instructions, attaches the semantic model, selects every element, and
publishes.

> **Runtime requirement:** `fabric-data-agent-sdk` needs **Python ≥3.10, <3.13**. This repo's main venv
> is 3.13, so use the dedicated `.venv-fabric`:
> ```powershell
> uv venv --python 3.11 .venv-fabric
> uv pip install --python .venv-fabric\Scripts\python.exe fabric-data-agent-sdk azure-identity
> .venv-fabric\Scripts\python.exe data/semantic-model/create_data_agent.py
> ```
> Auth outside Fabric is handled by
> `SetFabricAnalyticsDefaultTokenCredentialsGlobally(AzureCliCredential())` (uses your `az login`).

**Two SDK caveats this script works around**, both worth knowing before you edit it:

1. The convenience helpers (`get_datasources()`, `update_configuration()`, `publish()`) route through a
   *legacy* endpoint that imports `synapse.ml.fabric` and therefore only resolves **inside a Fabric
   notebook**. From a laptop you must use the modern **staging** surface instead: `update_settings`,
   `add_staging_datasource`, `patch_staging_datasource`, `patch_staging_element`, `publish_staging`.
2. **Few-shot examples are not supported for `SemanticModel` data sources** — `POST .../fewshots`
   returns `400 BadRequest`. The NL→DAX exemplars are therefore folded into the *data-source
   instructions* string instead.

Two more behaviours to keep in mind: `add_staging_datasource` is **asynchronous** (HTTP `202`; the
script polls until the data source appears), and a freshly attached semantic model has **every element
unselected**, which would leave the agent with nothing to query — hence the recursive select step.

#### Alternative — portal (no code)

1. Open **`Zava-Demos`** → **New** → **Data agent** → name it **`ZavaDataAgent`**.
2. **Add data source** → **Semantic model** → select **`ZavaSemanticModel`** → tick all tables.
3. Add **instructions** (copy `AGENT_INSTRUCTIONS` from `create_data_agent.py`), then **Publish**.

### Test it

[`test_data_agent.py`](./test_data_agent.py) exists but relies on `FabricOpenAI`, which is
**notebook-only** (it imports `synapse.ml.fabric`). From a laptop, call the **MCP endpoint** directly —
this is also exactly the path Fabric IQ uses:

```powershell
$WS="<FABRIC_WORKSPACE_ID>"; $ID="<FABRIC_DATA_AGENT_ID>"
$t = az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv
$u = "https://api.fabric.microsoft.com/v1/mcp/workspaces/$WS/dataagents/$ID/agent"
$b = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"DataAgent_ZavaDataAgent","arguments":{"userQuestion":"Show revenue and units by product line."}}}'
Invoke-WebRequest -Method Post -Uri $u -Headers @{Authorization="Bearer $t"; Accept="application/json, text/event-stream"} -ContentType "application/json" -Body $b
```

Verified response:

| Product Line | Total Revenue | Total Units |
|---|---|---|
| ZavaCore Field Core | $54,234.83 | 1,629 |
| ZavaCore Field Elite | $127,748.55 | 1,770 |
| ZavaCore Field Premium | $90,050.25 | 1,615 |
| ZavaCore Field Pro | $70,976.74 | 1,650 |

### Prompts to demo the Data Agent

- *"What is total revenue and how many units have we sold?"*
- *"Show revenue and units by product line."*
- *"Which distribution centre has the most critical or low-stock SKUs?"*
- *"What is the total on-hand inventory and the average days to stockout?"*
- *"Top 5 selling SKUs by revenue."*
- *"How many orders are delayed, and which customers do they belong to?"*
- *"Compare online versus in-store revenue."*
- *"Show monthly revenue for the most recent months."* (uses the `Calendar` dimension)

### Resulting MCP endpoint

```
https://api.fabric.microsoft.com/v1/mcp/workspaces/<FABRIC_WORKSPACE_ID>/dataagents/<FABRIC_DATA_AGENT_ID>/agent
```

---

## 4. Wire the Data Agent into the InventoryAgent ✅

The Foundry **InventoryAgent** (`agents/inventory-agent/create_agent.py`) attaches the published Data
Agent as a **third** tool, for *analytical* questions ("How did Elite-line revenue compare month over
month?", "What is total revenue by product line?").

### Two Fabric tool types — pick the right one

| | `FabricIQPreviewTool` (`fabric_iq_preview`) | **`MicrosoftFabricPreviewTool`** (`fabric_dataagent_preview`) ✅ |
|---|---|---|
| Wiring | `server_url` + `project_connection_id` | `fabric_dataagent_preview.project_connections[]` |
| Connection | `MicrosoftFabric` / AAD | **CustomKeys** connection with `metadata.type = "fabric_dataagent_preview"` |
| Auth | needs a **delegated user** token → Entra app + tenant admin consent | works with the connection alone |
| Result here | **401** (and see the warning below) | ✅ verified answering |

We use the second. The connection `fabric_zava_dataagent` is created by adding the **Data Agent** tool to
the agent in the [Foundry portal](https://ai.azure.com/) (it also accepts an ARM `PUT`); `create_agent.py`
then references it by name:

```python
from azure.ai.projects.models import MicrosoftFabricPreviewTool, FabricDataAgentToolParameters

MicrosoftFabricPreviewTool(
    fabric_dataagent_preview=FabricDataAgentToolParameters(
        project_connections=[{"project_connection_id": "fabric_zava_dataagent"}]
    )
)
```

> ### ⚠️ A failing tool endpoint takes the whole agent down
> Foundry resolves an MCP tool's endpoint on **every** request. If a tool endpoint returns `401`,
> **all** InventoryAgent calls fail — including plain inventory questions that never touch it —
> with `tool_user_error`. This was reproduced live with the `fabric_iq_preview` path. Roll back by
> re-running `agents/inventory-agent/create_agent.py` (add `--no-fabric` to drop the Fabric tool).

### Verify

```powershell
.venv\Scripts\python.exe agents/inventory-agent/create_agent.py --test
```

The smoke test asks one question per capability — Foundry IQ (policy), toolbox MCP (live stock) and
Fabric (revenue by product line).

---

## 5. Reproduce the whole build

All scripts are **environment-parameterised** (ids default to this workspace but are overridable) and
keep secrets/tokens **out of source** — tokens are read from env vars at runtime via `az`.

```powershell
# repo root; az already logged in (do NOT run az login)
$py = ".venv\Scripts\python.exe"

# 0) deps (one-time)
& $py -m pip install deltalake pandas pyarrow requests

# 1) load CSVs → Delta (delta-rs → OneLake).  Needs a *storage* token.
$env:ONELAKE_TOKEN = az account get-access-token --resource https://storage.azure.com --query accessToken -o tsv
& $py data/semantic-model/load_delta.py

# 2) (re)generate TMDL from the model spec
& $py data/semantic-model/build_tmdl.py

# 3) deploy the semantic model (Fabric Items API).  Needs a *Fabric* token.
$env:FABRIC_TOKEN = az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv
& $py data/semantic-model/deploy_semantic_model.py     # prints SEMANTIC_MODEL_ID

# 4) one-time Direct Lake reframe (resource: https://analysis.windows.net/powerbi/api)
#    POST .../groups/{ws}/datasets/{modelId}/refreshes  {"type":"full"}

# 5) create + publish the Fabric Data Agent (Python 3.10-3.12 — see §3)
& .venv-fabric\Scripts\python.exe data/semantic-model/create_data_agent.py

# 6) wire the Data Agent into the InventoryAgent (+ Foundry IQ + toolbox)
& $py agents/inventory-agent/setup_foundry_iq_and_toolbox.py
& $py agents/inventory-agent/create_agent.py --test
```

> **Token audiences** (each is a different `--resource`): OneLake writes →
> `https://storage.azure.com`; Fabric Items API → `https://api.fabric.microsoft.com`; Power BI
> refresh/DAX → `https://analysis.windows.net/powerbi/api`. Using the wrong one returns `401`.

---

## 6. Files in this folder

| File | Purpose |
|---|---|
| [`load_delta.py`](./load_delta.py) | Reads the 9 CSVs, applies types, builds `dim_date`, writes 10 Delta tables to OneLake (delta-rs, no Spark). |
| [`build_tmdl.py`](./build_tmdl.py) | Generates the TMDL folder (tables, relationships, measures) with correct **tab** indentation. Edit here to change the model. |
| [`deploy_semantic_model.py`](./deploy_semantic_model.py) | Base64-encodes the TMDL parts and creates the semantic model via the Fabric Items API (LRO-polled). |
| [`create_data_agent.py`](./create_data_agent.py) | Idempotently creates + configures + publishes the Fabric Data Agent via `fabric-data-agent-sdk` (Python 3.10-3.12, `.venv-fabric`). |
| [`test_data_agent.py`](./test_data_agent.py) | Asks the published Data Agent a set of questions. **Fabric-notebook only** (`FabricOpenAI` needs `synapse.ml.fabric`); from a laptop use the MCP call in §3. |
| [`ZavaSemanticModel/`](./ZavaSemanticModel) | The deployed TMDL definition (`definition.pbism`, `database.tmdl`, `model.tmdl`, `expressions.tmdl`, `relationships.tmdl`, `tables/*.tmdl`). |

---

## 7. Manual / admin actions still required

**None.** The Fabric side of the demo is complete:

- ✅ F8 capacity assignment, lakehouse, 10 typed Delta tables
- ✅ validated Direct Lake semantic model `ZavaSemanticModel`
- ✅ `ZavaDataAgent` created, configured (104 elements), published and **answering**
- ✅ Foundry connection `fabric_zava_dataagent` (CustomKeys, `fabric_dataagent_preview`)
- ✅ `MicrosoftFabricPreviewTool` attached to **InventoryAgent** and verified live

> The older `fabric_iq_preview` path is **not** used: it requires an Entra app with delegated
> `Item.Execute.All` / `Item.Read.All` (Power BI Service) + `DataAgent.Execute.All` (Fabric) and
> **tenant admin consent**, because the Fabric Data Agent MCP endpoint rejects service-principal
> tokens. Granting the Foundry managed identity **Member** on the `Zava-Demos` workspace and setting
> `useWorkspaceManagedIdentity: true` was tried and still returned `401`. The
> `fabric_dataagent_preview` tool avoids the problem entirely.
