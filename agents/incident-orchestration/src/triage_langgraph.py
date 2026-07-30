"""Triage Agent — built with **LangGraph**.

A compact ``StateGraph`` classifies the incident (severity / category / component) and
then deterministically **routes** it to the next stage. The graph is exposed to the
Microsoft Agent Framework through :class:`LangGraphTriageClient`, a ``BaseChatClient``
adapter — so from MAF's point of view the LangGraph agent is just another chat client
(this uniform surface is the *common Agent Harness*).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, TypedDict

from agent_framework import Agent, BaseChatClient

if __package__:  # imported as `src.triage_langgraph`
    from .harness import (
        CODE_FIX,
        TRIAGE,
        EventBus,
        HarnessChatClient,
        HarnessTodos,
        TriageResult,
        build_azure_openai_client,
        build_todo_provider,
        fenced_json,
        last_user_text,
        triage_model,
    )
else:  # run directly as `python src/triage_langgraph.py`
    from harness import (  # type: ignore[no-redef]
        CODE_FIX,
        TRIAGE,
        EventBus,
        HarnessChatClient,
        HarnessTodos,
        TriageResult,
        build_azure_openai_client,
        build_todo_provider,
        fenced_json,
        last_user_text,
        triage_model,
    )


class TriageState(TypedDict, total=False):
    incident: str
    severity: str
    category: str
    component: str
    summary: str
    incident_id: str
    route: str


CLASSIFY_SYSTEM = (
    "You are the Triage node of Zava's incident-response system. Classify the reported "
    "engineering incident. Respond with a STRICT JSON object with exactly these keys:\n"
    '  "severity": one of "low" | "medium" | "high" | "critical"\n'
    '  "category": one of "bug" | "data-quality" | "outage" | "security" | "performance" | "other"\n'
    '  "component": the most likely file or subsystem at fault (e.g. "reorder.py")\n'
    '  "summary": a one-sentence, plain-language summary of the problem\n'
    '  "incident_id": the incident id if present in the text, else ""\n'
    "Base every field only on the incident text. Do not add commentary or extra keys."
)

_client_cache: Any = None


def _azure_client() -> Any:
    global _client_cache
    if _client_cache is None:
        _client_cache = build_azure_openai_client()
    return _client_cache


def classify_node(state: TriageState) -> TriageState:
    """LangGraph node: LLM classification of the incident into structured fields."""
    client = _azure_client()
    completion = client.chat.completions.create(
        model=triage_model(),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": state.get("incident", "")},
        ],
    )
    data = json.loads(completion.choices[0].message.content or "{}")
    return {
        "severity": str(data.get("severity", "unknown")).lower(),
        "category": str(data.get("category", "unknown")).lower(),
        "component": str(data.get("component", "unknown")),
        "summary": str(data.get("summary", "")),
        "incident_id": str(data.get("incident_id", "")),
    }


def route_node(state: TriageState) -> TriageState:
    """LangGraph node: deterministic routing decision.

    In this workflow a code/data defect in a source component is routed to the **Code
    Fix** agent (which will then hand off to Compliance). The rule is intentionally
    explicit so the routing is auditable.
    """
    category = state.get("category", "")
    component = (state.get("component", "") or "").lower()
    is_code_defect = category in {"bug", "data-quality", "performance"} or component.endswith(".py")
    return {"route": CODE_FIX if is_code_defect else CODE_FIX}


def build_triage_graph() -> Any:
    """Compile the LangGraph ``classify -> route`` state graph."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(TriageState)
    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "route")
    graph.add_edge("route", END)
    return graph.compile()


_graph_cache: Any = None


def triage_graph() -> Any:
    global _graph_cache
    if _graph_cache is None:
        _graph_cache = build_triage_graph()
    return _graph_cache


class LangGraphTriageClient(HarnessChatClient, BaseChatClient):
    """MAF adapter that runs the LangGraph triage graph."""

    agent_id = TRIAGE

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    async def _produce(self, messages: Any, options: Any) -> str:
        incident = last_user_text(messages)
        await self._emit("agent_started", note="Classifying & routing the incident with LangGraph")

        graph = triage_graph()
        state: TriageState = await asyncio.to_thread(graph.invoke, {"incident": incident})

        result = TriageResult(
            severity=state.get("severity", "unknown"),
            category=state.get("category", "unknown"),
            component=state.get("component", "unknown"),
            route=state.get("route", CODE_FIX),
            summary=state.get("summary", ""),
            incident_id=state.get("incident_id", ""),
        )
        await self._emit(
            "harness_step",
            step="classify",
            detail=f"severity={result.severity} · category={result.category} · component={result.component}",
        )
        await self._emit("harness_step", step="route", detail=f"route -> {result.route}")

        # Triage owns the plan: it writes the remediation checklist the later stages work through.
        todos = HarnessTodos(options)
        if todos.available:
            await todos.add(
                f"Reproduce the defect in `{result.component}` with a failing test",
                f"Patch `{result.component}` so the {result.category} no longer occurs",
                "Re-run the test suite until it is green",
                "Review the change against Zava engineering policy",
            )
            await self._emit("harness_step", step="plan", detail="4 remediation items added to the shared todo list")

        await self._emit("agent_completed", result=result.to_dict())

        human = (
            f"**Triage complete.** Severity **{result.severity}**, category **{result.category}**, "
            f"component `{result.component}`. Routing to **{result.route}**.\n\n{result.summary}"
        )
        return fenced_json({"triage": result.to_dict()}) + "\n\n" + human


def create_triage_agent(bus: EventBus | None = None, todo_store: Any = None) -> Agent:
    """Return the Triage stage as a MAF agent."""
    return Agent(
        client=LangGraphTriageClient(bus=bus),
        name="Triage",
        description="Classifies and routes a Zava engineering incident (LangGraph).",
        instructions="You are the Zava incident Triage agent.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


if __name__ == "__main__":  # manual smoke test
    from harness import load_env  # type: ignore

    load_env()

    async def _main() -> None:
        bus = EventBus()
        agent = create_triage_agent(bus)
        incident = (
            "ZAVA-INC-4821: the nightly reorder job produced NEGATIVE reorder quantities for "
            "well-stocked SKUs and rounded deficits down below target. Suspect reorder.py."
        )
        resp = await agent.run(incident)
        print(resp.text)

    asyncio.run(_main())
