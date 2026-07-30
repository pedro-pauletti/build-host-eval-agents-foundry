#!/usr/bin/env python3
"""
Smoke-test the published **ZavaDataAgent** by asking it real questions and
printing the answers.

    .venv-fabric\\Scripts\\python.exe data/semantic-model/test_data_agent.py
    .venv-fabric\\Scripts\\python.exe data/semantic-model/test_data_agent.py "your own question"

Uses the assistants-style client the Fabric Data Agent exposes (`FabricOpenAI`),
pointed at the **production** stage (i.e. what `create_data_agent.py` published).
"""
from __future__ import annotations

import os
import sys
import time

WS_NAME = os.environ.get("FABRIC_WORKSPACE_NAME", "Zava-Demos")
AGENT = os.environ.get("DATA_AGENT_NAME", "ZavaDataAgent")
STAGE = os.environ.get("DATA_AGENT_STAGE", "production")

QUESTIONS = [
    "What is total revenue and how many units have we sold?",
    "Show revenue and units by product line.",
    "Which distribution centre has the most critical or low-stock SKUs?",
    "How many orders are currently delayed?",
]


def _auth_outside_fabric() -> None:
    try:
        from azure.identity import AzureCliCredential
        from fabric.analytics.environment.credentials import (
            SetFabricAnalyticsDefaultTokenCredentialsGlobally,
        )
        SetFabricAnalyticsDefaultTokenCredentialsGlobally(AzureCliCredential())
    except Exception as e:
        print(f"Auth: skipping explicit credential setup ({e}).")


def ask(client, question: str) -> str:
    assistant = client.beta.assistants.create(model="not-used")
    thread = client.beta.threads.create()
    client.beta.threads.messages.create(thread_id=thread.id, role="user", content=question)
    run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant.id)

    while run.status in ("queued", "in_progress"):
        time.sleep(2)
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

    if run.status != "completed":
        return f"[run {run.status}] {getattr(run, 'last_error', '')}"

    messages = client.beta.threads.messages.list(thread_id=thread.id)
    for m in messages.data:
        if m.role == "assistant":
            return "\n".join(c.text.value for c in m.content if c.type == "text")
    return "[no assistant message]"


def main() -> None:
    from fabric.dataagent.client import FabricOpenAI

    _auth_outside_fabric()
    client = FabricOpenAI(artifact_name=AGENT, workspace_name=WS_NAME, ai_skill_stage=STAGE)

    questions = sys.argv[1:] or QUESTIONS
    for q in questions:
        print(f"\n=== Q: {q}")
        try:
            print(ask(client, q))
        except Exception as e:
            print(f"[error] {e}")


if __name__ == "__main__":
    main()
