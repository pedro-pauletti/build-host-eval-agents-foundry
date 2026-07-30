"""Compliance Agent — a **Foundry prompt agent**.

The agent itself (instructions + the Zava engineering policy) lives in Foundry and is
created by ``create_compliance_agent.py``. This module exposes it to the Microsoft Agent
Framework through :class:`FoundryComplianceClient`, a ``BaseChatClient`` adapter that
invokes the prompt agent via the Responses API ``agent_reference`` and parses its JSON
decision. If the Foundry agent is unavailable it falls back to a direct policy-grounded
model call so the pipeline still completes.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from agent_framework import Agent, BaseChatClient

if __package__:  # imported as `src.compliance_foundry`
    from .harness import (
        COMPLIANCE,
        EventBus,
        ComplianceResult,
        HarnessChatClient,
        HarnessTodos,
        build_todo_provider,
        extract_json,
        extract_last_json,
        fenced_json,
        last_user_text,
        shared_credential,
    )
else:  # run directly as `python src/compliance_foundry.py`
    from harness import (  # type: ignore[no-redef]
        COMPLIANCE,
        EventBus,
        ComplianceResult,
        HarnessChatClient,
        HarnessTodos,
        build_todo_provider,
        extract_json,
        extract_last_json,
        fenced_json,
        last_user_text,
        shared_credential,
    )

REPO = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else Path(__file__).resolve().parent
AGENT_NAME = os.getenv("COMPLIANCE_AGENT_NAME", "ComplianceReviewer")
COMPLIANCE_MODEL = os.getenv("COMPLIANCE_MODEL", os.getenv("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))

_project_client: Any = None


def _client() -> Any:
    global _project_client
    if _project_client is None:
        from azure.ai.projects import AIProjectClient

        _project_client = AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=shared_credential(),
        )
    return _project_client


def _build_review_input(code_fix: dict[str, Any], incident: str) -> str:
    return (
        f"INCIDENT:\n{incident}\n\n"
        f"PROPOSED FIX SUMMARY:\n{code_fix.get('summary', '')}\n\n"
        f"TESTS PASSED: {code_fix.get('test_passed')}\n"
        f"TEST OUTPUT:\n{code_fix.get('test_output', '')}\n\n"
        f"FILES CHANGED: {', '.join(code_fix.get('files_changed', []) or []) or 'none'}\n\n"
        f"UNIFIED DIFF:\n{code_fix.get('diff', '')}\n"
    )


def _fallback_instructions() -> str:
    policy = ""
    for parent in [REPO, *Path(__file__).resolve().parents]:
        candidate = parent / "data" / "company" / "zava-engineering-policy.md"
        if candidate.exists():
            policy = candidate.read_text(encoding="utf-8")
            break
    return (
        "You are ComplianceReviewer. Apply this policy and return STRICT JSON "
        '{"decision","checks":[{"id","status"}],"rationale","required_changes":[]}. '
        "Approve only if all applicable rules pass and tests pass.\n\n" + policy
    )


def _normalize_decision(raw: Any) -> str:
    """Map the model's free-form verdict onto the canonical ``approved`` / ``needs-changes``.

    The prompt agent answers with any of ``approve`` / ``approved`` / ``pass`` /
    ``reject`` / ``needs_changes`` / ``needs-changes``; anything that is not clearly an
    approval is treated as *needs-changes* (fail closed).
    """
    value = str(raw or "").strip().lower().replace("_", "-")
    return "approved" if value in {"approve", "approved", "pass", "passed", "ok"} else "needs-changes"


class FoundryComplianceClient(HarnessChatClient, BaseChatClient):
    """MAF adapter that calls the Foundry ComplianceReviewer prompt agent."""

    agent_id = COMPLIANCE

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    def _call_foundry(self, review_input: str) -> str:
        oai = _client().get_openai_client()
        resp = oai.responses.create(
            model=COMPLIANCE_MODEL,
            input=review_input,
            extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
        )
        return resp.output_text

    def _call_fallback(self, review_input: str) -> str:
        from harness import build_azure_openai_client  # local import to avoid cycle at import time

        client = build_azure_openai_client()
        completion = client.chat.completions.create(
            model=COMPLIANCE_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _fallback_instructions()},
                {"role": "user", "content": review_input},
            ],
        )
        return completion.choices[0].message.content or "{}"

    async def _produce(self, messages: Any, options: Any) -> str:
        payload = extract_last_json(messages, must_have="code_fix") or {}
        code_fix = payload.get("code_fix", payload)
        incident = last_user_text(messages)

        await self._emit(
            "agent_started",
            note="Reviewing the fix against Zava engineering policy (Foundry prompt agent)",
        )
        review_input = _build_review_input(code_fix, incident)

        used_fallback = False
        try:
            text = await asyncio.to_thread(self._call_foundry, review_input)
        except Exception as exc:  # pragma: no cover
            used_fallback = True
            await self._emit("harness_step", step="fallback", detail=f"Foundry agent unavailable: {exc}")
            text = await asyncio.to_thread(self._call_fallback, review_input)

        parsed = extract_json(text) or {}
        result = ComplianceResult(
            decision=_normalize_decision(parsed.get("decision")),
            checks=parsed.get("checks", []) or [],
            rationale=str(parsed.get("rationale", text[:500])),
            required_changes=parsed.get("required_changes", []) or [],
        )
        await self._emit(
            "harness_step",
            step="policy-review",
            detail=f"{len(result.checks)} checks evaluated"
            + (" (fallback path)" if used_fallback else ""),
        )

        # Close the loop on the shared plan: approve the review item, or append what is missing.
        todos = HarnessTodos(options)
        if todos.available:
            if result.decision == "approved":
                item = await todos.find("review", "policy")
                if item:
                    await todos.complete((item, f"{len(result.checks)} policy checks passed"))
            elif result.required_changes:
                await todos.add(*result.required_changes)
                await self._emit(
                    "harness_step",
                    step="plan",
                    detail=f"{len(result.required_changes)} required change(s) added to the plan",
                )

        await self._emit("agent_completed", result=result.to_dict())

        badge = "✅ APPROVED" if result.decision == "approved" else "⚠️ NEEDS CHANGES"
        lines = [f"**Compliance review — {badge}.**", "", result.rationale]
        if result.required_changes:
            lines.append("")
            lines.append("**Required changes:**")
            lines.extend(f"- {item}" for item in result.required_changes)
        human = "\n".join(lines)
        return fenced_json({"compliance": result.to_dict()}) + "\n\n" + human


def create_compliance_agent(bus: EventBus | None = None, todo_store: Any = None) -> Agent:
    """Return the Compliance stage as a MAF agent."""
    return Agent(
        client=FoundryComplianceClient(bus=bus),
        name="Compliance",
        description="Reviews the fix against Zava engineering policy (Foundry prompt agent).",
        instructions="You are the Zava incident Compliance agent.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


if __name__ == "__main__":  # manual smoke test
    from harness import load_env  # type: ignore

    load_env()

    async def _main() -> None:
        bus = EventBus()
        agent = create_compliance_agent(bus)
        seed = (
            "```json\n{\"code_fix\": {\"test_passed\": true, \"summary\": \"added guard + ceil\", "
            "\"files_changed\": [\"reorder.py\"], \"diff\": \"+ if on_hand>reorder_point: return 0\", "
            "\"test_output\": \"4 passed\"}}\n```\nReview please."
        )
        resp = await agent.run(seed)
        print(resp.text)

    asyncio.run(_main())
