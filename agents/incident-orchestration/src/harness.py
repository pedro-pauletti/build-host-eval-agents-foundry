"""Common **MAF Agent Harness** for the Zava incident-response demo.

This module is the "glue" that lets three agents built with *different frameworks*
(LangGraph, GitHub Copilot SDK, Foundry prompt agent) be driven **uniformly** by the
Microsoft Agent Framework and orchestrated as one pipeline.

It provides:

* :class:`EventBus` — a tiny async pub/sub used to stream **fine-grained** harness
  events (agent started, a Copilot tool/harness step, an agent completed, the final
  result) to any consumer: the notebook, ``test_orchestration.py`` and the web app's
  real-time flow diagram all subscribe to the same stream.
* :class:`SharedTodoStore` + :func:`harness_todos` — the MAF **todo provider** capability,
  backed by a store that is shared by *all three* stages so they work through **one**
  remediation plan (the default ``TodoSessionStore`` would give each agent its own list).
* :func:`setup_observability` — turns on MAF's **OpenTelemetry** instrumentation, so the
  three heterogeneous frameworks produce one uniform trace in Application Insights.
* Small serialisable **result types** (:class:`TriageResult`, :class:`CodeFixResult`,
  :class:`ComplianceResult`) that each stage emits.
* Helpers to pass structured data **between** stages through the shared MAF conversation
  (:func:`fenced_json` / :func:`extract_last_json`) and to build an Azure OpenAI client
  with Microsoft Entra auth (:func:`build_azure_openai_client`).

The three per-framework adapters (``triage_langgraph.py``, ``code_fix_copilot.py``,
``compliance_foundry.py``) subclass MAF's :class:`agent_framework.BaseChatClient`, so
each framework is presented to MAF as an ordinary chat client — that uniform surface is
the *common Agent Harness*.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

# Stage / node identifiers shared by the harness, the orchestrator and the web app.
TRIAGE = "triage"
CODE_FIX = "code_fix"
COMPLIANCE = "compliance"
ORCHESTRATOR = "orchestrator"

ORCHESTRATION_SERVICE_NAME = os.getenv("ORCHESTRATION_AGENT_NAME", "IncidentResponseOrchestrator")

# The MAF ``TodoProvider`` injects the current plan as a user message starting with this
# marker; ``last_user_text`` skips it so the stages still see the incident text.
TODO_CONTEXT_MARKER = "### Current todo list"


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class HarnessEvent:
    """A single event on the shared stream."""

    type: str          # e.g. "agent_started", "harness_step", "agent_completed", "final", "error"
    agent: str         # one of TRIAGE / CODE_FIX / COMPLIANCE / ORCHESTRATOR
    ts: float
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "agent": self.agent, "ts": self.ts, **self.data}


class EventBus:
    """Minimal async pub/sub. Producers call :meth:`emit`; consumers :meth:`subscribe`.

    All events are also retained in :attr:`events` so a late/one-shot consumer (e.g. a
    notebook cell) can read the full trace after the run completes.
    """

    def __init__(self) -> None:
        self.events: list[HarnessEvent] = []
        self._queues: list[asyncio.Queue[HarnessEvent | None]] = []

    def subscribe(self) -> "asyncio.Queue[HarnessEvent | None]":
        queue: asyncio.Queue[HarnessEvent | None] = asyncio.Queue()
        self._queues.append(queue)
        return queue

    async def emit(self, type: str, agent: str, **data: Any) -> HarnessEvent:
        event = HarnessEvent(type=type, agent=agent, ts=time.time(), data=data)
        self.events.append(event)
        for queue in self._queues:
            queue.put_nowait(event)
        return event

    async def close(self) -> None:
        """Signal end-of-stream to all subscribers."""
        for queue in self._queues:
            queue.put_nowait(None)


# ---------------------------------------------------------------------------
# Result types (each stage emits one; all are JSON-serialisable)
# ---------------------------------------------------------------------------


@dataclass
class TriageResult:
    severity: str = "unknown"          # low | medium | high | critical
    category: str = "unknown"          # e.g. bug | outage | data-quality | security
    component: str = "unknown"         # e.g. reorder.py
    route: str = CODE_FIX              # which stage to hand off to
    summary: str = ""
    incident_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodeFixResult:
    test_passed: bool = False
    iterations: int = 0
    files_changed: list[str] = field(default_factory=list)
    diff: str = ""
    summary: str = ""
    test_output: str = ""
    sandbox_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComplianceResult:
    decision: str = "needs-changes"    # approved | needs-changes
    checks: list[dict[str, str]] = field(default_factory=list)  # [{id, status}]
    rationale: str = ""
    required_changes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Conversation helpers — structured hand-off through the shared MAF conversation
# ---------------------------------------------------------------------------

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"(\{(?:[^{}]|\{[^{}]*\})*\})", re.DOTALL)


def fenced_json(payload: dict[str, Any]) -> str:
    """Serialise a stage result as a fenced JSON block for the transcript."""
    return "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"


def extract_json(text: str) -> dict[str, Any] | None:
    """Return the first JSON object found in ``text`` (fenced or bare), or ``None``."""
    if not text:
        return None
    for pattern in (_JSON_FENCE, _BARE_JSON):
        for match in pattern.finditer(text):
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def messages_text(messages: Sequence[Any]) -> list[str]:
    """Return the text of each message, in order (skips empty/system-only entries)."""
    out: list[str] = []
    for message in messages:
        text = getattr(message, "text", None)
        if text:
            out.append(text)
    return out


def last_user_text(messages: Sequence[Any]) -> str:
    """Return the most recent user-authored message text (falls back to the last text).

    The MAF ``TodoProvider`` injects the current plan as a *user* message, so it is skipped
    here — the stages want the incident text, not the checklist.
    """
    texts: list[str] = []
    for message in messages:
        role = getattr(message, "role", None)
        role_value = getattr(role, "value", role)
        text = getattr(message, "text", "") or ""
        if not text or text.lstrip().startswith(TODO_CONTEXT_MARKER):
            continue
        texts.append(text)
        if str(role_value).lower() == "user":
            last_user = text
    try:
        return last_user  # type: ignore[name-defined]
    except NameError:
        return texts[-1] if texts else ""


def extract_last_json(messages: Sequence[Any], must_have: str | None = None) -> dict[str, Any] | None:
    """Scan messages newest-first and return the last JSON object.

    If ``must_have`` is given, only return an object that contains that key — this lets a
    downstream stage pick up the *specific* structured hand-off it needs.
    """
    for message in reversed(list(messages)):
        obj = extract_json(getattr(message, "text", "") or "")
        if obj is not None and (must_have is None or must_have in obj):
            return obj
    return None


# ---------------------------------------------------------------------------
# Azure OpenAI (Microsoft Entra auth) — used by the LangGraph triage node
# ---------------------------------------------------------------------------

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


def _account_endpoint() -> str:
    endpoint = os.getenv("AZURE_AI_ACCOUNT_ENDPOINT")
    if endpoint:
        return endpoint.rstrip("/")
    # Derive the account endpoint from the project endpoint if needed.
    project = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    return project.split("/api/projects", 1)[0].rstrip("/")


_CREDENTIAL: Any = None
_AOAI_CLIENT: Any = None


def shared_credential() -> Any:
    """One process-wide credential, so token acquisition is cached instead of re-run per call.

    A fresh ``DefaultAzureCredential`` shells out to ``az account get-access-token`` on every
    request; under load that subprocess can exceed the 10 s default and surface as
    ``AzureCliCredential: Failed to invoke the Azure CLI``. Reusing one instance keeps the token
    in memory, and the longer ``process_timeout`` covers a slow CLI start.
    """
    global _CREDENTIAL
    if _CREDENTIAL is None:
        from azure.identity import DefaultAzureCredential

        _CREDENTIAL = DefaultAzureCredential(
            exclude_interactive_browser_credential=True, process_timeout=30
        )
    return _CREDENTIAL


def build_azure_openai_client() -> Any:
    """Return an ``AzureOpenAI`` client authenticated with Microsoft Entra (keyless)."""
    global _AOAI_CLIENT
    if _AOAI_CLIENT is None:
        from azure.identity import get_bearer_token_provider
        from openai import AzureOpenAI

        _AOAI_CLIENT = AzureOpenAI(
            azure_endpoint=_account_endpoint(),
            azure_ad_token_provider=get_bearer_token_provider(shared_credential(), COGNITIVE_SCOPE),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        )
    return _AOAI_CLIENT


def triage_model() -> str:
    """Deployment used by the LangGraph triage node.

    Defaults to the **Model Router** deployment: triage is a short classification call, so the
    router picks a small/cheap model for it and escalates only when the incident text is complex.
    Verified working with JSON mode.
    """
    return (
        os.getenv("TRIAGE_MODEL")
        or os.getenv("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router")
    )


def load_env() -> None:
    """Load the repo ``.env`` (searching upward) without overriding real env vars."""
    from dotenv import load_dotenv

    here = os.path.abspath(__file__)
    for _ in range(6):
        here = os.path.dirname(here)
        candidate = os.path.join(here, ".env")
        if os.path.exists(candidate):
            load_dotenv(candidate, override=False)
            return
    load_dotenv(override=False)


# ---------------------------------------------------------------------------
# Base MAF adapter — the uniform surface that IS the "common Agent Harness"
# ---------------------------------------------------------------------------


class HarnessChatClient:
    """Mixin that turns a single text result into a correct MAF ``ChatResponse``.

    Concrete adapters (``LangGraphTriageClient``, ``CopilotCodeFixClient``,
    ``FoundryComplianceClient``) inherit from ``BaseChatClient`` **and** this mixin, and
    only implement :meth:`_produce`. This keeps the per-framework glue tiny and uniform.
    """

    agent_id: str = ORCHESTRATOR
    _bus: EventBus | None = None

    def bind(self, bus: EventBus | None) -> None:
        self._bus = bus

    async def _emit(self, type: str, **data: Any) -> None:
        if self._bus is not None:
            await self._bus.emit(type, self.agent_id, **data)

    async def _produce(self, messages: Sequence[Any], options: Any) -> str:  # pragma: no cover
        raise NotImplementedError

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):  # noqa: ANN001
        from agent_framework import ChatResponse, Message

        text = await self._produce(messages, options)
        if stream:
            return self._build_response_stream(self._as_updates(text))  # type: ignore[attr-defined]
        return ChatResponse(
            messages=[Message(role="assistant", contents=[text])],
            response_id=f"{self.agent_id}-{int(time.time() * 1000)}",
        )

    async def _as_updates(self, text: str):
        from agent_framework import ChatResponseUpdate

        yield ChatResponseUpdate(role="assistant", contents=[{"type": "text", "text": text}])


# ---------------------------------------------------------------------------
# Harness capability #1 — todo provider (one shared remediation plan)
# ---------------------------------------------------------------------------

TODO_INSTRUCTIONS = (
    "You are one stage of Zava's incident-response harness. A single shared todo list is the "
    "remediation plan for this incident: Triage writes the plan, Code Fix works through it, and "
    "Compliance verifies it. Never restart the plan — add to it or complete items on it."
)


class SharedTodoStore:
    """A :class:`agent_framework.TodoStore` shared by **every** stage of one run.

    MAF's default ``TodoSessionStore`` keeps todos in ``AgentSession.state``, which means each
    agent would get its *own* list. The harness wants the opposite: Triage plans, Code Fix
    executes and Compliance verifies **the same** checklist, so this store ignores the session
    and keeps one list per run — a store swap is the documented extension point for exactly this.

    Every mutation is republished on the :class:`EventBus` as a ``todo_updated`` event, so the
    notebook and the web app can render the plan filling in live.
    """

    def __init__(self, bus: "EventBus | None" = None) -> None:
        self.items: list[Any] = []
        self.next_id = 1
        self._bus = bus

    async def load_state(self, session: Any, *, source_id: str) -> tuple[list[Any], int]:
        return list(self.items), self.next_id

    async def load_items(self, session: Any, *, source_id: str) -> list[Any]:
        return list(self.items)

    async def save_state(self, session: Any, items: list[Any], *, next_id: int, source_id: str) -> None:
        self.items, self.next_id = list(items), next_id
        if self._bus is not None:
            await self._bus.emit("todo_updated", ORCHESTRATOR, todos=self.snapshot())

    def snapshot(self) -> list[dict[str, Any]]:
        """JSON-serialisable view of the plan (used by the event stream and the web app)."""
        return [
            {
                "id": getattr(item, "id", None),
                "title": getattr(item, "title", ""),
                "description": getattr(item, "description", None),
                "done": bool(getattr(item, "is_complete", False)),
            }
            for item in self.items
        ]


def build_todo_provider(store: Any) -> Any:
    """Return the real MAF ``TodoProvider`` bound to the harness-wide store."""
    from agent_framework import TodoProvider

    return TodoProvider(instructions=TODO_INSTRUCTIONS, store=store)


class HarnessTodos:
    """Thin wrapper letting an adapter drive the todo tools MAF put in ``options``.

    ``TodoProvider`` exposes ``todos_add`` / ``todos_complete`` / ... as ordinary MAF tools. A
    normal agent lets the *model* call them; our adapters wrap frameworks that return structured
    results instead, so the **harness** calls them on the stage's behalf. Either way it is the
    same provider, the same store and the same plan — which is the point of a harness capability.
    """

    def __init__(self, options: Any) -> None:
        tools = (options or {}).get("tools") or [] if isinstance(options, dict) else []
        self._tools = {getattr(tool, "name", ""): tool for tool in tools}

    @property
    def available(self) -> bool:
        return "todos_add" in self._tools

    async def _call(self, name: str, **arguments: Any) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            return None
        try:
            return await tool.invoke(arguments=arguments)
        except Exception:  # noqa: BLE001 - the plan is observability, never the critical path
            return None

    async def add(self, *titles: str) -> None:
        """Append plan items (no-op when the provider is not attached)."""
        items = [{"title": title} for title in titles if title]
        if items:
            await self._call("todos_add", todos=items)

    async def complete(self, *completions: tuple[int, str]) -> None:
        """Tick items off by id, each with the reason it is considered done."""
        items = [{"id": todo_id, "reason": reason} for todo_id, reason in completions]
        if items:
            await self._call("todos_complete", items=items)

    async def all(self) -> list[dict[str, Any]]:
        raw = await self._call("todos_get_all")
        text = _tool_text(raw)
        try:
            return json.loads(text) if text else []
        except (json.JSONDecodeError, ValueError):
            return []

    async def find(self, *keywords: str) -> int | None:
        """Return the id of the first *open* item whose title matches any keyword."""
        for item in await self.all():
            if item.get("is_complete"):
                continue
            title = str(item.get("title", "")).lower()
            if any(keyword.lower() in title for keyword in keywords):
                return int(item["id"])
        return None


def _tool_text(result: Any) -> str:
    """Tool results come back as MAF ``Content`` objects; pull the text out."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "".join(_tool_text(part) for part in result)
    for attr in ("text", "value", "result"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    return ""


# ---------------------------------------------------------------------------
# Harness capability #2 — OpenTelemetry
# ---------------------------------------------------------------------------

_otel_ready: bool | None = None


def setup_observability() -> bool:
    """Enable MAF's OpenTelemetry instrumentation, exporting to Application Insights.

    This is the capability that pays for itself in a *multi-framework* demo: because every
    stage reaches MAF through a ``BaseChatClient`` adapter, MAF instruments all three
    identically. LangGraph, the Copilot SDK and a Foundry prompt agent end up in **one**
    distributed trace with the same ``gen_ai.*`` attributes — something you would otherwise
    have to build three times, once per SDK.

    Safe to call repeatedly: OTel providers may only be configured once per process.
    """
    global _otel_ready
    if _otel_ready is not None:
        return _otel_ready

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        _otel_ready = False
        return False
    try:
        from agent_framework.observability import configure_otel_providers
        from azure.monitor.opentelemetry.exporter import (
            AzureMonitorLogExporter,
            AzureMonitorMetricExporter,
            AzureMonitorTraceExporter,
        )

        os.environ.setdefault("OTEL_SERVICE_NAME", ORCHESTRATION_SERVICE_NAME)
        configure_otel_providers(
            exporters=[
                AzureMonitorTraceExporter(connection_string=connection_string),
                AzureMonitorLogExporter(connection_string=connection_string),
                AzureMonitorMetricExporter(connection_string=connection_string),
            ],
            # Attaching prompts/completions to spans is opt-in: safe default, even though this
            # demo only ever handles synthetic Zava data.
            enable_sensitive_data=_truthy(os.getenv("OTEL_SENSITIVE_DATA")),
        )
        _otel_ready = True
    except Exception:  # noqa: BLE001 - telemetry must never break the pipeline
        _otel_ready = False
    return _otel_ready
