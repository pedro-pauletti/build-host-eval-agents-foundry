"""Zava incident-response multi-framework orchestration.

Three heterogeneous agents cooperate through a common Microsoft Agent Framework
(MAF) harness and are orchestrated as a deterministic pipeline:

    Triage (LangGraph) -> Code Fix (GitHub Copilot SDK) -> Compliance (Foundry prompt agent)

See ``harness.py`` (common MAF harness + event bus) and ``orchestration.py``
(the MAF sequential workflow) for the wiring, and ``main.py`` for Foundry hosting.
"""
