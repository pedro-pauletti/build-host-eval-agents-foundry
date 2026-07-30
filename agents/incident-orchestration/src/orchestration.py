"""MAF **orchestration** of the Zava incident-response pipeline.

Wires the three per-framework agents into a deterministic **sequential** workflow with
:class:`agent_framework_orchestrations.SequentialBuilder`:

    Triage (LangGraph) -> Code Fix (GitHub Copilot SDK) -> Compliance (Foundry prompt agent)

Because each agent is exposed to MAF through the common harness (a ``BaseChatClient``
adapter), the orchestrator treats them uniformly. The same workflow can be wrapped as a
single MAF agent (:func:`build_incident_agent`) and hosted on Foundry (see ``main.py``).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_framework import WorkflowAgent
from agent_framework_orchestrations import SequentialBuilder

if __package__:  # imported as `src.orchestration`
    from .harness import (
        CODE_FIX,
        COMPLIANCE,
        ORCHESTRATOR,
        TRIAGE,
        EventBus,
        SharedTodoStore,
        load_env,
        setup_observability,
    )
    from .triage_langgraph import create_triage_agent
    from .code_fix_copilot import create_code_fix_agent
    from .compliance_foundry import create_compliance_agent
else:  # run directly as `python src/orchestration.py`
    from harness import (  # type: ignore
        CODE_FIX,
        COMPLIANCE,
        ORCHESTRATOR,
        TRIAGE,
        EventBus,
        SharedTodoStore,
        load_env,
        setup_observability,
    )
    from triage_langgraph import create_triage_agent  # type: ignore
    from code_fix_copilot import create_code_fix_agent  # type: ignore
    from compliance_foundry import create_compliance_agent  # type: ignore

SEED = Path(__file__).resolve().parent.parent / "sandbox_seed"
ORCHESTRATION_AGENT_NAME = os.getenv("ORCHESTRATION_AGENT_NAME", "IncidentResponseOrchestrator")


def incident_text_from_seed() -> str:
    """Build the demo incident prompt from ``sandbox_seed/incident.json``."""
    data = json.loads((SEED / "incident.json").read_text(encoding="utf-8"))
    symptoms = "\n".join(f"- {s}" for s in data.get("symptoms", []))
    return (
        f"{data['incident_id']}: {data['title']}\n\n"
        f"{data['description']}\n\nSymptoms:\n{symptoms}"
    )


def build_incident_workflow(bus: EventBus | None = None, todo_store: Any = None) -> Any:
    """Build the sequential Triage -> Code Fix -> Compliance workflow.

    ``todo_store`` is the harness-wide plan: passing the *same* store to all three stages is what
    makes the todo provider a shared checklist instead of three private ones.
    """
    triage = create_triage_agent(bus, todo_store)
    code_fix = create_code_fix_agent(bus, todo_store)
    compliance = create_compliance_agent(bus, todo_store)
    return SequentialBuilder(participants=[triage, code_fix, compliance]).build()


def build_incident_agent(bus: EventBus | None = None, todo_store: Any = None) -> WorkflowAgent:
    """Wrap the workflow as a single MAF agent (used for Foundry hosting)."""
    setup_observability()
    workflow = build_incident_workflow(bus, todo_store if todo_store is not None else SharedTodoStore(bus))
    return WorkflowAgent(
        workflow=workflow,
        name=ORCHESTRATION_AGENT_NAME,
        description="Zava incident-response orchestration: Triage (LangGraph) -> "
        "Code Fix (GitHub Copilot SDK) -> Compliance (Foundry prompt agent).",
    )


@dataclass
class OrchestrationResult:
    triage: dict[str, Any] | None
    code_fix: dict[str, Any] | None
    compliance: dict[str, Any] | None
    final_text: str
    events: list[dict[str, Any]] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "triage": self.triage,
            "code_fix": self.code_fix,
            "compliance": self.compliance,
            "final_text": self.final_text,
            "events": self.events,
            "todos": self.todos,
        }


def _last_result(bus: EventBus, agent: str) -> dict[str, Any] | None:
    for event in reversed(bus.events):
        if event.agent == agent and event.type == "agent_completed":
            return event.data.get("result")
    return None


def _outputs_to_text(outputs: list[Any]) -> str:
    flat: list[Any] = []
    for item in outputs:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    texts = [getattr(m, "text", None) for m in flat if getattr(m, "text", None)]
    if texts:
        return texts[-1]
    return str(outputs[-1]) if outputs else ""


async def run_incident(incident_text: str | None = None, bus: EventBus | None = None) -> OrchestrationResult:
    """Run the full incident-response pipeline once and return a structured result.

    Fine-grained progress is emitted on ``bus`` as it happens (subscribe for a live feed);
    the per-agent structured results are also collected here for convenience.
    """
    load_env()
    otel = setup_observability()
    bus = bus or EventBus()
    incident_text = incident_text or incident_text_from_seed()
    todo_store = SharedTodoStore(bus)

    workflow = build_incident_workflow(bus, todo_store)
    await bus.emit("run_started", ORCHESTRATOR, incident=incident_text, otel=otel)
    result = await workflow.run(incident_text)
    final_text = _outputs_to_text(result.get_outputs())

    triage = _last_result(bus, TRIAGE)
    code_fix = _last_result(bus, CODE_FIX)
    compliance = _last_result(bus, COMPLIANCE)
    todos = todo_store.snapshot()
    await bus.emit(
        "run_completed",
        ORCHESTRATOR,
        decision=(compliance or {}).get("decision"),
        test_passed=(code_fix or {}).get("test_passed"),
        todos_done=sum(1 for item in todos if item["done"]),
        todos_total=len(todos),
    )
    await bus.close()

    return OrchestrationResult(
        triage=triage,
        code_fix=code_fix,
        compliance=compliance,
        final_text=final_text,
        events=[event.to_dict() for event in bus.events],
        todos=todos,
    )
