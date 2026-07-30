"""Builder for notebooks/02_delivery_support_agent.en.ipynb (English).
Run: .venv\\Scripts\\python.exe notebooks/_builders/build_delivery_en.py
Mirrors the live MAF DeliverySupport agent (agents/delivery-support-agent/).
"""
import os
import nbformat as nbf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "02_delivery_support_agent.en.ipynb")

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))
def code(t): cells.append(nbf.v4.new_code_cell(t.strip("\n")))

md(r"""
# 📦 Zava · Building the **DeliverySupport Agent** on Microsoft Foundry

> **Hosted agent** · **Microsoft Agent Framework (MAF)** · **Model Router** · `lookupOrder` tool · **Memory** · **Traces + Evaluations + Continuous Evaluations** · **Voice-live**
>
> 🇧🇷 A Portuguese version is available as `02_delivery_support_agent.pt-BR.ipynb`.

Zava customers — like **Jane**, **Priya**, and **Diego** — want to track their ZavaCore Field orders and
understand delays without waiting for a human. In this notebook you build the **DeliverySupport Agent**: a
**hosted agent** written with the **Microsoft Agent Framework** and deployed to **Foundry Agent Service**.

It:
1. Runs on the **Model Router** deployment (routes across GPT models for cost/quality).
2. Calls a **`lookupOrder`** tool against Zava's "3rd-party" order system (the Zava API).
3. Keeps **memory** at two levels: **session memory** inside a conversation, and **Foundry Memory** —
   durable, per-customer recall that survives across conversations.
4. Emits **traces** and is covered by **evaluations** + **continuous (production) evaluations**.
5. Supports a **voice-live** experience.
""")

md(r"""
## 🏗️ Architecture

```mermaid
flowchart LR
  C[Customer<br/>text + voice-live] --> DEL[DeliverySupport<br/>hosted agent · MAF]
  DEL --> MR[Model Router<br/>deployment]
  DEL -->|lookupOrder / track_shipment| API[Zava order API<br/>3rd-party system]
  DEL --> SES[(Session memory<br/>this conversation)]
  DEL <-->|ContextProvider| FM[(Foundry Memory<br/>zava_delivery_memory)]
  DEL --> AI[(App Insights<br/>traces + continuous evals)]
```

**Prompt agent vs. hosted agent.** The InventoryAgent (notebook 01) is a *prompt agent* — model +
instructions + tools, managed by the service. The DeliverySupport agent is a **hosted agent**: your own
**code** (a MAF `Agent` with Python function tools and custom memory) packaged and run by Foundry Agent
Service. You get full control of the orchestration while Foundry handles hosting, identity, and scaling.
""")

md(r"""
## ✅ Prerequisites

- Demo infrastructure provisioned (`scripts/provision.ps1`) — this created the **`model-router`** deployment
  and the Zava API is deployed (`scripts/deploy_backend.ps1`).
- The MAF packages are installed (in the repo `.venv`): `agent-framework`,
  `agent-framework-foundry-hosting`, `azure-identity`, `httpx`.
- `az login` done (the agent uses `DefaultAzureCredential` locally, managed identity when hosted).
- A repo-root `.env` with the endpoints.
""")

code(r"""
# %pip install -r ../agents/delivery-support-agent/requirements.txt
import os, sys
from dotenv import load_dotenv

load_dotenv(os.path.join("..", ".env"))

# Make the agent package importable (agents/delivery-support-agent/src/agent.py)
AGENT_DIR = os.path.abspath(os.path.join("..", "agents", "delivery-support-agent"))
sys.path.insert(0, AGENT_DIR)

print("Model router:", os.environ.get("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))
print("Zava API    :", os.environ["ZAVA_API_BASE_URL"])
print("Account     :", os.environ["AZURE_AI_ACCOUNT_ENDPOINT"])
""")

md(r"""
## 1️⃣ The `lookupOrder` tool — MAF tool syntax

In the Microsoft Agent Framework a **tool** is just a decorated Python function. The `@tool` decorator turns
the signature into the JSON schema the model sees: the parameter names, their `Annotated[..., Field(...)]`
descriptions and the docstring all become part of the contract. `approval_mode="never_require"` means the
framework may invoke it without a human approval round-trip.

We define the two real tools **here in the notebook** — this is verbatim the pattern used by
`agents/delivery-support-agent/src/agent.py`.
""")

code(r'''
import json
from typing import Annotated

import httpx
from agent_framework import tool          # <- the MAF tool decorator
from pydantic import Field

ZAVA_API = os.environ["ZAVA_API_BASE_URL"].rstrip("/")


async def _get_tracking(path: str) -> str:
    """Shared HTTP call against Zava's "3rd-party" order system."""
    async with httpx.AsyncClient(base_url=ZAVA_API, timeout=20.0) as client:
        response = await client.get(path)
    if response.status_code == 404:
        return json.dumps({"found": False, "message": "I couldn\'t find that Zava order or tracking number."})
    response.raise_for_status()
    return json.dumps({"found": True, "tracking_card": response.json()}, ensure_ascii=False)


@tool(approval_mode="never_require")
async def lookup_order(
    order_id: Annotated[str, Field(description="The numeric Zava order ID, for example 23518.")],
) -> str:
    """Look up a Zava order by numeric order ID and return its tracking card."""
    print(f"[tool] lookup_order(order_id={order_id})", flush=True)
    return await _get_tracking(f"/orders/{str(order_id).strip()}")


@tool(approval_mode="never_require")
async def track_shipment(
    order_id: Annotated[str, Field(description="Optional numeric Zava order ID.")] = "",
    tracking_number: Annotated[str, Field(description="Optional carrier tracking number, e.g. ZVX-7489201374829.")] = "",
) -> str:
    """Track a shipment by order ID or tracking number."""
    print(f"[tool] track_shipment(order_id={order_id}, tracking_number={tracking_number})", flush=True)
    if str(order_id).strip():
        return await _get_tracking(f"/orders/{str(order_id).strip()}")
    if str(tracking_number).strip():
        return await _get_tracking(f"/track/{str(tracking_number).strip()}")
    return json.dumps({"found": False, "message": "Please provide an order ID or a tracking number."})


# The decorator produced a first-class MAF tool object, not a plain function:
print(type(lookup_order).__name__)
print("name       :", lookup_order.name)
print("description:", lookup_order.description)
''')

md(r"""
## 2️⃣ The Model Router — the MAF chat client

Instead of pinning one model, the agent uses the **`model-router`** deployment. Model Router inspects each
request and routes it to an appropriate GPT model — cheaper models for simple lookups, stronger models for
nuanced delay explanations — optimizing **cost vs. quality** automatically. From the agent's perspective it's
just one deployment name.

In MAF the model is supplied as a **chat client**. `OpenAIChatCompletionClient` talks to the Foundry account
with **Microsoft Entra** auth — no API keys, because the account has local auth disabled. The credential is
passed as a *bearer-token provider*, so tokens are refreshed for you.
""")

code(r"""
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

chat_client = OpenAIChatCompletionClient(
    model=os.environ.get("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"),
    azure_endpoint=os.environ["AZURE_AI_ACCOUNT_ENDPOINT"].rstrip("/"),
    credential=token_provider,                # keyless: Entra token, refreshed automatically
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
)

print("chat client:", type(chat_client).__name__)
print("deployment :", os.environ.get("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))
""")

md(r"""
## 3️⃣ Build the agent (with **session memory**) and run it

Everything now comes together in one MAF object. `Agent(...)` takes the **chat client**, a **name**, the
**instructions** (system prompt) and the **tools** list — that is the whole agent definition. There is no
service-side registration: this agent *is* your code.

`agent.create_session()` returns the conversation state. Reusing it across turns is the agent's **short-term
memory** — watch how turn 2 (*"when will it arrive?"*) is answered without repeating the order number.
""")

code(r'''
from agent_framework import Agent          # <- the MAF chat-agent type

INSTRUCTIONS = """
You are DeliverySupport, Zava\'s concise and empathetic order-tracking assistant.
Zava is ZavaCore Field athletic apparel. Customers track orders by numeric order ID
or carrier tracking number.

Rules:
- Never invent order, delivery, delay, or exception data.
- For every new order ID, tracking number, or explicit tracking request, call the
  lookup_order or track_shipment tool before answering.
- Use conversation/session history for follow-ups such as "when will it arrive?" so
  you can answer about the previously discussed order without asking again.
- When KNOWN CUSTOMER CONTEXT is provided, treat it as already confirmed: greet the
  customer by name and honour their stated delivery preferences.
- Include the exact status label, ETA, last location and destination when available.
- Keep answers brief, warm, and useful.
""".strip()

agent = Agent(
    client=chat_client,                    # Model Router, Entra auth
    name="DeliverySupport",
    instructions=INSTRUCTIONS,
    tools=[lookup_order, track_shipment],  # the @tool functions defined above
)

session = agent.create_session()           # <- conversation memory lives here
print(agent.name, "| tools:", [t.name for t in (lookup_order, track_shipment)])
''')

code(r"""
from collections.abc import Awaitable

async def say(prompt: str):
    resp = agent.run(prompt, session=session)   # same session -> multi-turn context
    if isinstance(resp, Awaitable):
        resp = await resp
    text = getattr(resp, "text", resp)
    print("Customer:", prompt)
    print("DeliverySupport:", text, "\n")

await say("Hey, what's the status of order 23518?")   # -> lookup_order(23518): Delayed - Weather, ETA Feb 17
await say("When will it arrive?")                     # -> uses MEMORY: answers Feb 17 without re-asking
await say("What about order 23590?")                  # -> lookup_order(23590): Delivered
""")

md(r"""
> The shipped agent packages exactly these three pieces — tools, chat client, `Agent(...)` — behind
> `create_delivery_support_agent()` in `agents/delivery-support-agent/src/agent.py`, so the hosted process and
> this notebook run the same definition:
>
> ```python
> from src.agent import create_delivery_support_agent, load_environment
> load_environment()
> agent = create_delivery_support_agent()
> ```
""")

md(r"""
### 💡 What just happened
- Turn 1 → the agent called **`lookup_order("23518")`**, which hit the live Zava API and returned the
  *Delayed - Weather* card (held at the Memphis DC, ETA Feb 17). The agent explained the delay plainly.
- Turn 2 → *"when will it arrive?"* had **no order number**, but the **session memory** let the agent answer
  **Feb 17, 2026** about order 23518 — no re-asking.
- Turn 3 → a new order id triggered a fresh tool call → *Delivered*.
""")

md(r"""
## 4️⃣ **Foundry Memory** — remembering the customer across conversations

Session memory dies with the conversation. Close the tab, come back tomorrow, and the agent has forgotten
your name and that you always want parcels left with the concierge. **Foundry Memory** fixes exactly that.

```mermaid
sequenceDiagram
  participant U as Customer
  participant A as DeliverySupport (MAF)
  participant P as FoundryMemoryProvider<br/>(ContextProvider)
  participant F as Foundry Memory Store
  U->>A: "How should my next delivery be handled?"
  A->>P: before_run(messages)
  P->>F: search_memories(scope, query)
  F-->>P: profile + summaries (semantic search)
  P-->>A: context.instructions += recalled facts
  A-->>U: "Hi Marcus — signature required, as always."
  A->>P: after_run(messages)
  P->>F: begin_update_memories(scope, messages)
  Note over F: extracts durable memories asynchronously<br/>(debounced by update_delay)
```

**Three concepts**

| Concept | Meaning |
|---|---|
| **Store** | The memory database. Has a *chat model* (does the extraction), an *embedding model* (semantic search), the memory *kinds* to collect, and a *TTL*. |
| **Scope** | One partition = **one customer**. Search and delete are always scoped, so customers never see each other's memories. |
| **Kinds** | `user_profile` (durable facts), `chat_summary` (rolling conversation summaries), `procedural` (learned behaviour rules). |

### 4️⃣.1 Create the store

`user_profile_details` is the highest-leverage knob in the whole feature: it is the instruction the
extraction model follows when deciding what is worth keeping — and what must never be stored.
""")

code(r'''
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
)
stores = project.beta.memory_stores          # <- the Foundry Memory API surface
STORE_NAME = os.environ.get("DELIVERY_MEMORY_STORE_NAME", "zava_delivery_memory")

USER_PROFILE_DETAILS = (
    "Remember the customer's preferred name, delivery preferences (safe place, concierge, "
    "signature requirements, preferred delivery window), preferred carrier, notification "
    "channel, accessibility needs, and the Zava orders or tracking numbers they follow. "
    "Do not store payment details, full street addresses, credentials, government IDs, "
    "precise geolocation, age or any other sensitive personal data."
)

try:
    store = stores.get(STORE_NAME)
    print("store already exists:", store.name)
except Exception:
    store = stores.create(
        name=STORE_NAME,
        description="Per-customer memory for Zava's DeliverySupport agent",
        definition=MemoryStoreDefaultDefinition(
            chat_model=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1"),        # extraction
            embedding_model=os.environ.get("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large"),  # recall
            options=MemoryStoreDefaultOptions(
                user_profile_enabled=True,
                chat_summary_enabled=True,
                default_ttl_seconds=30 * 24 * 3600,   # forget after 30 idle days (0 = never)
                user_profile_details=USER_PROFILE_DETAILS,
            ),
        ),
    )
    print("created store:", store.name)
''')

md(r"""
### 4️⃣.2 The four memory calls

The whole feature is four methods on `project.beta.memory_stores`. Everything else — the provider, the web
app panel, the notebook demo — is built on top of these:

| Call | What it does |
|---|---|
| `search_memories(store, scope, items)` | semantic recall for the current turn |
| `begin_update_memories(store, scope, items, update_delay)` | hand a finished turn back for extraction (async, debounced) |
| `list_memories(store, scope)` | everything currently held for one customer |
| `delete_scope(store, scope)` | forget one customer entirely |

The wrapper below is exactly what ships in `src/memory.py` — written out here so the SDK calls are visible.
""")

code(r'''
class ZavaMemory:
    """Thin, synchronous wrapper over the Foundry Memory Store API."""

    def __init__(self, stores, name: str, update_delay: int = 5) -> None:
        self.stores, self.name, self.update_delay = stores, name, update_delay

    def recall(self, query: str, *, scope: str, limit: int = 8) -> list[dict]:
        result = self.stores.search_memories(self.name, scope=scope, items=query)
        memories = getattr(result, "memories", None) or getattr(result, "results", None) or []
        return [self._flatten(item) for item in list(memories)[:limit]]

    def remember(self, items: list[dict], *, scope: str):
        # Debounced: Foundry waits for the conversation to go quiet before consolidating.
        return self.stores.begin_update_memories(
            self.name, scope=scope, items=items, update_delay=self.update_delay
        )

    def list_items(self, *, scope: str, limit: int = 50) -> list[dict]:
        return [self._flatten(i) for i in self.stores.list_memories(self.name, scope=scope, limit=limit)]

    def clear_scope(self, *, scope: str):
        return self.stores.delete_scope(self.name, scope=scope)

    @staticmethod
    def _flatten(item) -> dict:
        # search_memories returns MemorySearchItem (wrapping memory_item); list_memories returns MemoryItem.
        inner = getattr(item, "memory_item", None) or item
        kind = getattr(inner, "kind", None)
        return {
            "id": str(getattr(inner, "memory_id", None) or getattr(inner, "id", "")),
            "content": str(getattr(inner, "content", "") or ""),
            "kind": str(getattr(kind, "value", kind) or "memory"),
            "score": getattr(item, "score", None),
        }


KIND_LABEL = {"user_profile": "Profile", "chat_summary": "Past conversation", "procedural": "Learned habit"}

def format_recall(memories: list[dict]) -> str:
    """Render recalled memories as an instruction block for the model."""
    lines = [f"- ({KIND_LABEL.get(m['kind'], 'Memory')}) {m['content'].strip()}"
             for m in memories if m.get("content")]
    if not lines:
        return ""
    return ("KNOWN CUSTOMER CONTEXT (recalled from Zava's long-term memory — treat as already confirmed, "
            "use it proactively, never ask the customer to repeat it, and never invent additions):\n"
            + "\n".join(lines))


memory = ZavaMemory(stores, STORE_NAME, update_delay=int(os.environ.get("DELIVERY_MEMORY_UPDATE_DELAY", "5")))
print("memory wrapper ready for store:", memory.name)
''')

md(r"""
### 4️⃣.3 Wiring memory into a MAF agent — the `ContextProvider`

Foundry ships a built-in **`memory_search_preview`** tool, but it is for **prompt agents** (like the
InventoryAgent in notebook 01). DeliverySupport is a **hosted MAF agent**, so it calls the memory APIs
itself — the documented *"your backend owns the memory calls"* pattern — through a MAF
**`ContextProvider`**, the official extension point for injecting context into every run.

A `ContextProvider` has two hooks, both receiving the run `context` as a keyword argument:

- **`before_run`** — recall from Foundry and **append to `context.instructions`**.
- **`after_run`** — hand the finished turn back to Foundry for extraction.
""")

code(r'''
import asyncio

from agent_framework import ContextProvider          # <- MAF extension point


def latest_user_text(messages) -> str:
    for message in reversed(list(messages or [])):
        role = str(getattr(getattr(message, "role", None), "value", getattr(message, "role", "")) or "").lower()
        text = getattr(message, "text", None) or ""
        if text and role in ("user", ""):
            return text
    return ""


class FoundryMemoryProvider(ContextProvider):
    """Gives the agent durable, per-customer memory backed by a Foundry memory store."""

    def __init__(self, memory: ZavaMemory, scope: str) -> None:
        super().__init__(source_id="foundry-memory")
        self.memory, self.scope = memory, scope

    async def before_run(self, *, agent, session, context, state) -> None:
        query = latest_user_text(context.input_messages)
        if not query:
            return
        memories = await asyncio.to_thread(self.memory.recall, query, scope=self.scope)
        block = format_recall(memories)                 # "KNOWN CUSTOMER CONTEXT: ..."
        if block:
            context.instructions.append(block)          # <- recall lands in INSTRUCTIONS
            print(f"[memory] recalled {len(memories)} item(s) for scope={self.scope}", flush=True)

    async def after_run(self, *, agent, session, context, state) -> None:
        user_text = latest_user_text(context.input_messages)
        answer = getattr(context.response, "text", "") or ""
        if not user_text or not answer:
            return
        await asyncio.to_thread(                        # fire-and-forget, debounced by Foundry
            self.memory.remember,
            [
                {"type": "message", "role": "user", "content": user_text},
                {"type": "message", "role": "assistant", "content": answer},
            ],
            scope=self.scope,
        )
        print(f"[memory] queued update for scope={self.scope}", flush=True)


print("provider ready:", FoundryMemoryProvider.__name__)
''')

md(r"""
Two details that matter:

- **Recall goes into `instructions`, not chat history.** Memories are *context about* the customer, not
  things anyone said. Faking them as messages confuses the model and pollutes the transcript.
- **Writes are asynchronous and debounced.** `begin_update_memories` returns immediately; Foundry waits
  `update_delay` seconds of silence, then runs the extraction model. So a memory stated *now* typically
  becomes searchable ~10–30 s later — never `assert` on it in the same turn.

Attaching it is one extra argument on the same `Agent(...)` constructor from section 3:

```python
Agent(client=chat_client, name="DeliverySupport", instructions=INSTRUCTIONS,
      tools=[lookup_order, track_shipment],
      context_providers=[FoundryMemoryProvider(memory, scope)])   # <- the only difference
```
""")

code(r"""
# Prove cross-session recall. Session 2 is a BRAND NEW agent with zero conversation history.
import time
from collections.abc import Awaitable

async def ask(a, prompt):
    r = a.run(prompt)
    if isinstance(r, Awaitable):
        r = await r
    return getattr(r, "text", r)

def remembering_agent(scope: str) -> Agent:
    return Agent(
        client=chat_client,
        name="DeliverySupport",
        instructions=INSTRUCTIONS,
        tools=[lookup_order, track_shipment],
        context_providers=[FoundryMemoryProvider(memory, scope)],
    )

SCOPE = "zava-notebook-demo"
memory.clear_scope(scope=SCOPE)          # clean slate for the demo

s1 = remembering_agent(SCOPE)
print(await ask(s1, "Hi, I'm Priya Raman. Always leave my Zava parcels with the building "
                    "concierge and text me instead of emailing. Can you check order 23518?"))

print("\nwaiting for Foundry to consolidate memories...")
items = []
for _ in range(24):
    time.sleep(5)
    items = memory.list_items(scope=SCOPE)
    if items:
        break
for i in items:
    print(f"  [{i['kind']}] {i['content'][:120]}")

# --- new day, new conversation, no history ---
s2 = remembering_agent(SCOPE)
print("\n", await ask(s2, "Hi again - how should my next delivery be handled?"))
# -> greets Priya by name and repeats concierge + text-only, with nothing in the transcript.
""")

md(r"""
### 💡 What just happened
- Session 1's transcript was handed to Foundry, which distilled it into `user_profile` facts
  (*name = Priya Raman*, *drop-off = concierge*, *channel = SMS*, *follows order 23518*) plus a
  `chat_summary`.
- Session 2 was a **new agent object with an empty session**. `before_run` searched the same **scope**,
  found those facts, and injected them as instructions — so the agent answered as if it had known Priya
  for months.
- Run `python agents/delivery-support-agent/test_memory.py` for the same check as a script, or inspect the
  scope directly with `memory.list_items(scope=SCOPE)` and reset it with `memory.clear_scope(scope=SCOPE)`.

> **Which agent should get memory?** DeliverySupport — it talks to *the same person* repeatedly about
> *their* shipments, so continuity is the product. InventoryAgent is operational and analytical: its
> "state" is the live warehouse, and remembering an ops manager's past questions adds little. Rule of
> thumb: **memory belongs where there is a durable end-user relationship.**
""")

md(r"""
## 5️⃣ Run the hosted server locally

`main.py` wraps the agent in the Foundry hosting adapter (`ResponsesHostServer`) so the *same code* runs
locally and on Foundry Agent Service:

```powershell
Set-Location agents/delivery-support-agent
..\..\.venv\Scripts\python.exe .\main.py         # serves /responses on :8088
# smoke test:
Invoke-WebRequest http://localhost:8088/responses -Method POST -ContentType application/json `
  -Body '{"input":"Track order 23518"}'
```
""")

md(r"""
## 6️⃣ Deploy to **Foundry Agent Service** (hosted)

Hosted agents deploy with **`azd`** using **direct code deployment** — Foundry zips your source and builds
the runtime image (no Docker needed). The `azure.yaml` service block uses `codeConfiguration`:

```yaml
services:
  delivery-support-agent:
    project: ./agents/delivery-support-agent
    host: azure.ai.agent
    config: { name: DeliverySupport }
    codeConfiguration:
      runtime: python_3_13
      entryPoint: main.py
      dependencyResolution: remote_build
    environmentVariables:
      AZURE_AI_ACCOUNT_ENDPOINT: ${AZURE_AI_ACCOUNT_ENDPOINT}
      MODEL_ROUTER_DEPLOYMENT_NAME: ${MODEL_ROUTER_DEPLOYMENT_NAME}
      ZAVA_API_BASE_URL: ${ZAVA_API_BASE_URL}
```

```powershell
# point azd at the existing Foundry project, then deploy just this agent
azd env set AZURE_AI_PROJECT_ENDPOINT "<project-endpoint>"
azd deploy delivery-support-agent --no-prompt
azd ai agent show --output json
azd ai agent invoke "What's the status of order 23518?"
```

> The hosted agent's managed identity needs **Cognitive Services OpenAI User** on the Foundry account to call
> `model-router`. See `agents/delivery-support-agent/README.md`.
""")

md(r"""
## 7️⃣ Traces — OpenTelemetry, end to end

MAF is **instrumented with OpenTelemetry** following the GenAI semantic conventions. One call to
`configure_otel_providers()` and every model call, tool call and agent run emits a span with `gen_ai.*`
attributes — no per-agent wiring.

The fastest way to *see* that is to export the spans into the notebook itself with a tiny custom
`SpanExporter`, run one turn, and print what MAF produced. We register the **Application Insights exporter
at the same time**, because `configure_otel_providers()` configures the process **once** — calling it again
later in the same kernel will not add exporters.
""")

code(r'''
from agent_framework.observability import configure_otel_providers
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

CAPTURED = []

class NotebookSpanExporter(SpanExporter):
    """Collect finished spans in memory so we can print them here."""

    def export(self, spans):
        CAPTURED.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None

exporters = [NotebookSpanExporter()]
APPINSIGHTS = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
if APPINSIGHTS:                                   # exactly what the hosted agent does in production
    os.environ.setdefault("OTEL_SERVICE_NAME", "zava-delivery-support")
    exporters.append(AzureMonitorTraceExporter(connection_string=APPINSIGHTS))

# enable_sensitive_data also attaches prompts/responses to the spans — demo tenants only.
configure_otel_providers(exporters=exporters, enable_sensitive_data=True)

from collections.abc import Awaitable

async def run_once(agent, prompt: str) -> str:
    response = agent.run(prompt)
    if isinstance(response, Awaitable):
        response = await response
    return getattr(response, "text", response)

print(f"OpenTelemetry configured with {len(exporters)} exporter(s) — MAF is now emitting GenAI spans")
''')

code(r'''
# Run one turn, then flush and inspect the spans MAF emitted.
traced = Agent(client=chat_client, name="DeliverySupport",
               instructions=INSTRUCTIONS, tools=[lookup_order, track_shipment])
print(await run_once(traced, "What's the status of order 23518?"), "\n")

trace.get_tracer_provider().force_flush()

for span in CAPTURED:
    attrs = dict(span.attributes or {})
    duration_ms = (span.end_time - span.start_time) / 1_000_000
    print(f"{span.name:<34s} {duration_ms:7.0f} ms")
    for key in sorted(k for k in attrs if k.startswith("gen_ai.")):
        value = str(attrs[key]).replace("\n", " ")
        print(f"    {key:<34s} {value[:90]}")
    print()
''')

md(r"""
Three span shapes are worth recognising, because they are what the Foundry portal and Application Insights
render:

- **`invoke_agent <name>`** — the whole agent run: `gen_ai.agent.name`, the system instructions, the tool
  definitions the model could choose from, and total token usage.
- **`chat <model>`** — one model call, with `gen_ai.request.model`, `gen_ai.input.messages` /
  `gen_ai.output.messages` (only with `enable_sensitive_data`) and per-call token usage.
- **`execute_tool <name>`** — one tool invocation, with `gen_ai.tool.name`, `gen_ai.tool.call.arguments`
  and `gen_ai.tool.call.result`. This is what proves the agent *actually looked the order up*.

### 7️⃣.1 Reading the same traces back from Application Insights

Those spans were also shipped to **Application Insights** by the exporter registered above — that is all the
hosted agent does in production (`APPLICATIONINSIGHTS_CONNECTION_STRING` is already provisioned by
`scripts/provision.ps1`).

Traces are only useful if you can query them. MAF's spans land in the **`dependencies`** table with the
GenAI attributes in `customDimensions`, so *"which tools did this agent call today, and how long did they
take?"* is a KQL query, not a screenshot.
""")

code(r'''
# pip install azure-monitor-query
from datetime import timedelta
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

# provision.ps1 writes the App Insights name; the resource id is derivable from it.
RESOURCE_ID = os.environ.get("APPINSIGHTS_RESOURCE_ID") or (
    f"/subscriptions/{os.environ.get('AZURE_SUBSCRIPTION_ID', '')}"
    f"/resourceGroups/{os.environ.get('AZURE_RESOURCE_GROUP', '')}"
    f"/providers/Microsoft.Insights/components/{os.environ.get('APPLICATIONINSIGHTS_NAME', '')}"
)

QUERY = """
dependencies
| where timestamp > ago(1h)
| extend op    = tostring(customDimensions["gen_ai.operation.name"]),
         agent = tostring(customDimensions["gen_ai.agent.name"]),
         tool  = tostring(customDimensions["gen_ai.tool.name"]),
         model = tostring(customDimensions["gen_ai.request.model"]),
         tokens = toint(customDimensions["gen_ai.usage.output_tokens"])
| where isnotempty(op)
| project timestamp, op, agent, tool, model, tokens, ms = round(duration)
| order by timestamp desc
| take 15
"""

logs = LogsQueryClient(DefaultAzureCredential(exclude_interactive_browser_credential=True))
result = logs.query_resource(RESOURCE_ID, QUERY, timespan=timedelta(hours=1))
if result.status == LogsQueryStatus.SUCCESS and result.tables and result.tables[0].rows:
    table = result.tables[0]
    print(" | ".join(f"{c:<22s}" for c in table.columns))
    for row in table.rows:
        print(" | ".join(f"{str(v)[:22]:<22s}" for v in row))
else:
    print("No rows yet — App Insights ingestion lags 1-3 minutes. Re-run this cell shortly,")
    print("or open the Foundry portal -> Tracing / Application Insights -> Transaction search.")
''')


md(r"""
## 8️⃣ Evaluations

Foundry scores the agent **as a service**, so results land in the project (portal → *Evaluations*, and the
web app's *Evaluations* tab) rather than in a local notebook variable.

### Choosing the right evaluators for *this* agent

DeliverySupport is a tool-using, customer-facing agent, so the set is built around its real failure modes —
not a generic quality checklist:

| Evaluator | Flavour | The failure it catches |
|---|---|---|
| `builtin.intent_resolution` | built-in | misreading what the customer asked |
| `builtin.task_adherence` | built-in | ignoring its own rules (answer before looking up) |
| `builtin.tool_call_success` | built-in | `lookup_order` / `track_shipment` erroring out silently |
| `zava_tracking_facts` | **custom, code** | the real status / ETA / location missing from the answer |
| `zava_no_fabrication` | **custom, code** | the worst one: inventing a status, ETA or tracking number |
| `zava_delivery_rubric` | **rubric** | overall delivery-support quality, weighted and explained |

The last two exist because no generic evaluator knows Zava's data. The dataset carries the facts an answer
**must** contain (`must_include`) and, for the two rows where the agent has nothing to look up — an unknown
order and a question with no order id — the phrases it **must not** contain (`forbidden`).
""")

code(r'''
# The evaluation dataset: 9 real order-tracking questions with ground truth.
import json
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
)
oai = project.get_openai_client()
JUDGE = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")

EVAL_DATASET = os.path.join("..", "agents", "delivery-support-agent", "evals", "delivery_eval.jsonl")
rows = [json.loads(line) for line in open(EVAL_DATASET, encoding="utf-8") if line.strip()]
print(json.dumps(rows[0], indent=2)[:420])
print(f"\n{len(rows)} rows "
      f"({sum(1 for r in rows if r.get('forbidden'))} of them anti-hallucination rows)")

# Dataset versions are immutable, so bump until one is free (re-running this cell stays painless).
def upload_dataset(name, file_path):
    last = None
    for version in range(1, 50):
        try:
            return project.datasets.upload_file(name=name, version=str(version), file_path=file_path)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"could not upload {name}: {last}")

dataset = upload_dataset("zava-delivery-eval", EVAL_DATASET)
print("dataset id:", dataset.id)
''')

md(r"""
### 8️⃣.1 The two custom **code-based** evaluators

A code-based evaluator is a `grade(sample, item) -> float` function that Foundry runs in a sandbox (no
network, 2 minutes per call). Deterministic, cheap, and it never hallucinates about hallucinations.
""")

code(r'''
from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

TRACKING_FACTS_CODE = """
def grade(sample: dict, item: dict) -> float:
    # Fraction of the required tracking facts present in the answer.
    # Alternatives are separated by "|", so a date may be "Feb 17", "February 17" or "2026-02-17".
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

NO_FABRICATION_CODE = """
def grade(sample: dict, item: dict) -> float:
    # 1.0 when the answer contains none of the forbidden phrases, 0.0 otherwise.
    # Used for rows where the agent has nothing to look up: inventing a status, an ETA or a
    # tracking number there is the worst failure mode of an order-tracking agent.
    try:
        response = (item.get("sample", {}).get("output_text") or item.get("response") or "").lower()
        forbidden = item.get("forbidden") or []
        if isinstance(forbidden, str):
            forbidden = [forbidden]
        if not forbidden:
            return 1.0
        leaked = [f for f in forbidden if str(f).strip().lower() in response]
        return 0.0 if leaked else 1.0
    except Exception:
        return 0.0
"""

def register_code_evaluator(name, display_name, description, code_text, properties):
    return project.beta.evaluators.create_version(
        name=name,
        evaluator_version={
            "name": name,
            "categories": [EvaluatorCategory.QUALITY],
            "display_name": display_name,
            "description": description,
            "definition": {
                "type": EvaluatorDefinitionType.CODE,
                "code_text": code_text,
                "init_parameters": {
                    "type": "object",
                    "properties": {"deployment_name": {"type": "string"},
                                   "pass_threshold": {"type": "number"}},
                    "required": ["deployment_name", "pass_threshold"],
                },
                "metrics": {"result": {"type": "continuous", "desirable_direction": "increase",
                                       "min_value": 0.0, "max_value": 1.0}},
                "data_schema": {"type": "object", "required": ["item"],
                                "properties": {"item": {"type": "object", "properties": properties}}},
            },
        },
    )

facts = register_code_evaluator(
    "zava_tracking_facts", "Zava Tracking Facts",
    "Fraction of the real status/ETA/location facts present in the answer.",
    TRACKING_FACTS_CODE,
    {"query": {"type": "string"}, "ground_truth": {"type": "string"}, "must_include": {"type": "array"}},
)
guard = register_code_evaluator(
    "zava_no_fabrication", "Zava No Fabrication",
    "Hard gate: the answer must not invent a status, ETA or tracking number.",
    NO_FABRICATION_CODE,
    {"query": {"type": "string"}, "forbidden": {"type": "array"}},
)
print("registered:", facts.name, "|", guard.name)
''')

md(r"""
### 8️⃣.2 The delivery **rubric**

Weighted dimensions, judged 1–5 each by an LLM and normalised to 0–1. `lookup_before_answer` and
`no_fabrication` carry the most weight because they are what makes an order-tracking agent trustworthy.
""")

code(r'''
DELIVERY_RUBRIC_DIMENSIONS = [
    {"id": "lookup_before_answer", "weight": 9, "description":
     "Calls lookup_order or track_shipment before stating any status, and asks the customer for an order "
     "or tracking number when none was given. Never answers from assumption."},
    {"id": "factual_tracking_detail", "weight": 7, "description":
     "Reports the exact status label, estimated delivery date, carrier and last known location returned "
     "by the tool, without altering or rounding them."},
    {"id": "delay_explanation", "weight": 6, "description":
     "Explains weather, customs, volume and address exceptions in plain language and says clearly whether "
     "the customer needs to do anything."},
    {"id": "no_fabrication", "weight": 8, "description":
     "Never invents an order, ETA, tracking number or delivery confirmation. For unknown orders it says so "
     "and asks the customer to check the number."},
    {"id": "conversational_continuity", "weight": 4, "description":
     "Uses the conversation and remembered customer preferences for follow-ups such as 'when will it "
     "arrive?' instead of asking for the order number again."},
    {"id": "tone", "weight": 3, "description":
     "Warm, brief and empathetic; acknowledges frustration without over-apologising."},
    {"id": "general_quality", "weight": 5, "always_applicable": True, "description":
     "Other important quality factors not covered by the listed criteria."},
]

rubric = project.beta.evaluators.create_version(
    name="zava_delivery_rubric",
    evaluator_version={
        "name": "zava_delivery_rubric",
        "categories": [EvaluatorCategory.AGENTS],
        "display_name": "Zava Delivery Quality",
        "description": "Weighted quality criteria for Zava order-tracking answers.",
        "definition": {
            "type": EvaluatorDefinitionType.RUBRIC,
            "dimensions": DELIVERY_RUBRIC_DIMENSIONS,
            "pass_threshold": 0.6,
        },
    },
)
print("rubric:", rubric.name, "v" + str(rubric.version))
''')

md(r"""
### 8️⃣.3 Run it against the deployed agent

`DeliverySupport` is registered in Foundry, so the run can use it as an **agent target**: Foundry sends each
question to the hosted agent, captures the response *with its tool calls* (`{{sample.output_items}}`) and
scores it.
""")

code(r'''
import time
from azure.ai.projects.models import TestingCriterionAzureAIEvaluator
from openai.types.eval_create_params import DataSourceConfigCustom

def criterion(name, evaluator, mapping, init):
    return TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name=name, evaluator_name=evaluator,
        initialization_parameters=init, data_mapping=mapping,
    )

testing_criteria = [
    criterion("intent_resolution", "builtin.intent_resolution",
              {"query": "{{item.query}}", "response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
    criterion("task_adherence", "builtin.task_adherence",
              {"query": "{{item.query}}", "response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
    criterion("tool_call_success", "builtin.tool_call_success",
              {"response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
    criterion("tracking_facts", "zava_tracking_facts", {},
              {"deployment_name": JUDGE, "pass_threshold": 0.99}),
    criterion("no_fabrication", "zava_no_fabrication", {},
              {"deployment_name": JUDGE, "pass_threshold": 1.0}),
    criterion("delivery_rubric", rubric.name,
              {"query": "{{item.query}}", "response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
]

evaluation = oai.evals.create(
    name="Zava DeliverySupport quality",
    data_source_config=DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"}, "ground_truth": {"type": "string"},
                "must_include": {"type": "array"}, "forbidden": {"type": "array"},
                "expected_tool": {"type": "string"},
            },
            "required": ["query"],
        },
        include_sample_schema=True,
    ),
    testing_criteria=testing_criteria,
)

eval_run = oai.evals.runs.create(
    eval_id=evaluation.id,
    name="delivery-agent-target",
    data_source={
        "type": "azure_ai_target_completions",
        "source": {"type": "file_id", "id": dataset.id},
        "input_messages": {"type": "template", "template": [
            {"type": "message", "role": "user", "content": {"type": "input_text", "text": "{{item.query}}"}},
        ]},
        "target": {"type": "azure_ai_agent", "name": "DeliverySupport"},
    },
)

while True:
    run = oai.evals.runs.retrieve(run_id=eval_run.id, eval_id=evaluation.id)
    if str(run.status) in ("completed", "failed", "canceled"):
        break
    time.sleep(10)

print(f"status={run.status}  rows: {run.result_counts.passed}/{run.result_counts.total} passed\n")
for c in run.per_testing_criteria_results:
    total = c.passed + c.failed
    print(f"  {c.testing_criteria:<20s} pass {c.passed:>2d}  fail {c.failed:>2d}   "
          f"{(c.passed / total if total else 0):.0%}")
print("\nFoundry portal:\n", run.report_url)
''')

md(r"""
### 💡 What just happened

- Foundry called the **deployed** DeliverySupport agent once per dataset row, captured the answer *and* the
  `lookup_order` / `track_shipment` calls, and scored all six criteria over that.
- The interesting rows are the last two: order **99999** does not exist and *"Where is my package?"* has no
  order id at all. `zava_no_fabrication` is a hard gate there — any invented status, ETA or `ZVX-…` number
  scores 0.
- Results are stored in the project: `run.report_url` opens the **Foundry portal**, and the same run appears
  in the web app's **Evaluations** tab.

Scripted equivalent (same evaluators, same dataset):

```powershell
.\.venv\Scripts\python.exe agents/delivery-support-agent/run_eval.py
```

> **Continuous evaluations:** once the agent is deployed and App Insights is linked, the portal can sample
> **production** traffic and run this same criteria set on a schedule, so regressions surface on a dashboard
> instead of in a support ticket.
""")

md(r"""
## 9️⃣ Voice-live

The **Azure AI Foundry Voice Live** API gives DeliverySupport a spoken interface: the customer asks
*"where's my order?"* out loud and hears the answer, while the same tools run server-side.

It is a **realtime WebSocket**, not a REST call. Three things define the integration:

| Piece | Value |
|---|---|
| Endpoint | `wss://<account>/voice-live/realtime?api-version=…&model=gpt-realtime-mini` |
| Auth | `Authorization: Bearer <Entra token>` for `https://cognitiveservices.azure.com/.default` |
| Configuration | one `session.update` event: instructions, audio formats, turn detection, **the same tools**, and the voice |

The cells below open a real session against your deployment. To keep it runnable in a notebook we drive the
turn with **text** instead of a microphone — everything else (tool calling, audio synthesis) is identical to
what the browser does in `webapp/inventory-dashboard/app/voice.py`.
""")

code(r'''
import json
import websockets
from azure.identity import DefaultAzureCredential

ACCOUNT = os.environ["AZURE_AI_ACCOUNT_ENDPOINT"].rstrip("/").replace("https://", "")
API_VERSION = os.environ.get("VOICE_LIVE_API_VERSION", "2026-06-01-preview")
REALTIME_MODEL = os.environ.get("REALTIME_DEPLOYMENT_NAME", "gpt-realtime-mini")

VOICE_URL = f"wss://{ACCOUNT}/voice-live/realtime?api-version={API_VERSION}&model={REALTIME_MODEL}"
TOKEN = DefaultAzureCredential(exclude_interactive_browser_credential=True).get_token(
    "https://cognitiveservices.azure.com/.default"
).token

# The realtime model needs the tool SCHEMAS (it calls them; your code executes them).
VOICE_TOOLS = [
    {"type": "function", "name": "lookup_order",
     "description": "Look up a Zava order by numeric order id; returns the full tracking card.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"]}},
    {"type": "function", "name": "track_shipment",
     "description": "Track a shipment by order id or carrier tracking number (ZVX-...).",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"},
                                                     "tracking_number": {"type": "string"}}}},
]

SESSION_UPDATE = {
    "type": "session.update",
    "session": {
        "instructions": (
            "You are Zava DeliverySupport on a live voice call with a customer tracking a ZavaCore Field "
            "order. Always call lookup_order or track_shipment before answering — never invent order, "
            "delay or ETA data. Be warm, concise and clear: this is spoken."
        ),
        "modalities": ["text", "audio"],
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "input_audio_transcription": {"model": "whisper-1"},
        "turn_detection": {"type": "server_vad", "threshold": 0.5,
                           "prefix_padding_ms": 300, "silence_duration_ms": 500},
        "tools": VOICE_TOOLS,
        "tool_choice": "auto",
        "voice": {"name": os.environ.get("VOICE_LIVE_VOICE", "en-US-AvaNeural"), "type": "azure-standard"},
    },
}

print(VOICE_URL)
''')

code(r'''
# A real Voice Live turn: connect, configure the session, ask, execute the tool call, hear the answer.
import httpx

async def voice_turn(question: str) -> None:
    audio_bytes = 0
    async with websockets.connect(VOICE_URL, additional_headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
        await ws.send(json.dumps(SESSION_UPDATE))
        # A microphone would stream input_audio_buffer.append frames here instead.
        await ws.send(json.dumps({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": question}]}}))
        await ws.send(json.dumps({"type": "response.create"}))

        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=45))
            etype = event["type"]

            if etype == "response.audio.delta":                 # base64 PCM16 the browser plays
                audio_bytes += len(event.get("delta", ""))
            elif etype == "session.updated":
                print("session configured:", event["session"]["model"],
                      "| voice:", event["session"]["voice"]["name"])
            elif etype == "response.function_call_arguments.done":
                args = json.loads(event.get("arguments") or "{}")
                print(f"tool call -> {event['name']}({args})")
                with httpx.Client(base_url=os.environ["ZAVA_API_BASE_URL"].rstrip("/"), timeout=20) as c:
                    result = c.get(f"/orders/{args.get('order_id')}").json()
                await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                    "type": "function_call_output", "call_id": event["call_id"],
                    "output": json.dumps(result)[:1500]}}))
                await ws.send(json.dumps({"type": "response.create"}))
            elif etype == "response.audio_transcript.done":
                print("spoken answer:", event["transcript"])
            elif etype == "error":
                print("error:", event); break
            elif etype == "response.done":
                if any(i.get("type") == "message" for i in event["response"].get("output", [])):
                    break

    print(f"\naudio received: {audio_bytes} base64 chars of PCM16 (the browser plays this)")

await voice_turn("Where is order 23518?")
''')

md(r"""
### 💡 What just happened

1. **`session.update`** configured the realtime model: instructions, `pcm16` in/out, **server-side VAD**
   (the model decides when the customer stopped talking), the two Zava tool schemas and the neural voice.
2. The model decided to call **`lookup_order("23518")`** and streamed the arguments as
   `response.function_call_arguments.delta` events.
3. **Your code executed the tool** against the live Zava API and returned it as a
   `function_call_output` item — the realtime model never touches your backend directly.
4. A second `response.create` produced the spoken answer: `response.audio.delta` frames (PCM16 audio) plus
   `response.audio_transcript.done` — grounded in the real order record.

In the browser (`webapp/inventory-dashboard`) the only difference is the audio path: the page streams
microphone frames as `input_audio_buffer.append` and plays the `response.audio.delta` frames back, while a
FastAPI WebSocket relay holds the Entra token so it never reaches the client.
""")

md(r"""
## 🔄 Recap

You built a **hosted** Foundry agent with the **Microsoft Agent Framework**:

| Capability | How |
|---|---|
| Cost/quality routing | **Model Router** deployment |
| Live order data | **`lookupOrder`** function tool → Zava API |
| Multi-turn context | **Session memory** (`agent.create_session()`) |
| Cross-session recall | **Foundry Memory** store + MAF **`ContextProvider`** |
| Hosting | `ResponsesHostServer` + `azd deploy` (direct code) |
| Observability | **Traces** + **Evaluations** + **Continuous Evaluations** (App Insights) |
| Spoken UX | **Voice-live** (gpt-realtime-mini) |

Together with notebook 01 (**InventoryAgent**), you now have Zava's two agents — a *prompt* agent and a
*hosted* agent — covering the full toolkit: Foundry IQ, MCP tools, Fabric IQ, Model Router, session +
long-term memory, evaluations, web + voice, and Teams.

Tear down with `scripts/teardown.ps1` when finished.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("Wrote", OUT, "with", len(cells), "cells")
