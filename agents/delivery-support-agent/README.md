# Zava DeliverySupport Agent

Microsoft Agent Framework (MAF) agent for ZavaCore Field order tracking.

## What it does

- Builds a `DeliverySupport` chat agent with the Foundry `model-router` deployment.
- Uses `DefaultAzureCredential` locally and managed identity in hosted environments.
- Calls the live Zava order API through function tools:
  - `lookup_order(order_id)`
  - `track_shipment(order_id="", tracking_number="")`
- Reuses a MAF `AgentSession` for multi-turn memory, so follow-ups like "When will it arrive?" resolve against the previously discussed order.
- Remembers the customer **across conversations** with **Foundry Memory** (see below).

## Long-term memory (Foundry Memory)

`AgentSession` only remembers the *current* conversation. Foundry **Memory** adds durable, per-customer
recall — the agent still knows your name, your drop-off preference and which orders you follow *days
later, in a brand new session*.

| Piece | Where |
|---|---|
| Memory store (`zava_delivery_memory`) | `create_memory_store.py` — idempotent, run once |
| Recall + persist logic | `src/memory.py` → `ZavaMemory` + `FoundryMemoryProvider` |
| Wiring into the agent | `src/agent.py` → `create_delivery_support_agent(memory_scope=...)` |
| Cross-session proof | `test_memory.py` |

**How it works**

1. `create_memory_store.py` creates a `MemoryStoreDefaultDefinition` with a chat model
   (`FOUNDRY_MODEL_DEPLOYMENT_NAME`), an embedding model (`EMBEDDING_DEPLOYMENT_NAME`),
   `chat_summary_enabled` + `user_profile_enabled`, a TTL, and `user_profile_details` that tell
   Foundry *which* facts matter for a delivery agent (name, address notes, drop-off preference,
   notification channel, tracked orders).
2. `FoundryMemoryProvider` is a MAF **`ContextProvider`**:
   - `before_run` → `search_memories(scope, query)` and appends the recalled facts to the run
     instructions, so the model sees them as context (never as fake chat history).
   - `after_run` → `begin_update_memories(scope, messages)`; Foundry extracts durable memories
     **asynchronously**, debounced by `DELIVERY_MEMORY_UPDATE_DELAY` seconds.
3. A **scope** is one customer. The demo pins a single scope (`DELIVERY_MEMORY_SCOPE`); a real app
   passes the signed-in user id (Foundry also supports the `{{$userId}}` template plus the
   `x-memory-user-id` header for prompt agents).

> **Why a `ContextProvider` and not the `memory_search_preview` tool?** The built-in
> `MemorySearchPreviewTool` is available to **Foundry prompt agents**. DeliverySupport is a *hosted MAF
> agent*, so it uses the memory APIs directly — the documented "your backend calls the memory store"
> pattern. InventoryAgent (a prompt agent) could use the tool instead.

```powershell
# once
..\..\.venv\Scripts\python.exe .\create_memory_store.py
# prove cross-session recall (session 1 states preferences, session 2 is a brand new agent)
..\..\.venv\Scripts\python.exe .\test_memory.py
```

Configuration (`.env`): `DELIVERY_MEMORY_ENABLED`, `DELIVERY_MEMORY_STORE_NAME`,
`DELIVERY_MEMORY_SCOPE`, `DELIVERY_MEMORY_UPDATE_DELAY`, `DELIVERY_MEMORY_TTL_DAYS`.

The web app shows the same store live in the delivery dashboard ("Foundry Memory" panel, with a
one-click **forget everything** reset) and adds a `memory` entry to the traces panel each turn.

> The agent's identity needs the **Azure AI User** role on the Foundry account to read/write memories.

## Local setup (PowerShell)

From the repo root:

```powershell
.\.venv\Scripts\python.exe -m pip install --pre -r .\agents\delivery-support-agent\requirements.txt
.\.venv\Scripts\python.exe .\agents\delivery-support-agent\test_agent.py
```

The scripts call `load_dotenv(override=False)`, so environment variables injected by Foundry or your shell win over repo `.env` values.

## Run the hosted-agent HTTP server locally

```powershell
Set-Location .\agents\delivery-support-agent
..\..\.venv\Scripts\python.exe .\main.py
```

The `agent_framework_foundry_hosting.ResponsesHostServer` default port is `8088`.

Smoke test:

```powershell
(Invoke-WebRequest -Uri http://localhost:8088/responses -Method POST -ContentType "application/json" -Body '{"input":"Track order 23518"}').Content
```

## Deployment (live in this demo)

This agent is deployed **two ways**, both against the live Foundry project:

1. **Foundry Agent Service (hosted)** — registered and **active** as `DeliverySupport` (version 2) via
   direct code deploy:
   ```powershell
   azd env set AZURE_AI_PROJECT_ENDPOINT "<project-endpoint>"
   azd deploy delivery-support-agent --no-prompt
   azd ai agent show --output json
   azd ai agent invoke "What's the status of order 23518?"
   ```
   > ⚠️ **Preview note:** the Foundry hosted runtime (`azure-ai-agentserver-responses` preview) currently
   > mishandles tool-call arguments for this MAF agent (the model emits an empty `lookup_order` argument and
   > the run fails with `name must be a non-empty string`). This is a hosted-runtime/`model-router` +
   > Responses-protocol preview issue, **not** an issue with the agent code — the identical container runs
   > correctly via its own `ResponsesHostServer` (below). The agent's managed identity needs
   > **Cognitive Services OpenAI User** on the Foundry account (granted during deploy).

2. **Azure Container Apps (verified working runtime)** — the same container (`main.py` →
   `ResponsesHostServer`) deployed to ACA, which handles tool-calling + memory correctly:
   - Endpoint: `${DELIVERY_AGENT_ENDPOINT}` (`https://zava-delivery.<env>.azurecontainerapps.io/responses`).
   - Verified: `lookup_order("23518")` → *Delayed - Weather, Memphis DC, ETA Feb 17, no action required.*
   ```powershell
   ./scripts/deploy_backend.ps1   # or: az acr build + az containerapp create (see repo)
   ```

Do not store API keys; this agent uses Microsoft Entra authentication only.
