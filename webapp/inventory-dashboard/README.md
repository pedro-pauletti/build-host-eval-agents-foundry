# Zava Console — tri-agent web app (text + **real Voice Live** + live traces)

A FastAPI + static SPA that lets you interact with **all three** Zava demos by **text and voice**, each with its
own dashboard — matching the reference screenshots in `docs/ux-reference/`:

- **Inventory** view → **InventoryAgent** (Foundry prompt agent). Chat + a live inventory dashboard
  (KPI cards + product-line grids). *"Ask about inventory…"*
- **Delivery** view → **DeliverySupport** (hosted MAF agent, via its Container Apps `/responses` endpoint).
  Chat + an **Order Tracking card** (status, carrier, ETA, last location, recipient, delay reason, notes).
  *"Ask about your delivery…"*
- **Incident** view → the **multi-framework orchestration** (Triage/LangGraph → Code Fix/GitHub Copilot SDK →
  Compliance/Foundry prompt agent). Chat + an **animated MAF Agent Harness diagram** + per-agent dashboard.
- **Evaluations** view → the **Foundry evaluation service**. A read-only report of every evaluation in the
  project: pass rate per testing criterion, badges for **built-in / custom / rubric** evaluators, a link to
  the run in the Foundry portal, and row-level scores with the judge's reasoning.

Switch agents with the **Inventory / Delivery / Incident / Evaluations** tabs. Toggle **Voice Live** with the
mic button.

## Layout — three columns

```
┌ chat ──────────────┬ dashboard ─────────────────┬ traces ──────────┐
│ agent tabs         │ per-view dashboard          │ per-turn trace   │
│ messages (md)      │ (inventory | order | flow)  │ groups: model,   │
│ voice status       │                             │ toolbox, tools,  │
│ suggested prompts  │                             │ KB, citations,   │
│ input + mic        │                             │ tokens           │
└────────────────────┴─────────────────────────────┴──────────────────┘
```

The traces column is toggled with the button in the dashboard header (it auto-hides below 1360 px).

## Traces panel — what runs behind every answer

Every turn creates a **trace group**. `POST /api/chat` returns a `trace` array built from the Responses
payload's non-message output items, so the panel shows the *real* execution, not a simulation:

| Kind | Source | Shows |
|---|---|---|
| `model` | `response.model` + `agent_reference` | deployment + agent name/version |
| `toolbox` | `mcp_list_tools` | each MCP server (`zava_toolbox`, `zava_kb`) and the tools it exposes |
| `tool` | `mcp_call` / `function_call` | tool name, arguments, result |
| `kb` | `mcp_call` on `zava_kb` | **Foundry IQ** knowledge-base retrieval + document count |
| `fabric` | `mcp_call` on the Data Agent | Fabric semantic-model queries |
| `citation` | message `annotations` | grounding sources behind the answer |
| `memory` | **Foundry Memory** store (delivery) | how many memories were in scope for this turn + their contents |
| `todo` | **MAF todo provider** (incident) | every mutation of the shared remediation plan, with the full checklist |
| `usage` | `response.usage` | input/output/total tokens |

## Evaluations tab

Backed by three endpoints in `app/evals_api.py`, all reading the live Foundry project (nothing is stored
locally):

| Endpoint | Returns |
|---|---|
| `GET /api/evals` | evaluations in the project + their latest run summary (pass rate per criterion) |
| `GET /api/evals/{eval_id}/runs` | every run of one evaluation |
| `GET /api/evals/{eval_id}/runs/{run_id}/items` | row-level results: query, answer, per-evaluator score/label/reason |

Populate it by running any of the suites:

```pwsh
.\.venv\Scripts\python.exe agents\inventory-agent\run_eval.py
.\.venv\Scripts\python.exe agents\delivery-support-agent\run_eval.py
.\.venv\Scripts\python.exe agents\incident-orchestration\run_eval.py
```

Voice turns add `voice` entries (session open, your transcript, tool calls, the agent's reply) and the
Incident pipeline adds `harness` / `agent` / `step` / `handoff` entries streamed from the MAF event bus.

## Delivery view — Foundry Memory panel

Under the order card, **Foundry Memory** shows exactly what the hosted DeliverySupport agent remembers
about the customer, read live from the `zava_delivery_memory` store. The panel is **collapsed by
default** (the chevron toggles it; the choice is remembered in `localStorage`):

- **Profile** items — durable facts (name, drop-off preference, notification channel, tracked orders).
- **Past conversation** items — Foundry's rolling chat summaries.
- **Learned behaviour** items — procedural memories, rendered from their `instruction` field.

The 🗑 button calls `DELETE /api/memory` (`delete_scope`) so you can reset between demo runs. Because
Foundry consolidates memories *asynchronously*, the panel re-reads ~8 s after each delivery turn.
The memory itself lives in the agent (`agents/delivery-support-agent/src/memory.py`); the web app is
only an observer.

## Incident view — animated harness

The flow diagram is driven live by the orchestration WebSocket:

- A **harness header** states the orchestration pattern (`SequentialBuilder`), the uniform surface
  (`agent_framework.BaseChatClient`) and where it is hosted, plus a **Parameters** toggle (**collapsed by
  default**, remembered in `localStorage`) revealing the 10 real harness settings (hand-off format, event
  bus, tool approval, loop bound, sandbox isolation, todo provider, observability, …) and the 10
  **harness capabilities** from the MAF *Agent Harnesses* doc, honestly marked
  `active` / `available` / `harness factory`.
- A **Shared plan** checklist renders the MAF **todo provider** live: Triage writes 4 remediation items,
  Code Fix ticks them off from real signals, and Compliance either completes the review item or *appends*
  the changes it requires. Driven by `todo_updated` events from `SharedTodoStore`.
- **Nodes** (`Triage → Code Fix → Compliance`) light up on `agent_started`, show a running elapsed timer, and
  turn green on `agent_completed`. Each node lists its **model deployment** and its **tool chips**, which
  flash as the matching `harness_step` event arrives.
- **Connectors** animate a travelling pulse while data flows, then lock to green.
- **Code Fix** reveals its internal **GitHub Copilot SDK harness loop** (plan → execute → assess) with the
  last few tool steps.
- Below the nodes, the **Agent Harness rail** shows the three `BaseChatClient` adapters
  (`LangGraphTriageClient`, `CopilotCodeFixClient`, `FoundryComplianceClient`) over the **MAF event bus**,
  with a pulse that moves to whichever adapter is currently driving and event names that fire in real time.

All of this comes from `GET /api/orchestration/scenario` (`harness` + per-agent `adapter`/`model`/`tools`),
so it always reflects the real code in `agents/incident-orchestration/src/harness.py`.

The 🗑 **Clear conversation** button resets the whole Incident view, not just the chat: flow nodes go back
to `idle`/`queued` with their timers cleared, the adapter rail goes dark, tool chips un-light, the agent
cards return to *Waiting…*, the shared plan is emptied and the detail column drops the diff / compliance
blocks a run prepended. If a run is still streaming it is aborted first, so a mid-run clear can't keep
repainting the diagram. Traces are deliberately **not** touched — they are global across the three agents
and have their own 🗑 button.

## Real Voice Live (no STT/TTS fallback)
Voice uses the **Azure AI Foundry Voice Live API** via a server-side **broker** (browsers can't set the
`Authorization` header on a native WebSocket):

```
browser  <—WS—>  FastAPI /api/voice/{agent}  <—WS (Entra token)—>  wss://<account>/voice-live/realtime
                                                                    ?api-version=2026-06-01-preview&model=gpt-realtime-mini
```

The broker binds the realtime `gpt-realtime-mini` model with each agent's **instructions + function tools**
(`get_inventory_alerts`, `get_product_stock`, `lookup_order`, `track_shipment`, …), and **executes tool calls
against the live Zava API**. Audio is PCM16 mono 24 kHz; turn-taking uses server VAD. The browser captures the
mic, streams `input_audio_buffer.append`, plays `response.audio.delta`, and renders live transcripts; for the
Delivery agent, a `lookup_order` tool call also refreshes the order card.

**Button states:** idle = blue mic; **active = red with expanding rings + a stop icon**; while the agent is
speaking back it turns green. Your transcription and the agent's reply are both appended to the chat history.
Voice Live is configured for the *inventory* and *delivery* agents, so the button is hidden on the Incident view.

> Voice Live is **preview**. The broker surfaces clear errors if the handshake is rejected (e.g. the preview
> isn't enabled in your tenant). Mic access requires `http://localhost` or HTTPS.


## Run locally

From the repository root (Windows/PowerShell), with the demo already provisioned (repo-root `.env` present):

```powershell
.\.venv\Scripts\python.exe -m pip install -r webapp\inventory-dashboard\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8501 --app-dir webapp\inventory-dashboard
```

Open **http://localhost:8501**, pick **Inventory** or **Delivery**, type a question, and click the mic to talk.

The app reads the repo-root `.env`: `AZURE_AI_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_DEPLOYMENT_NAME`,
`AZURE_AI_ACCOUNT_ENDPOINT`, `REALTIME_DEPLOYMENT_NAME`, `ZAVA_API_BASE_URL`, `DELIVERY_AGENT_ENDPOINT`,
`DELIVERY_MEMORY_*`.
Azure auth is server-side (`DefaultAzureCredential`); no credentials reach the browser.

## API
- `GET  /api/dashboard` — live inventory KPIs + product cards (Zava API, briefly cached).
- `POST /api/chat` — `{message, agent: "inventory"|"delivery", previous_response_id?}` →
  `{answer, response_id, order, trace, memory?}`. Inventory → Foundry Responses API; Delivery → the
  DeliverySupport `/responses` endpoint (returns the looked-up order for the card, plus the Foundry
  Memory snapshot). `trace` powers the traces panel.
- `GET  /api/order/{id}` — order tracking card data (Zava API).
- `GET  /api/memory` — what Foundry Memory currently holds for `DELIVERY_MEMORY_SCOPE`
  (`{enabled, scope, store, items[]}`; 3 s cache, warmed at startup).
- `DELETE /api/memory` — `delete_scope` — forget everything for that customer (demo reset).
- `GET  /api/voice/config` — voice availability + realtime deployment.
- `WS   /api/voice/{agent}` — Voice Live broker (relay + tool execution).
- `GET  /api/orchestration/scenario` — seeded incident, buggy code, tests, **harness parameters +
  capabilities**, and per-agent `adapter` / `model` / `tools`.
- `WS   /api/orchestration/run` — runs the MAF pipeline in-process and streams
  `run_started` / `agent_started` / `harness_step` / `todo_updated` / `agent_completed` / `run_completed`.

## Front-end files
- `static/index.html` — the three-column shell.
- `static/icons.js` — inline SVG icon set (`ico(name)`), no CDN so it works offline / in-container.
- `static/app.js` — chat + markdown renderer, traces panel, Voice Live client, animated orchestration flow.
- `static/styles.css` — layout grid, animations (flow pulse, harness rail, voice rings).

## Deploy to Azure Container Apps
```powershell
cd webapp\inventory-dashboard
docker build -t zava-console .
```
Push to your registry and deploy on port `8501` with the env vars above and a managed identity that has
**Cognitive Services OpenAI User** on the Foundry account (for the agent + Voice Live) and read access to the
Zava API. Serve over HTTPS so the browser mic works.
