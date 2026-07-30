# Zava · Microsoft Foundry Agents Demo

> 🇧🇷 [Versão em Português](./README.pt-BR.md)

A hands-on, **easy-to-replicate** demo/tutorial for the fictitious retailer **Zava** on **Microsoft
Foundry**. It contains **two demos** that share one coherent scenario so you can clone it, customize the
company, and reuse the patterns:

1. **Two production-shaped agents** — *InventoryAgent* (Foundry prompt agent) and *DeliverySupport*
   (hosted Microsoft Agent Framework agent).
2. **Multi-framework orchestration** — three agents built with *different* frameworks (LangGraph, GitHub
   Copilot SDK, Foundry prompt agent), orchestrated by the Microsoft Agent Framework and hosted on Foundry.

The centerpiece is **six didactic Jupyter notebooks** (three topics × EN/PT-BR) that explain the concepts,
show the diagrams, and run the code step by step. The rest of the repo is the working stack that the
notebooks orchestrate.

---

## The two agents

### 1. InventoryAgent — *prompt agent* (Foundry Agent Service SDK)
Answers inventory questions for Zava operations staff.

- **Knowledge base** via **Foundry IQ** (Azure AI Search *knowledge base* `zava-kb` over the `zava-docs` index) — answers with citations.
- **Tools** via a **Foundry Toolbox** (`zava-toolbox`) wrapping the **real Zava MCP server**.
- **Fabric Data Agent** (built over a Fabric semantic model) attached through the `fabric_dataagent_preview` tool.
- **Web app** for **text + voice** (Voice Live) chat with a live **inventory dashboard**.
- **Published to Microsoft Teams**.
- **Evaluations** configured — built-in + custom (code & prompt) + rubric, run in the cloud and visible in the Foundry portal and the web app **Evaluations** tab.

### 2. DeliverySupport Agent — *hosted agent* (Microsoft Agent Framework)
Handles order tracking for Zava customers.

- **Model Router** deployment as the model.
- **`lookupOrder`** tool against "3rd-party" systems (Zava APIs / MCP).
- **Session memory** across turns **plus [Foundry Memory](./agents/delivery-support-agent/README.md#long-term-memory-foundry-memory)** — durable per-customer recall (name, drop-off preference, notification channel, tracked orders) that survives across conversations, wired through a MAF `ContextProvider`.
- **Traces + Evaluations + Continuous Evaluations** (App Insights).
- **Voice-live** interaction.

---

## Demo #2 — Multi-framework agent orchestration (MAF + Foundry Hosted Agents)

A second, self-contained demo shows how to **integrate agents built with different frameworks**, orchestrate
them with the **Microsoft Agent Framework (MAF)** through a common **Agent Harness**, and **host** the
orchestration on **Foundry**. The scenario is a **Zava engineering incident**: the nightly *reorder service*
produced negative reorder quantities. Three agents cooperate in a deterministic pipeline:

| Stage | Agent | Framework | Role |
|-------|-------|-----------|------|
| 1 | **Triage** | **LangGraph** | Classify severity/category/component and route the incident. |
| 2 | **Code Fix** | **GitHub Copilot SDK** | Run a real *plan → execute (shell/fs) → assess → iterate* harness on an **isolated sandbox** until `pytest` passes. |
| 3 | **Compliance** | **Foundry prompt agent** | Review the fix against Zava's engineering policy → approve / needs-changes. |

Each agent is exposed to MAF through a uniform `BaseChatClient` adapter (the **common Agent Harness**),
orchestrated by MAF `SequentialBuilder`, wrapped as a `WorkflowAgent`, and served by `ResponsesHostServer`.
The whole orchestration is registered in Foundry as a **single hosted agent, `IncidentOrchestrator`**
(`azd deploy incident-orchestration`) — heterogeneous frameworks in, one Foundry agent out. The same
container also runs on Azure Container Apps, which the web app uses for the live per-step event stream.
Taught in
**notebook 03** (EN + PT-BR) and runnable live in the web app's **Incident Response** page — a real-time
orchestration **flow diagram** + per-agent **dashboard**. See
[`agents/incident-orchestration/`](./agents/incident-orchestration/).

---

## Architecture

See [`docs/architecture.md`](./docs/architecture.md) for the full diagram and data flows.
Ready-to-run demo prompts for all three agents: [`docs/test-prompts.md`](./docs/test-prompts.md).

```
Clients (Web app · Teams · Voice-live)
        │
        ▼
Azure AI Foundry project  ── InventoryAgent (prompt) ── Foundry IQ KB `zava-kb` ── Azure AI Search (Zava docs)
        │                                     │        └ Fabric Data Agent ── Fabric semantic model (Zava-Demos)
        │                                     └ Toolbox `zava-toolbox` ── Zava MCP server ── Zava REST APIs
        └───────────────── DeliverySupport (hosted, MAF) ── Model Router · lookupOrder
                                              │            └ Foundry Memory `zava_delivery_memory` (per-customer scope)
                                     App Insights (traces + evals)
```

---

## Repository layout

| Path | What it holds |
|------|---------------|
| `notebooks/` | The 6 didactic notebooks (3 topics × EN + PT-BR) — **start here** |
| `infra/` | azd + Bicep IaC (Foundry project, models, AI Search, Container Apps, App Insights) |
| `data/` | Fictitious Zava content: `docs/` (KB), `structured/` (Fabric), `company/`, `semantic-model/` |
| `services/zava-api/` | Zava fictitious REST APIs (FastAPI) |
| `services/zava-mcp/` | The **real** Zava MCP server |
| `agents/inventory-agent/` | InventoryAgent creation scripts, tool wiring, Teams publish, evals |
| `agents/delivery-support-agent/` | DeliverySupport hosted agent (Microsoft Agent Framework) |
| `agents/incident-orchestration/` | **Demo #2**: Triage (LangGraph) + Code Fix (Copilot SDK) + Compliance (Foundry) + MAF harness/orchestration + Foundry hosting |
| `webapp/inventory-dashboard/` | Text + voice + dashboard web app (Inventory · Delivery · **Incident Response**) |
| `scripts/` | Provisioning, RBAC, doc indexing, Fabric load, teardown |
| `docs/` | Architecture, diagrams and the [test-prompt guide](./docs/test-prompts.md) |

---

## Prerequisites

- **Azure subscription** with permission to create resources and assign roles.
- **Azure CLI** (`az`) and **Azure Developer CLI** (`azd`), both logged in.
- **Python 3.11+**, **Node.js 18+**, **Docker**.
- **Microsoft Fabric** license + a workspace (this demo reuses `Zava-Demos`).
- For Teams publishing and Voice Live: **Microsoft 365** and tenant admin consent (manual steps documented).

---

## Quickstart

Windows PowerShell (the scripts are `.ps1`; the notebooks/scripts use Python + the repo `.venv`).

```powershell
# 1. Authenticate
az login

# 2. Provision the core Azure resources into rg-zava-demo (Foundry project + models,
#    Azure AI Search, Container Apps env + ACR, App Insights, connections, RBAC).
#    Writes all endpoints to a repo-root .env
./scripts/provision.ps1

# 3. (Optional) regenerate the fictitious canonical data
python data/structured/generate_data.py

# 4. Deploy the Zava backends (REST API + MCP server) to Azure Container Apps
./scripts/deploy_backend.ps1

# 5. Index the Zava docs into Azure AI Search
python scripts/index_docs.py

# 6. Create the Foundry IQ knowledge base + the zava-toolbox (connections included)
python agents/inventory-agent/setup_foundry_iq_and_toolbox.py --test

# 7. Create the InventoryAgent (toolbox + Foundry IQ + Fabric Data Agent) and smoke-test it
python agents/inventory-agent/create_agent.py --test

# 8. Deploy the DeliverySupport hosted agent (Microsoft Agent Framework)
#    see agents/delivery-support-agent/README.md

# 8b. Deploy the multi-framework orchestration as a Foundry hosted agent (Demo #2)
azd env set GITHUB_TOKEN "<a GitHub token with Copilot access>"
azd deploy incident-orchestration --no-prompt

# 9. Follow the didactic notebooks
#    notebooks/01_inventory_agent.en.ipynb   (or .pt-BR.ipynb)
#    notebooks/02_delivery_support_agent.en.ipynb

# 9. (Demo #2) Multi-framework orchestration — register the Compliance prompt agent,
#    run the pipeline end-to-end, and deploy it to Container Apps.
python agents/incident-orchestration/create_compliance_agent.py
python agents/incident-orchestration/test_orchestration.py     # Triage -> Code Fix -> Compliance (local)
#    The web app "Incident Response" page runs it live in-process; teaching notebook:
#    notebooks/03_multi_agent_orchestration.en.ipynb   (or .pt-BR.ipynb)

# Run the web app locally (Inventory · Delivery · Incident Response)
cd webapp/inventory-dashboard; ../../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8501
```

> A Python virtual environment (`.venv`) with the client libraries is used by the scripts and notebooks.
> Optional: the Fabric Data Agent (analytics) and Teams/Voice-live activation are documented separately
> (`data/semantic-model/`, `agents/inventory-agent/TEAMS.md`) because they need Fabric/M365 admin steps.

---

## Cost & cleanup

This demo provisions **billable** Azure resources (Foundry models, AI Search, Container Apps, App Insights).
Run the teardown script in `scripts/` to delete `rg-zava-demo` and stop incurring cost. Fabric uses the
existing **Trial** capacity by default.

---

## What's live vs. documented

This demo **provisions and runs** the core stack; a few preview / admin-gated pieces are fully coded and
**documented for final activation** (they need Fabric or Microsoft 365 admin actions).

| Component | Status |
|-----------|--------|
| Foundry project + models (`gpt-4.1`, `model-router`, `text-embedding-3-large`, `gpt-realtime-mini`) | ✅ Provisioned live (Bicep) |
| Azure AI Search index `zava-docs` | ✅ Live (indexed, keyless) |
| **Foundry IQ** knowledge base `zava-kb` (+ knowledge source `zava-docs-ks`) | ✅ Live, answer synthesis with citations |
| **Toolbox** `zava-toolbox` (Zava MCP + Foundry IQ) | ✅ Live, versioned, bound via project managed identity |
| Zava REST API + **real MCP server** (Azure Container Apps) | ✅ Deployed live |
| **InventoryAgent** (prompt) — Toolbox + Foundry IQ + Fabric Data Agent | ✅ Live, all three tools verified end-to-end |
| Inventory **web app** (text chat + dashboard) | ✅ Live; voice = preview stub |
| **DeliverySupport** (hosted, MAF) — Model Router + `lookupOrder` + memory | ✅ Built + verified; deploy via `azd` (see agent README) |
| **Foundry Memory** store `zava_delivery_memory` (DeliverySupport, per-customer scope) | ✅ Live — cross-session recall verified locally *and* on the deployed agent |
| Evaluations (all three demos) | ✅ Cloud evaluations — built-in + custom (code & prompt) + rubric; results in the Foundry portal and the web app **Evaluations** tab |
| **Fabric Data Agent** `ZavaDataAgent` (semantic model + published) | ✅ Live, verified answering over its MCP endpoint |
| **Fabric Data Agent** tool on InventoryAgent (`fabric_dataagent_preview`) | ✅ Live, returns revenue-by-line analytics |
| ~~Fabric IQ (`fabric_iq_preview`)~~ | ⛔ Superseded — needs delegated Power BI tenant admin consent; use the Data Agent tool instead |
| **Teams** publishing | 🟡 Documented (needs M365 admin consent) |
| **Voice-live** | 🟡 Realtime model deployed + token pattern; activation documented |
| **Demo #2** — Triage (LangGraph) + Code Fix (Copilot SDK) + Compliance (Foundry prompt agent) | ✅ Built + verified end-to-end (local) |
| **Demo #2** MAF orchestration hosted on Container Apps (`ORCHESTRATION_AGENT_ENDPOINT`) | ✅ Deployed live (used by the web app for the per-step event stream) |
| **Demo #2** orchestration registered as a **Foundry Hosted Agent** (`IncidentOrchestrator`) | ✅ Deployed + verified end-to-end |
| Web app **Incident Response** page (real-time flow diagram + per-agent dashboard) | ✅ Live |

## Which model runs where

| Component | Deployment | Why |
|---|---|---|
| **DeliverySupport** (MAF hosted agent) | `model-router` | Function tools are executed by MAF in-process, not by Foundry. |
| **Triage** (LangGraph) | `model-router` | Plain chat completion in JSON mode — no tools. |
| **Compliance** (Foundry prompt agent) | `model-router` | Prompt agent with **no tools** → router-safe. |
| **InventoryAgent** (Foundry prompt agent) | `gpt-4.1` 📌 | **Pinned** — see below. |
| **Foundry IQ knowledge base** (`zava-kb`) | `gpt-4.1` 📌 | AI Search rejects `model-router` (allow-list: gpt-4o / gpt-4.1 / gpt-5.x). |
| **Eval judge** (`eval.yaml`, `run_eval.py`) | `gpt-4.1` 📌 | A judge must be deterministic, not routed. |
| **Code Fix** (GitHub Copilot SDK) | `claude-sonnet-4.5` | Runs through the Copilot SDK, outside Foundry. |

> 📌 **`model-router` + MCP tools does not work on a Foundry prompt agent.** Reproduced repeatedly and in
> isolation (toolbox MCP alone, with and without `allowed_tools`): the model *lists* the tools
> (`mcp_list_tools` succeeds) but every tool **call** fails with
> `500 tool_function_not_found`. The identical agent on `gpt-4.1` calls
> `zava_tools___get_inventory_alerts` correctly. Preview limitation — re-test after a service refresh.

## Status & disclaimers

- Zava, its data, documents, APIs, and carriers are **entirely fictitious**.
- Several capabilities are **preview** (Foundry IQ, Toolboxes, Fabric Data Agent, hosted agents, Voice Live,
  continuous eval); APIs may change. SDK versions are pinned where possible.
