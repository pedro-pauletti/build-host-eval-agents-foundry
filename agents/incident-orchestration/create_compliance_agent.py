#!/usr/bin/env python3
"""Create (or version) the Zava **ComplianceReviewer** — a Foundry *prompt agent*.

The agent's instructions embed the Zava Engineering & Change-Management Policy
(``data/company/zava-engineering-policy.md``). Given a proposed fix (summary + diff +
test result) it returns a STRICT JSON compliance decision.

Run (repo root, venv):
    .venv\\Scripts\\python.exe agents/incident-orchestration/create_compliance_agent.py
    .venv\\Scripts\\python.exe agents/incident-orchestration/create_compliance_agent.py --test
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env")

AGENT_NAME = os.getenv("COMPLIANCE_AGENT_NAME", "ComplianceReviewer")
PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
# The ComplianceReviewer carries no tools, so it can safely use the **Model Router** deployment:
# the router escalates to a stronger model for long/ambiguous diffs and uses a cheap one otherwise.
MODEL = os.getenv("COMPLIANCE_MODEL", os.getenv("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))
POLICY_PATH = REPO / "data" / "company" / "zava-engineering-policy.md"

POLICY = POLICY_PATH.read_text(encoding="utf-8")

INSTRUCTIONS = f"""You are **ComplianceReviewer**, Zava's automated engineering change reviewer.
During incident response you review a *proposed code fix* against Zava's engineering and
change-management policy and decide whether it may be shipped.

Apply THIS policy exactly:

--- BEGIN POLICY ---
{POLICY}
--- END POLICY ---

You will be given the incident, the proposed fix summary, the unified diff, and the test
result. Evaluate every applicable rule. Approve ONLY when all applicable rules pass AND the
tests pass. Never approve a change that leaves tests failing, removes a validation guard,
or masks a symptom.

Respond with a STRICT JSON object and nothing else:
{{
  "decision": "approved" | "needs-changes",
  "checks": [{{"id": "C1", "status": "pass" | "fail" | "n/a"}}, ...],
  "rationale": "short plain-language justification citing failing rule ids if any",
  "required_changes": ["concrete change needed for approval", ...]
}}
When approved, "required_changes" must be an empty list."""


def create_agent(client: AIProjectClient):
    agent = client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(model=MODEL, instructions=INSTRUCTIONS),
    )
    print(f"Created/updated agent '{agent.name}' version {getattr(agent, 'version', '?')}")
    return agent


def smoke_test(client: AIProjectClient):
    oai = client.get_openai_client()
    review = (
        "Incident: reorder.py produced negative reorder quantities.\n"
        "Fix summary: added a reorder-point guard, non-negative clamp, and ceiling rounding.\n"
        "Diff: (adds `if item.on_hand > item.reorder_point: return 0` and ceil division).\n"
        "Test result: 4 passed in 0.05s (all green)."
    )
    resp = oai.responses.create(
        model=MODEL,
        input=review,
        extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
    )
    print("\nCompliance decision:\n", resp.output_text)


def main():
    client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())
    if "--test-only" not in sys.argv:
        create_agent(client)
    if "--test" in sys.argv or "--test-only" in sys.argv:
        smoke_test(client)


if __name__ == "__main__":
    main()
