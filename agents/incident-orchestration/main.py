"""Foundry hosting entrypoint for the Zava incident-response orchestration.

Wraps the MAF sequential workflow (Triage -> Code Fix -> Compliance) as a single agent and
serves it with the Foundry Responses host server — the same pattern as the DeliverySupport
hosted agent. Deployed to Foundry Agent Service (with an Azure Container Apps fallback).

Run locally:
    cd agents/incident-orchestration
    ../../.venv/Scripts/python.exe main.py
"""
import os
import sys

# The Foundry hosted runtime may import the modules under ``src/`` either as a package
# (``src.orchestration``) or as top-level modules (``orchestration``). Put both the project
# root and ``src/`` on ``sys.path`` so either resolution works.
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.harness import load_env
from src.orchestration import build_incident_agent

from agent_framework_foundry_hosting import ResponsesHostServer

load_env()

agent = build_incident_agent()
app = ResponsesHostServer(agent=agent)

if __name__ == "__main__":
    app.run()
