"""End-to-end local run of the Zava incident-response orchestration.

Runs the full MAF pipeline once against the seeded incident and asserts the sandbox tests
end up green and Compliance approves. Run (repo root, venv):

    cd agents/incident-orchestration
    ../../.venv/Scripts/python.exe test_orchestration.py
"""
from __future__ import annotations

import asyncio
import sys

from src.harness import EventBus, load_env
from src.orchestration import incident_text_from_seed, run_incident


async def main() -> int:
    load_env()
    bus = EventBus()
    incident = incident_text_from_seed()
    print("INCIDENT:\n" + incident + "\n" + "=" * 70)

    result = await run_incident(incident, bus)

    print("\n--- EVENT TIMELINE ---")
    for event in result.events:
        detail = event.get("detail") or event.get("note") or event.get("step") or ""
        print(f"  [{event['agent']:<12}] {event['type']:<16} {detail}")

    print("\n--- TRIAGE ---")
    print(result.triage)
    print("\n--- CODE FIX ---")
    if result.code_fix:
        print({k: v for k, v in result.code_fix.items() if k != "diff"})
    print("\n--- COMPLIANCE ---")
    print(result.compliance)

    ok = bool(result.code_fix and result.code_fix.get("test_passed")) and bool(
        result.compliance and result.compliance.get("decision") == "approved"
    )
    print("\nRESULT:", "PASS ✅" if ok else "CHECK ⚠️")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
