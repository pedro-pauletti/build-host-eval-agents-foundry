"""Builder for notebooks/01_inventory_agent.en.ipynb (English).

Run: .venv\\Scripts\\python.exe notebooks/_builders/build_inventory_en.py
Produces a didactic, runnable notebook that mirrors the live InventoryAgent
(agents/inventory-agent/create_agent.py) and the wider demo.
"""
import os
import nbformat as nbf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "01_inventory_agent.en.ipynb")

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))
def code(t): cells.append(nbf.v4.new_code_cell(t.strip("\n")))

md(r"""
# 🧵 Zava · Building the **InventoryAgent** on Microsoft Foundry

> **Prompt agent** · Foundry Agent Service SDK · **Foundry IQ** knowledge base · **MCP** tools in a **Toolbox** · **Fabric Data Agent** · Web app (text + voice) · Teams · Evaluations
>
> 🇧🇷 A Portuguese version of this notebook is available as `01_inventory_agent.pt-BR.ipynb`.

**Zava** is a fictitious direct-to-consumer **athletic apparel** brand (the *ZavaCore Field* collection:
Core, Pro, Premium, Elite). Inventory operations staff — like our persona **Maya**, an Inventory Operations
Manager — need fast, natural-language answers about stock across 7 distribution centers.

In this notebook you will build the **InventoryAgent**, a Foundry **prompt agent** that:

1. Answers **policy / how-to** questions from a **Foundry IQ knowledge base**, with citations.
2. Answers **live inventory** questions (stock by SKU, critical alerts, on-hand by product line) by calling
   the **Zava MCP server**, published through a Foundry **Toolbox**.
3. Answers **analytical** questions via a **Fabric Data Agent** over the Zava semantic model.
""")

md(r"""
## 🏗️ Architecture

```mermaid
flowchart LR
  U[User / Maya<br/>text + voice] --> INV[InventoryAgent<br/>prompt agent]
  INV -->|policy & how-to| KB[Foundry IQ<br/>knowledge base zava-kb]
  KB --> KS[knowledge source<br/>zava-docs-ks]
  KS --> SEARCH[(Azure AI Search<br/>zava-docs index)]
  INV -->|live stock & orders| TB[Toolbox<br/>zava-toolbox]
  TB --> MCP[Zava MCP server<br/>Azure Container Apps]
  MCP --> API[Zava REST APIs<br/>FastAPI]
  INV -->|analytics| FAB[Fabric Data Agent<br/>ZavaDataAgent]
  FAB --> SM[(Fabric semantic model)]
  INV --> AI[(App Insights<br/>traces + evals)]
```

**Why these pieces?**
- **Foundry IQ** grounds the agent on Zava's *documents*. Unlike querying a raw search index, a knowledge
  base plans the query, federates sources and returns a **synthesised answer with citations**.
- **MCP tools** give the agent *live, structured* data. Foundry only accepts **remote** MCP endpoints, so the
  Zava MCP server runs on **Azure Container Apps** and calls the Zava REST API.
- A **Toolbox** bundles those MCP tools into one versioned endpoint, so tools can change without
  re-versioning every agent that uses them.
- The **Fabric Data Agent** lets the same agent delegate *analytical* questions to a Fabric semantic model —
  natural-language questions over the enterprise warehouse.
""")

md(r"""
## ✅ Prerequisites

- The demo infrastructure is already provisioned (`scripts/provision.ps1`) and the backends are deployed
  (`scripts/deploy_backend.ps1`), and the knowledge base is indexed (`scripts/index_docs.py`).
- A repo-root **`.env`** exists with the resource endpoints (created by provisioning). We load it below.
- You are authenticated: `az login` (the SDK uses `DefaultAzureCredential`).
- Use the repo virtual environment as the Jupyter kernel (`.venv`).

Install the client libraries (already present if you used the repo `.venv`):
""")

code(r"""
# %pip install azure-ai-projects --pre azure-identity openai python-dotenv httpx
import os
from dotenv import load_dotenv

# Load the endpoints produced by provisioning.
load_dotenv(os.path.join("..", ".env"))

PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
MODEL            = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
SEARCH_CONN      = os.environ.get("AZURE_SEARCH_CONNECTION_NAME", "zava-search")
INDEX            = os.environ.get("AZURE_SEARCH_INDEX_NAME", "zava-docs")
MCP_URL          = os.environ["ZAVA_MCP_URL"]

print("Project :", PROJECT_ENDPOINT)
print("Model   :", MODEL)
print("KB index:", INDEX, "via connection", SEARCH_CONN)
print("MCP     :", MCP_URL)
""")

md(r"""
## 1️⃣ Connect to the Foundry project

Everything goes through the **`AIProjectClient`** — the SDK entry point for a Foundry project. It uses
`DefaultAzureCredential`, so the same code works locally (`az login`) and in production (managed identity).
""")

code(r"""
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())

# The AI Search connection was created declaratively (infra/modules/connections.bicep).
search_conn = client.connections.get(SEARCH_CONN)
print("AI Search connection id:\n", search_conn.id)
""")

md(r"""
## 2️⃣ The knowledge base — **Foundry IQ**

Zava's documents (`data/docs/*.md` — returns & exchanges, shipping SLA, sizing & fabric care, reorder policy,
product-line overview, FAQ…) were **chunked, embedded, and indexed** into an Azure AI Search index called
`zava-docs` (see `scripts/index_docs.py`). The index has a searchable `content` field, a 3072-dim
`content_vector`, an integrated Azure OpenAI **vectorizer**, and a **semantic** configuration.

But we do **not** hand that raw index to the agent. Instead we put **Foundry IQ** on top of it.

### Raw index vs. Foundry IQ

| | `AzureAISearchTool` (raw index) | **Foundry IQ** (knowledge base) |
|---|---|---|
| Input | a search *query* | a natural-language *question* |
| Query planning | none — one query, as written | decomposes & rewrites into sub-queries |
| Sources | one index | many **knowledge sources** federated together |
| Output | a list of chunks the model must read | a **synthesised answer with citations** |
| Steering | `top_k`, query type | `retrievalInstructions`, `answerInstructions`, `outputMode` |

Foundry IQ is implemented by Azure AI Search **knowledge bases**. Two objects, both on the *search service*
data plane (not the Foundry project):

1. a **knowledge source** (`zava-docs-ks`) — wraps the `zava-docs` index,
2. a **knowledge base** (`zava-kb`) — one or more sources + a reasoning model + instructions.

`agents/inventory-agent/setup_foundry_iq_and_toolbox.py` creates both idempotently. Here is the essence:
""")

code(r'''
import httpx
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"].rstrip("/")
SEARCH_API      = "2026-05-01-preview"          # knowledge bases need a 2026+ preview surface
KS_NAME, KB_NAME = "zava-docs-ks", "zava-kb"

hdr = {"Authorization": "Bearer " + DefaultAzureCredential()
                                      .get_token("https://search.azure.com/.default").token,
       "Content-Type": "application/json"}

# 1) knowledge source — `searchIndexName` is the only required parameter
httpx.put(f"{SEARCH_ENDPOINT}/knowledgeSources/{KS_NAME}?api-version={SEARCH_API}", headers=hdr,
          json={"name": KS_NAME, "kind": "searchIndex",
                "searchIndexParameters": {"searchIndexName": INDEX}}, timeout=90).raise_for_status()

# 2) knowledge base — sources + reasoning model + how to retrieve and how to answer
httpx.put(f"{SEARCH_ENDPOINT}/knowledgeBases/{KB_NAME}?api-version={SEARCH_API}", headers=hdr, json={
    "name": KB_NAME,
    "description": "Zava's official operations handbook. AUTHORITATIVE for policy, procedure and rules.",
    "knowledgeSources": [{"name": KS_NAME}],
    "models": [{"kind": "azureOpenAI", "azureOpenAIParameters": {
        "resourceUri": f"https://{os.environ['FOUNDRY_ACCOUNT_NAME']}.openai.azure.com",
        "deploymentId": MODEL, "modelName": MODEL}}],
    "retrievalInstructions": "The corpus is Zava's internal operations handbook…",
    "answerInstructions":    "Answer only from retrieved documents and always cite the document title.",
    "outputMode": "answerSynthesis",   # return a written answer, not just chunks
}, timeout=90).raise_for_status()

print("Foundry IQ knowledge base ready:", KB_NAME)
''')

md(r"""
### How an agent consumes Foundry IQ

There is **no** dedicated `KnowledgeBaseTool`. A knowledge base publishes its own **MCP endpoint**:

```
https://<search-service>.search.windows.net/knowledgeBases/<kb>/mcp?api-version=2026-05-01-preview
```

…exposing a single tool, **`knowledge_base_retrieve`**. So the agent binds to it with a normal `MCPTool`.

Two details that cost hours if you get them wrong:

- the argument is **`queries`** — a JSON **array** of one full natural-language question (not `query`);
- to avoid putting a bearer token in the agent definition, create a **`RemoteTool` connection** with
  `authType: ProjectManagedIdentity` and `audience: "https://search.azure.com/"`. The `audience` must be a
  **top-level** property — nesting it under `metadata` silently yields `audience: null` and you get a 401.
""")

code(r'''
KB_MCP_URL = f"{SEARCH_ENDPOINT}/knowledgeBases/{KB_NAME}/mcp?api-version={SEARCH_API}"

r = httpx.post(KB_MCP_URL,
    headers={**hdr, "Accept": "application/json, text/event-stream"},
    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
          "params": {"name": "knowledge_base_retrieve",
                     "arguments": {"queries": ["What is the Zava return window?"]}}},
    timeout=120)
print(r.text[:500])   # -> a synthesised answer WITH a [ref_id / source] citation
''')

md(r"""
## 3️⃣ The tools — the **Zava MCP server**

The **Model Context Protocol (MCP)** is an open standard for exposing tools to LLMs. The Zava MCP server
(`services/zava-mcp`, deployed to Azure Container Apps) wraps the Zava REST API and exposes tools such as
`get_product_stock`, `get_inventory_alerts`, `get_inventory_summary`, `get_line_stock`, `list_products`,
`lookup_order`, and `track_shipment`.

Because Foundry only accepts **remote** MCP endpoints, the server is reachable at `ZAVA_MCP_URL`
(`https://…/mcp`). Let's list its tools directly over MCP to see what the agent will be able to call:
""")

code(r"""
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

async def list_mcp_tools(url):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            return [(t.name, (t.description or "").split("\n")[0]) for t in tools]

for name, desc in await list_mcp_tools(MCP_URL):
    print(f"• {name:22s} {desc}")
""")

md(r"""
### Bundling tools into a **Toolbox**

Attaching MCP servers one-by-one to every agent does not scale: each agent definition repeats every URL,
label and connection, and adding a tool means re-versioning every agent.

A **toolbox** is a *named, versioned bundle* of tools published at a single MCP endpoint:

```
{project_endpoint}/toolboxes/{name}/mcp?api-version=v1
```

Agents bind to that one endpoint with a normal `MCPTool`. Inside, tools are namespaced
`<server_label>___<tool_name>` (three underscores), e.g. `zava_tools___get_inventory_alerts`.

Toolboxes are **versioned**: `POST /toolboxes/{name}/versions` appends a version, and the MCP endpoint
serves the toolbox's `default_version` — so you must **promote** a new version with
`PATCH /toolboxes/{name}` for agents to see it. That is exactly what makes a toolbox useful: you can swap
tools underneath a fleet of agents without touching a single agent definition.
""")

code(r'''
PROJECT = PROJECT_ENDPOINT.rstrip("/")
TOOLBOX = "zava-toolbox"
phdr = {"Authorization": "Bearer " + DefaultAzureCredential()
                                       .get_token("https://ai.azure.com/.default").token,
        "Content-Type": "application/json"}

body = {
    "name": TOOLBOX,
    "description": "Zava operations toolbox: live inventory/order tools + Foundry IQ knowledge base.",
    "tools": [
        {"type": "mcp", "server_label": "zava_tools", "server_url": MCP_URL,
         "server_description": "Live Zava inventory, alerts, KPIs, product lookups.",
         "require_approval": "never"},
        {"type": "mcp", "server_label": "zava_kb", "server_url": KB_MCP_URL,
         "server_description": "Foundry IQ knowledge base — authoritative for Zava policy.",
         "allowed_tools": ["knowledge_base_retrieve"], "require_approval": "never",
         "project_connection_id": "zava-kb-mcp"},          # connection NAME, not an ARM id
    ],
}

exists = httpx.get(f"{PROJECT}/toolboxes/{TOOLBOX}?api-version=v1", headers=phdr).status_code == 200
url = f"{PROJECT}/toolboxes/{TOOLBOX}/versions?api-version=v1" if exists else f"{PROJECT}/toolboxes?api-version=v1"
version = str(httpx.post(url, headers=phdr, json=body, timeout=120).json()["version"])

# Promote it, otherwise the MCP endpoint keeps serving the previous default version.
httpx.patch(f"{PROJECT}/toolboxes/{TOOLBOX}?api-version=v1", headers=phdr,
            json={"default_version": version}, timeout=60).raise_for_status()

tools_listed = httpx.post(f"{PROJECT}/toolboxes/{TOOLBOX}/mcp?api-version=v1",
    headers={**phdr, "Accept": "application/json, text/event-stream"},
    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, timeout=90)
print("toolbox version", version)
print(tools_listed.text[:400])
''')

md(r"""
## 4️⃣ Create the **InventoryAgent** (prompt agent)

A **prompt agent** is defined by a `PromptAgentDefinition`: a model, instructions, and a list of tools.
Our final tool set is deliberately small — the *toolbox* does the bundling:

| Tool | Purpose |
|---|---|
| `MCPTool` → **`zava-toolbox`** | live inventory / orders (`zava_tools___*`) |
| `MCPTool` → **`zava-kb`** (Foundry IQ) | policy & how-to answers with citations |
| `MicrosoftFabricPreviewTool` | historical analytics via the Fabric **Data Agent** |

Notes from building this for real:

- **Authentication** is via `project_connection_id` = the **name** of a `RemoteTool` connection. The
  *project* managed identity then calls the endpoint — no tokens in the agent definition. Note that the
  **project** MI is a different principal from the **account** MI, and it is the project one that needs
  `Foundry User` / `Azure AI Developer` on the account and `Search Index Data Reader` on the search service.
- **Foundry IQ is bound directly on the agent as well as inside the toolbox.** In the current preview the
  nested knowledge-base tool is silently dropped from `mcp_list_tools` when the toolbox is enumerated by
  the project MI, so the direct binding is what actually makes it callable.
- The **Fabric Data Agent tool cannot live in a toolbox** — `ToolboxToolType` only exposes
  `fabric_iq_preview`, not the `fabric_dataagent_preview` type we use.
- ⚠️ **A single failing tool endpoint breaks every request to the agent**, even questions that never touch
  it. Foundry resolves all MCP endpoints on each call. Always smoke-test after adding a tool.

Good **instructions** are what make routing reliable — notice the explicit *hard routing rule* that forces
policy questions to Foundry IQ instead of letting the model infer policy from live numbers.

> 🧪 **Demo note:** we create the agent under a **separate name** (`InventoryAgent-Demo`) so this walkthrough
> does **not** disturb the pre-provisioned **`InventoryAgent`** that already powers the web app and Teams.
> The tools and instructions are identical — only the name differs. Remove it any time with
> `client.agents.delete("InventoryAgent-Demo")`.
""")

code(r'''
from azure.ai.projects.models import (
    PromptAgentDefinition, MCPTool,
)

INSTRUCTIONS = """You are InventoryAgent, the operations copilot for Zava — a DTC athletic apparel brand
(ZavaCore Field: Core, Pro, Premium, Elite; Tops/Tees, Shorts, Pants; sizes S/M/L/XL). Inventory is stored
across 7 distribution centers (Memphis, Charlotte, Seattle, Dallas, Newark, Reno, Columbus).

Tool routing:
1. zava_kb___knowledge_base_retrieve (Foundry IQ) — ANY policy, procedure or rule question: returns &
   exchanges, shipping SLAs, reorder policy, sizing/fabric care, supplier onboarding. Quote the citation.
2. zava_tools___* — live operational data: get_product_stock, get_inventory_alerts, get_line_stock,
   get_inventory_summary, list_products, lookup_order, track_shipment.
3. Fabric Data Agent — historical/aggregate analytics: revenue by product line, sales trends, comparisons.

HARD ROUTING RULE: if the question contains policy, procedure, rule, threshold, SLA, window, eligible,
return, exchange, refund, sizing, care or supplier — call zava_kb___knowledge_base_retrieve FIRST and
answer from its result. Live numbers are NOT documented policy; never infer one from the other.

Be concise and lead with the number/answer. Name facilities and SKUs. For critical stock, say how many
alerts exist and call out the MOST URGENT first. Never invent SKUs, quantities, or policies.

Formatting: reply in GitHub-flavored Markdown. When listing multiple items with attributes, use a compact
Markdown table with clear headers; use bold for key numbers and cite the source for policy answers."""

tools = [
    MCPTool(server_label="zava_toolbox",
            server_url=f"{PROJECT}/toolboxes/{TOOLBOX}/mcp?api-version=v1",
            require_approval="never", project_connection_id="zava-toolbox-mcp"),
    MCPTool(server_label="zava_kb", server_url=KB_MCP_URL, require_approval="never",
            allowed_tools=["knowledge_base_retrieve"], project_connection_id="zava-kb-mcp"),
]
# (the Fabric Data Agent tool is added in section 6)

# Use a DISTINCT name so this demo does NOT overwrite the production "InventoryAgent"
# that powers the web app / Teams. Change it freely for your own runs.
AGENT_NAME = "InventoryAgent-Demo"

agent = client.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(model=MODEL, instructions=INSTRUCTIONS, tools=tools),
)
print("Created agent:", agent.name, "version", getattr(agent, "version", "?"))
''')

md(r"""
## 5️⃣ Talk to the agent

We invoke the agent through the **OpenAI-compatible Responses API** exposed by the project
(`client.get_openai_client()`), passing an `agent_reference`. The agent runs the tool-calling loop
automatically: it decides to call the MCP tools or the AI Search KB, then composes the final answer.

Try the three canonical scenarios (they map to the reference UI):
""")

code(r'''
oai = client.get_openai_client()

def ask(question: str):
    resp = oai.responses.create(
        model=MODEL,
        input=question,
        extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
    )
    print("Q:", question)
    print("A:", resp.output_text, "\n")

ask("What are my most critical stock issues right now?")              # -> MCP get_inventory_alerts
ask("How many units of ZCPTM-SS-S-B0 do we have across facilities?")  # -> MCP get_product_stock
ask("What's our return policy for worn or opened apparel?")           # -> KB (Azure AI Search) with citation
''')

md(r"""
### 💡 What just happened

- *"most critical stock issues"* → the agent called **`get_inventory_alerts`** on the Zava MCP server, which
  read live inventory from the Zava API, and summarised the most urgent items (0 on-hand first).
- *"how many units of ZCPTM-SS-S-B0"* → **`get_product_stock`** returned the per-facility breakdown.
- *"return policy for worn apparel"* → the agent called **`knowledge_base_retrieve`** on the **Foundry IQ**
  knowledge base, which planned the query, retrieved from `zava-docs` and returned a synthesised answer
  **with a citation** — grounded, not hallucinated.

The exact same agent handles both **unstructured** (docs) and **structured/live** (API) questions.
""")

md(r"""
### 🔍 Tracing what the agent actually did

`resp.output_text` is only the last line of the story. The **`resp.output` list is the trace**: every tool
listing, every MCP call with its arguments and raw result, every citation, and the token usage. For a
*prompt agent* this is the observability surface — the service runs the loop, and it reports back exactly
what it ran.

| Item type | What it means |
|---|---|
| `mcp_list_tools` | the agent discovered the tools of one MCP server (`server_label`) |
| `mcp_call` | one tool invocation: `name`, `arguments`, `output`, `error`, `status` |
| `message` | the final answer, with `annotations` carrying knowledge-base citations |

This is the same data the web app renders in its **Traces** panel, and what the **Foundry portal → Tracing**
tab shows for each run.
""")

code(r'''
import json

oai = client.get_openai_client()

def trace_run(question: str):
    """Run the agent and print the full execution trace from the response items."""
    resp = oai.responses.create(
        model=MODEL,
        input=question,
        extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
    )
    print("Q:", question, "\n")
    for item in resp.output or []:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        kind = data.get("type")

        if kind == "mcp_list_tools":
            names = [t.get("name") for t in data.get("tools", [])]
            print(f"[tools ] {data.get('server_label'):<14s} {len(names)} tools: {', '.join(names[:4])}…")

        elif kind == "mcp_call":
            status = "ERROR" if data.get("error") else data.get("status", "ok")
            print(f"[call  ] {data.get('name')}  ({status})")
            print(f"         args   : {data.get('arguments')}")
            print(f"         result : {str(data.get('output') or '')[:160]}")

        elif kind == "message":
            for content in data.get("content", []):
                for note in content.get("annotations") or []:
                    print(f"[cite  ] {note.get('title') or note.get('file_id') or note}")
            print(f"[answer] {str(data.get('content', [{}])[0].get('text', ''))[:220]}…")

    usage = resp.usage
    print(f"\n[usage ] in={usage.input_tokens} out={usage.output_tokens} total={usage.total_tokens}"
          f"  (cached={usage.input_tokens_details.cached_tokens})")
    return resp

resp = trace_run("Which SKUs are critical at Charlotte?")
''')

md(r"""
> **Read the trace, find the bug.** In the run above the agent called
> `get_inventory_alerts(facility="Charlotte", severity="critical")` and got `{"alerts": []}` — so it answered
> *"no critical alerts at Charlotte"*. But the Zava API keys facilities by **code** (`FC-CLT`), not by city,
> so the filter silently matched nothing. Without the trace the answer looks confident and correct; with it,
> the fix is obvious (teach the agent the facility codes in its instructions, or make the tool accept both).
> This is exactly the failure the `zava_answer_grounding` evaluator catches in section 9.

**Where traces live in production**

| Surface | What you get |
|---|---|
| Foundry portal → **Tracing** | every run of the agent, with the same tool calls and citations, searchable |
| Application Insights | the raw spans when the app is OTel-instrumented (see notebook 02 for the `configure_otel_providers()` setup and a KQL query over `dependencies`) |
| Web app **Traces** panel | `webapp/inventory-dashboard` renders `resp.output` live, one row per item |
""")

md(r"""
## 6️⃣ Analytics — the **Fabric Data Agent**

For *analytical* questions ("How did Elite line sales this month compare to last month?", "What is revenue
by product line?"), Zava's structured data (`data/structured/`) is loaded into a **Microsoft Fabric**
lakehouse and a **semantic model**, and a **Fabric Data Agent** (`ZavaDataAgent`) is published on top of it
(see `data/semantic-model/create_data_agent.py`). It translates natural language into DAX and returns the
result — no SQL, no hand-written queries.

There are **two different Fabric tool types** in the SDK, and picking the wrong one costs a day:

| | `FabricIQPreviewTool` (`fabric_iq_preview`) | **`MicrosoftFabricPreviewTool`** (`fabric_dataagent_preview`) |
|---|---|---|
| Wiring | `server_url` + connection | `project_connections: [{project_connection_id}]` |
| Connection | Fabric/AAD connection | a **CustomKeys** connection whose `metadata.type = "fabric_dataagent_preview"` |
| Auth | needs a *delegated user* token → Entra app + tenant admin consent | works with the connection alone |
| Result here | **401** | ✅ works |

We use the second one. The `fabric_zava_dataagent` connection is created in the Foundry portal
(*Data Agent* tool on the agent) or via ARM; `create_agent.py` then just references it by name.
""")

code(r'''
from azure.ai.projects.models import (
    MicrosoftFabricPreviewTool, FabricDataAgentToolParameters,
)

fabric_tool = MicrosoftFabricPreviewTool(
    fabric_dataagent_preview=FabricDataAgentToolParameters(
        project_connections=[{"project_connection_id": "fabric_zava_dataagent"}]
    )
)

client.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(model=MODEL, instructions=INSTRUCTIONS,
                                     tools=tools + [fabric_tool]),
)

print(ask("What is total revenue by product line?"))
''')

md(r"""
## 7️⃣ The web app — text + **voice** + dashboard

`webapp/inventory-dashboard/` hosts the experience shown at the top: a chat panel (text **and voice**, using
the **Azure AI Foundry Voice Live** API with the `gpt-realtime-mini` deployment) next to a live inventory
dashboard. The dashboard reads KPIs and product cards from the **Zava API** (`/inventory/summary`,
`/product-lines`, `/inventory/alerts`), and the chat talks to this **InventoryAgent**.

Run it locally with `webapp/inventory-dashboard/README.md`. The voice path is documented there; final
activation of Voice Live may require enabling the preview in your tenant.
""")

md(r"""
## 8️⃣ Publish to Microsoft **Teams**

Foundry can publish a prompt agent to **Teams** (it provisions an Azure Bot + an M365 app). Because this
needs Microsoft 365 and **tenant admin consent**, it's a guided/manual step:

1. In the [Foundry portal](https://ai.azure.com) → your project → **InventoryAgent** → **Publish → Teams**.
2. Approve the Azure Bot + M365 app registration (admin consent).
3. Install the generated Teams app package for your team.

> Note: MCP **identity passthrough is not supported in Teams** — the agent uses the project managed identity
> when calling tools. That's fine for Zava's tools, which authorize at the service level.
""")

md(r"""
## 9️⃣ Evaluations — **built-in**, **custom** and **rubric**

An agent is only as good as what you can measure. Microsoft Foundry runs evaluations **as a service**: you
describe the data, list the *testing criteria*, and the service generates the responses, scores them and
stores everything in your project — so results show up in **Foundry portal → Evaluations** (and in the web
app's *Evaluations* tab) instead of only in your terminal.

Three flavours of evaluator, all usable in the same run:

| Flavour | What it is | Use it for |
|---|---|---|
| **Built-in** | Microsoft-curated evaluators referenced by name (`builtin.relevance`, `builtin.intent_resolution`, `builtin.task_adherence`, `builtin.violence`, …) | quality, agent behaviour, safety — the baseline |
| **Custom** | Your own evaluator registered in the project catalog: **code-based** (a sandboxed Python `grade()`) or **prompt-based** (an LLM judge prompt) | deterministic fact checks, domain rules, house style |
| **Rubric** | Weighted criteria (`dimensions`) an LLM judge scores 1–5 each, normalised to 0–1 | "what does *good* mean for **this** agent" |

A cloud evaluation is always the same three steps:

1. **Define** — a `data_source_config` (the shape of your rows) + `testing_criteria` (the evaluators).
2. **Create** — `openai_client.evals.create(...)` returns an *evaluation* (a container for runs).
3. **Run** — `openai_client.evals.runs.create(...)` points at the data and, optionally, at a **target**
   (a model or an agent) that generates the answers to be scored.

We use an **agent target**: Foundry sends each question to the live InventoryAgent, captures the answer
*including its MCP tool calls*, and scores that.
""")

code(r'''
# The evaluation dataset: 10 real Zava questions with ground truth + the facts an answer must contain.
# (agents/inventory-agent/evals/inventory_eval.jsonl — 6 tool questions, 4 knowledge-base questions)
import json

EVAL_DATASET = os.path.join("..", "agents", "inventory-agent", "evals", "inventory_eval.jsonl")
rows = [json.loads(line) for line in open(EVAL_DATASET, encoding="utf-8") if line.strip()]
print(f"{len(rows)} rows; first row:")
print(json.dumps(rows[0], indent=2)[:400])

# Datasets are versioned artefacts of the project, reusable across runs and visible in the portal.
# Versions are immutable, so bump until one is free (keeps re-running this cell painless).
def upload_dataset(name, file_path):
    last = None
    for version in range(1, 50):
        try:
            return client.datasets.upload_file(name=name, version=str(version), file_path=file_path)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"could not upload {name}: {last}")

dataset = upload_dataset("zava-inventory-eval", EVAL_DATASET)
print("\ndataset id:", dataset.id)
''')

md(r"""
### 9️⃣.1 Built-in evaluators

Reference them by name in a `TestingCriterionAzureAIEvaluator`. Two things matter:

- **`data_mapping`** wires your data to the evaluator's inputs. `{{item.<field>}}` reads the dataset row;
  `{{sample.output_text}}` is the agent's final text and `{{sample.output_items}}` is its *full* structured
  output (messages **and** tool calls) — agent evaluators want the latter.
- **`initialization_parameters`** carries the judge model (`deployment_name`) and optional `threshold`.
  Safety evaluators such as `builtin.violence` run on the Content Safety service and need no model at all.
""")

code(r'''
from azure.ai.projects.models import TestingCriterionAzureAIEvaluator

JUDGE = MODEL   # gpt-4.1 — the LLM judge for AI-assisted evaluators

builtin_criteria = [
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="relevance", evaluator_name="builtin.relevance",
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_text}}"},
    ),
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="intent_resolution", evaluator_name="builtin.intent_resolution",
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_items}}"},
    ),
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="task_adherence", evaluator_name="builtin.task_adherence",
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_items}}"},
    ),
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="violence", evaluator_name="builtin.violence",
        initialization_parameters={},        # service-based safety evaluator: no judge model
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_text}}"},
    ),
]

# The full catalog available in your project:
for e in client.beta.evaluators.list(type="builtin"):
    print(" ", e.name)
''')

md(r"""
### 9️⃣.2 Custom evaluator — **code-based**

A code-based evaluator is a Python function `grade(sample, item) -> float` (0.0–1.0, higher is better) that
Foundry runs in a **sandbox**: no network, 2 minutes and 2 GB per call, with numpy/pandas/rapidfuzz
available. Perfect for the checks an LLM judge should never be asked to do — exact numbers, formats, IDs.

Ours answers a question no generic evaluator can: *did the agent actually report the Zava facts?* Each row
carries a `must_include` list (alternatives separated by `|`), and the score is the fraction found.

> In a **dataset** evaluation you read `item["response"]`; with a **model/agent target** the generated text
> arrives as `item["sample"]["output_text"]`. The code below handles both.
""")

code(r'''
from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

ANSWER_GROUNDING_CODE = """
def grade(sample: dict, item: dict) -> float:
    # Fraction of the required Zava facts that appear in the answer.
    try:
        response = item.get("sample", {}).get("output_text") or item.get("response") or ""
        required = item.get("must_include") or []
        if isinstance(required, str):
            required = [required]
        if not required:
            return 1.0 if response.strip() else 0.0
        haystack = response.lower().replace(",", "")
        hits = 0
        for entry in required:
            options = [o.strip().lower().replace(",", "") for o in str(entry).split("|") if o.strip()]
            if any(o in haystack for o in options):
                hits += 1
        return round(hits / len(required), 4)
    except Exception:
        return 0.0
"""

code_evaluator = client.beta.evaluators.create_version(
    name="zava_answer_grounding",
    evaluator_version={
        "name": "zava_answer_grounding",
        "categories": [EvaluatorCategory.QUALITY],
        "display_name": "Zava Answer Grounding",
        "description": "Fraction of the required Zava facts that appear in the answer (deterministic).",
        "definition": {
            "type": EvaluatorDefinitionType.CODE,
            "code_text": ANSWER_GROUNDING_CODE,
            "init_parameters": {
                "type": "object",
                "properties": {"deployment_name": {"type": "string"}, "pass_threshold": {"type": "number"}},
                "required": ["deployment_name", "pass_threshold"],
            },
            "metrics": {"result": {"type": "continuous", "desirable_direction": "increase",
                                   "min_value": 0.0, "max_value": 1.0}},
            "data_schema": {
                "type": "object", "required": ["item"],
                "properties": {"item": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "ground_truth": {"type": "string"},
                    "must_include": {"type": "array"},
                }}},
            },
        },
    },
)
print("registered:", code_evaluator.name, "v" + str(code_evaluator.version))
''')

md(r"""
### 9️⃣.3 Custom evaluator — **prompt-based**

Same catalog, different engine: instead of Python you supply a **judge prompt**. Template variables use
`{{double_braces}}` and map to your data through `data_mapping`. The prompt must return
`{"result": <score>, "reason": "<why>"}` — ordinal (1–5 here), continuous, or binary.

Use it for the judgements code can't make. Ours encodes Zava's house style: *is this a briefing Maya can act
on while standing in a warehouse?*
""")

code(r'''
OPS_BRIEFING_PROMPT = """You grade answers written for Maya, a Zava inventory operations manager
who is standing on a warehouse floor. A great answer is a short operational briefing: it leads with
the number or status that matters, names the facility or SKU it refers to, and ends with the action
to take. A poor answer is a wall of prose, hedges without numbers, or buries the decision.

Rate the answer between one and five:

1 - Unusable: no numbers, no entities, or off-topic.
2 - Vague: mentions the topic but gives no actionable figures or entities.
3 - Acceptable: correct and readable, but padded or missing the next action.
4 - Good: concise, quantified, names SKUs/facilities, minor padding.
5 - Excellent: leads with the decisive number, names SKUs/facilities, states the next action, no filler.

Question:
{{query}}

Answer:
{{response}}

Output Format (JSON):
{
  "result": <integer from 1 to 5>,
  "reason": "<one sentence explaining the score>"
}
"""

prompt_evaluator = client.beta.evaluators.create_version(
    name="zava_ops_briefing",
    evaluator_version={
        "name": "zava_ops_briefing",
        "categories": [EvaluatorCategory.QUALITY],
        "display_name": "Zava Ops Briefing Quality",
        "description": "LLM judge: is the answer a concise, quantified operational briefing (1-5)?",
        "definition": {
            "type": EvaluatorDefinitionType.PROMPT,
            "prompt_text": OPS_BRIEFING_PROMPT,
            "init_parameters": {
                "type": "object",
                "properties": {"deployment_name": {"type": "string"}, "threshold": {"type": "number"}},
                "required": ["deployment_name", "threshold"],
            },
            "data_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "response": {"type": "string"}},
                "required": ["query", "response"],
            },
            "metrics": {"custom_prompt": {"type": "ordinal", "desirable_direction": "increase",
                                          "min_value": 1, "max_value": 5}},
        },
    },
)
print("registered:", prompt_evaluator.name, "v" + str(prompt_evaluator.version))
''')

md(r"""
### 9️⃣.4 **Rubric** evaluator

A rubric is a set of weighted **dimensions**; an LLM judge scores every applicable dimension 1–5 and the
overall score is the weighted average normalised to 0–1, with a per-dimension reason. This is the
recommended *primary* measure of agent quality, because it states your criteria explicitly.

You can hand-author a rubric (below) or **generate** one from the agent's own context — Foundry reads the
agent's instructions and tools and proposes dimensions. Set `GENERATE_RUBRIC = True` to try that path
(it runs an LLM job and takes a couple of minutes).
""")

code(r'''
GENERATE_RUBRIC = False   # True -> let Foundry propose the dimensions from the agent's instructions

INVENTORY_RUBRIC_DIMENSIONS = [
    {"id": "source_routing", "weight": 9, "description":
     "Routes the question to the right source: live stock/alert questions call the Zava MCP toolbox, "
     "policy/how-to questions use the Foundry IQ knowledge base."},
    {"id": "numeric_fidelity", "weight": 8, "description":
     "Every quantity, SKU, facility code and status comes from a tool or knowledge-base result. "
     "No invented or rounded-away numbers."},
    {"id": "operational_completeness", "weight": 5, "description":
     "Answers the whole question: on-hand versus reorder point, the facility breakdown when asked, "
     "and the affected SKUs rather than only a count."},
    {"id": "citation_discipline", "weight": 4, "description":
     "Policy answers cite the Zava document they came from; tool answers make clear the data is live."},
    {"id": "briefing_clarity", "weight": 3, "description":
     "Concise and scannable: leads with the decisive number and closes with the recommended action."},
    {"id": "general_quality", "weight": 5, "always_applicable": True, "description":
     "Other important quality factors not covered by the listed criteria."},
]

if GENERATE_RUBRIC:
    import time
    from azure.ai.projects.models import (
        AgentEvaluatorGenerationJobSource, EvaluatorGenerationInputs, EvaluatorGenerationJob, JobStatus,
    )
    job = client.beta.evaluators.create_generation_job(job=EvaluatorGenerationJob(
        inputs=EvaluatorGenerationInputs(
            model=JUDGE,
            evaluator_name="zava_inventory_rubric",
            evaluator_display_name="Zava Inventory Quality (generated)",
            sources=[AgentEvaluatorGenerationJobSource(agent_name=AGENT_NAME)],
        )))
    while job.status not in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
        time.sleep(10)
        job = client.beta.evaluators.get_generation_job(job.id)
    rubric = job.result
else:
    rubric = client.beta.evaluators.create_version(
        name="zava_inventory_rubric",
        evaluator_version={
            "name": "zava_inventory_rubric",
            "categories": [EvaluatorCategory.AGENTS],
            "display_name": "Zava Inventory Quality",
            "description": "Weighted quality criteria for Zava inventory answers.",
            "definition": {
                "type": EvaluatorDefinitionType.RUBRIC,
                "dimensions": INVENTORY_RUBRIC_DIMENSIONS,
                "pass_threshold": 0.6,
            },
        },
    )

print("rubric:", rubric.name, "v" + str(rubric.version))
for d in rubric.definition.dimensions:
    print(f"  - {d.id} (weight {d.weight})")
''')

md(r"""
### 9️⃣.5 Run it against the live agent

Now the three flavours go into **one** `testing_criteria` list. The run uses
`azure_ai_target_completions` with an `azure_ai_agent` target, so Foundry itself calls the agent for every
row before scoring — no response collection on your side.
""")

code(r'''
from openai.types.eval_create_params import DataSourceConfigCustom

testing_criteria = builtin_criteria + [
    # custom, code-based (no data_mapping: the whole item is passed to grade())
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="answer_grounding", evaluator_name="zava_answer_grounding",
        initialization_parameters={"deployment_name": JUDGE, "pass_threshold": 0.99}, data_mapping={},
    ),
    # custom, prompt-based (deliberately strict: needs 4/5 to pass)
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="ops_briefing", evaluator_name="zava_ops_briefing",
        initialization_parameters={"deployment_name": JUDGE, "threshold": 4},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_text}}"},
    ),
    # rubric
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="inventory_rubric", evaluator_name=rubric.name,
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_items}}"},
    ),
]

evaluation = oai.evals.create(
    name="Zava InventoryAgent quality",
    data_source_config=DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ground_truth": {"type": "string"},
                "must_include": {"type": "array"},
                "expected_tool": {"type": "string"},
            },
            "required": ["query"],
        },
        include_sample_schema=True,     # exposes {{sample.output_text}} / {{sample.output_items}}
    ),
    testing_criteria=testing_criteria,
)

eval_run = oai.evals.runs.create(
    eval_id=evaluation.id,
    name="inventory-builtin-custom-rubric",
    data_source={
        "type": "azure_ai_target_completions",
        "source": {"type": "file_id", "id": dataset.id},
        "input_messages": {"type": "template", "template": [
            {"type": "message", "role": "user", "content": {"type": "input_text", "text": "{{item.query}}"}},
        ]},
        "target": {"type": "azure_ai_agent", "name": AGENT_NAME},
    },
)
print("evaluation:", evaluation.id)
print("run       :", eval_run.id)
''')

code(r'''
# Poll until the run finishes, then read the aggregate scorecard.
import time

while True:
    run = oai.evals.runs.retrieve(run_id=eval_run.id, eval_id=evaluation.id)
    if str(run.status) in ("completed", "failed", "canceled"):
        break
    print("status:", run.status)
    time.sleep(10)

counts = run.result_counts
print(f"\nstatus={run.status}  rows: {counts.passed}/{counts.total} passed\n")
for c in run.per_testing_criteria_results:
    total = c.passed + c.failed
    print(f"  {c.testing_criteria:<22s} pass {c.passed:>2d}  fail {c.failed:>2d}   "
          f"{(c.passed / total if total else 0):.0%}")

print("\nOpen in the Foundry portal:\n", run.report_url)
''')

code(r'''
# Row-level detail: what each evaluator said about each answer.
for item in list(oai.evals.runs.output_items.list(run_id=eval_run.id, eval_id=evaluation.id))[:3]:
    source = item.datasource_item or {}
    print("Q:", str(source.get("query"))[:90])
    for result in item.results:
        data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        print(f"   {data.get('name'):<20s} score={data.get('score')!s:<8s} {data.get('label')}"
              f"  {(data.get('reason') or '')[:100]}")
    print()
''')

md(r"""
### 💡 What you just did

- Uploaded a **versioned dataset** to the project and pointed an evaluation at the **live agent** as a target.
- Scored every answer with **built-in** evaluators (relevance, intent resolution, task adherence, violence),
  **custom** evaluators — one code-based (`zava_answer_grounding`, deterministic fact checking) and one
  prompt-based (`zava_ops_briefing`, an LLM judge for house style) — and a **rubric** with weighted
  dimensions and per-dimension reasons.
- Everything lives in the project: open `run.report_url` for the **Foundry portal** view, or the web app's
  **Evaluations** tab (`webapp/inventory-dashboard`), which reads the very same runs through
  `GET /api/evals`.

The whole flow is scripted in `agents/inventory-agent/run_eval.py`:

```powershell
.\.venv\Scripts\python.exe agents/inventory-agent/run_eval.py            # all 10 rows
.\.venv\Scripts\python.exe agents/inventory-agent/run_eval.py --limit 3  # quick smoke run
```

> **Next steps in the portal:** schedule the same evaluation, or turn it into **continuous evaluation** so a
> sample of production traffic is scored automatically and quality regressions surface on a dashboard.
""")

md(r"""
## 🔄 Recap & next steps

You built a Foundry **prompt agent** that combines:

| Capability | Backed by |
|---|---|
| Policy / how-to answers with citations | **Foundry IQ** knowledge base `zava-kb` (over Azure AI Search `zava-docs`) |
| Live stock, alerts, order lookups | **MCP** tools bundled in the **`zava-toolbox`** (Zava MCP server → Zava API) |
| Analytics | **Fabric Data Agent** (`fabric_dataagent_preview`) |
| Text + voice UI + dashboard | `webapp/inventory-dashboard` (Voice Live) |
| Reach | **Teams** publishing |
| Quality | **Evaluations** — built-in + custom (code & prompt) + rubric, run in the cloud |

**Next:** open `02_delivery_support_agent.en.ipynb` to build the **DeliverySupport Agent** — a *hosted* agent
using the **Microsoft Agent Framework**, with a **Model Router**, a `lookupOrder` tool, **memory**, **traces
+ continuous evaluations**, and **voice-live**.

To remove all Azure resources when you're done: `scripts/teardown.ps1`.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("Wrote", OUT, "with", len(cells), "cells")
