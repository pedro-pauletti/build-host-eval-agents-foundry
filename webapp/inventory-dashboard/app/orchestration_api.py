"""Web-app integration for the incident-response orchestration (Demo #2).

Runs the MAF sequential workflow (Triage -> Code Fix -> Compliance) **in-process** and
streams its harness events so the browser can animate the flow diagram and per-agent
dashboard in real time. The heavy imports (MAF, LangGraph, GitHub Copilot SDK) are done
lazily so the main inventory/delivery dashboard stays fast to start.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator

_REPO = Path(__file__).resolve().parents[3]
_ORCH_SRC = _REPO / "agents" / "incident-orchestration" / "src"
_SEED = _REPO / "agents" / "incident-orchestration" / "sandbox_seed"


def _ensure_path() -> None:
    path = str(_ORCH_SRC)
    if path not in sys.path:
        sys.path.insert(0, path)


def _router() -> str:
    return os.getenv("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router")


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in {"0", "false", "no", "off"}


def _otel_enabled() -> bool:
    """OpenTelemetry only really exports when App Insights is wired up."""
    return bool(os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"))


def harness_info() -> dict[str, Any]:
    """The **real** configuration of the shared MAF Agent Harness.

    Everything here is read from the same environment/constants the orchestration itself
    uses (``agents/incident-orchestration/src/``), so the visualisation shows what is
    actually running rather than a hard-coded picture.

    ``capabilities`` maps this demo onto the capability list from the Microsoft Agent
    Framework *Agent Harnesses* documentation. States are deliberately honest:

    ``on``  — active in this run · ``off`` — available but not configured ·
    ``na`` — belongs to the ``create_harness_agent`` factory, not to this hand-built harness.
    """
    hosted = bool(os.getenv("ORCHESTRATION_AGENT_ENDPOINT"))
    return {
        "name": os.getenv("ORCHESTRATION_AGENT_NAME", "IncidentResponseOrchestrator"),
        "pattern": "SequentialBuilder",
        "surface": "agent_framework.BaseChatClient",
        "hosting": "Foundry hosted agent" if hosted else "in-process (local)",
        "parameters": [
            {
                "label": "Orchestration",
                "value": "SequentialBuilder",
                "note": "Deterministic Triage → Code Fix → Compliance, typed hand-offs through one shared conversation.",
            },
            {
                "label": "Uniform surface",
                "value": "BaseChatClient ×3",
                "note": "Each framework is wrapped as an ordinary MAF chat client — that adapter layer *is* the common harness.",
            },
            {
                "label": "Hand-off format",
                "value": "fenced JSON",
                "note": "Every stage appends a ```json block; the next stage picks up the object it needs with extract_last_json().",
            },
            {
                "label": "Event bus",
                "value": "async pub/sub",
                "note": "One stream feeds the notebook trace, the tests and this live diagram.",
            },
            {
                "label": "Tool approval",
                "value": "auto-approve (sandbox)",
                "note": "on_pre_tool_use returns permissionDecision=allow — safe because the harness only ever touches a temp copy.",
            },
            {
                "label": "Loop bound",
                "value": f"{os.getenv('CODE_FIX_TIMEOUT', '300')}s",
                "note": "CODE_FIX_TIMEOUT caps the Copilot plan → execute → assess loop; pytest is the completion condition.",
            },
            {
                "label": "Isolation",
                "value": "temp sandbox",
                "note": "sandbox_seed/ is copied to a fresh tempdir per run — the real repository is never writable.",
            },
            {
                "label": "Wrapped as",
                "value": "WorkflowAgent",
                "note": "The whole workflow is exposed as a single agent and served by ResponsesHostServer for Foundry hosting.",
            },
            {
                "label": "Todo provider",
                "value": "SharedTodoStore",
                "note": "One MAF TodoProvider backed by a store shared by all three stages, so they work through a single remediation plan instead of three private lists.",
            },
            {
                "label": "Observability",
                "value": "OpenTelemetry → App Insights" if _otel_enabled() else "OpenTelemetry (no connection string)",
                "note": "configure_otel_providers() instruments MAF itself, so all three frameworks emit one GenAI trace. Sensitive data: "
                + ("on" if _truthy(os.getenv("OTEL_SENSITIVE_DATA")) else "off")
                + " (OTEL_SENSITIVE_DATA).",
            },
        ],
        "capabilities": [
            {"id": "function-invocation", "label": "Function invocation", "state": "on",
             "note": "Copilot SDK runs the tool-calling loop; MAF invokes each adapter."},
            {"id": "tool-approval", "label": "Tool approval", "state": "on",
             "note": "on_pre_tool_use hook auto-approves every sandbox tool."},
            {"id": "looping", "label": "Looping", "state": "on",
             "note": "Code Fix re-plans until pytest passes or the timeout hits."},
            {"id": "shell", "label": "Shell environment", "state": "on",
             "note": "Shell + filesystem tools confined to the temp sandbox."},
            {"id": "todo", "label": "Todo provider", "state": "on",
             "note": "Triage writes the plan, Code Fix completes items from real signals, Compliance verifies — one SharedTodoStore for the whole run."},
            {"id": "otel", "label": "OpenTelemetry", "state": "on" if _otel_enabled() else "off",
             "note": "GenAI semantic conventions exported to Application Insights."
                     if _otel_enabled() else
                     "Ready — set APPLICATIONINSIGHTS_CONNECTION_STRING to export the traces."},
            {"id": "history", "label": "Per-call history persistence", "state": "off",
             "note": "MAF Agent(require_per_service_call_history_persistence=True) — not needed for a 3-stage run."},
            {"id": "compaction", "label": "Compaction", "state": "off",
             "note": "Activates once you pass max_context_window_tokens; this pipeline stays well under budget."},
            {"id": "mode", "label": "Agent mode provider", "state": "na",
             "note": "Plan/execute modes come from the harness factory; here the phases are explicit stages."},
            {"id": "websearch", "label": "Web search", "state": "na",
             "note": "Default harness tool — intentionally off so the run stays reproducible."},
        ],
        "events": [
            "run_started",
            "agent_started",
            "harness_step",
            "todo_updated",
            "agent_completed",
            "run_completed",
            "error",
        ],
    }


def scenario_info() -> dict[str, Any]:
    """Static description of the incident scenario for the dashboard's initial state."""
    incident = json.loads((_SEED / "incident.json").read_text(encoding="utf-8"))
    return {
        "incident": incident,
        "buggy_code": (_SEED / "reorder.py").read_text(encoding="utf-8"),
        "tests": (_SEED / "test_reorder.py").read_text(encoding="utf-8"),
        "harness": harness_info(),
        "agents": [
            {
                "id": "triage",
                "name": "Triage",
                "framework": "LangGraph",
                "role": "Classify severity/category/component and route the incident.",
                "adapter": "LangGraphTriageClient",
                "model": os.getenv("TRIAGE_MODEL") or _router(),
                "tools": [
                    {"name": "classify", "kind": "graph", "note": "LangGraph node — JSON-mode LLM call."},
                    {"name": "route", "kind": "graph", "note": "LangGraph node — deterministic, auditable routing rule."},
                ],
            },
            {
                "id": "code_fix",
                "name": "Code Fix",
                "framework": "GitHub Copilot SDK",
                "role": "Fix the bug in an isolated sandbox (plan → execute → assess → iterate).",
                "adapter": "CopilotCodeFixClient",
                "model": os.getenv("CODE_FIX_MODEL", "claude-sonnet-4.5"),
                "tools": [
                    {"name": "read", "kind": "file", "note": "Inspect reorder.py / test_reorder.py (plan phase)."},
                    {"name": "edit", "kind": "file", "note": "Write the fix — sandbox copy only (execute phase)."},
                    {"name": "shell", "kind": "shell", "note": "Runs `pytest -q` to verify (assess phase)."},
                ],
            },
            {
                "id": "compliance",
                "name": "Compliance",
                "framework": "Foundry prompt agent",
                "role": "Review the fix against Zava's engineering policy → approve / needs-changes.",
                "adapter": "FoundryComplianceClient",
                "model": os.getenv("COMPLIANCE_MODEL") or _router(),
                "tools": [
                    {
                        "name": os.getenv("COMPLIANCE_AGENT_NAME", "ComplianceReviewer"),
                        "kind": "agent",
                        "note": "Responses API agent_reference — instructions carry the Zava engineering policy.",
                    },
                    {"name": "policy fallback", "kind": "policy", "note": "Direct policy-grounded model call if the Foundry agent is unreachable."},
                ],
            },
        ],
    }


def default_incident_text() -> str:
    _ensure_path()
    from orchestration import incident_text_from_seed  # type: ignore

    return incident_text_from_seed()


async def stream_incident(incident_text_value: str) -> AsyncIterator[dict[str, Any]]:
    """Run the pipeline and yield each harness event as a plain dict, ending with the result."""
    _ensure_path()
    from harness import (  # type: ignore
        CODE_FIX,
        COMPLIANCE,
        ORCHESTRATOR,
        TRIAGE,
        EventBus,
        SharedTodoStore,
        setup_observability,
    )
    from orchestration import (  # type: ignore
        _last_result,
        _outputs_to_text,
        build_incident_workflow,
    )

    otel = setup_observability()
    bus = EventBus()
    queue = bus.subscribe()
    todo_store = SharedTodoStore(bus)
    workflow = build_incident_workflow(bus, todo_store)

    async def _run() -> None:
        try:
            await bus.emit("run_started", ORCHESTRATOR, incident=incident_text_value, otel=otel)
            result = await workflow.run(incident_text_value)
            final = _outputs_to_text(result.get_outputs())
            await bus.emit(
                "run_completed",
                ORCHESTRATOR,
                final_text=final,
                triage=_last_result(bus, TRIAGE),
                code_fix=_last_result(bus, CODE_FIX),
                compliance=_last_result(bus, COMPLIANCE),
                todos=todo_store.snapshot(),
            )
        except Exception as exc:  # noqa: BLE001
            await bus.emit("error", ORCHESTRATOR, note=str(exc))
        finally:
            await bus.close()

    task = asyncio.create_task(_run())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event.to_dict()
    finally:
        await task
