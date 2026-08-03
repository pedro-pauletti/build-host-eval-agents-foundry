#!/usr/bin/env python3
"""
Smoke-test InventoryAgentDatabricks against the same questions the Fabric agent answers.

Prints the tool traffic (which MCP tool ran, with what arguments) alongside the answer, so
you can see Genie doing natural-language-to-SQL rather than the model guessing.

Usage:
    .venv\\Scripts\\python.exe agents/inventory-agent-databricks/test_agent.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=False)

AGENT_NAME = os.getenv("DATABRICKS_AGENT_NAME", "InventoryAgentDatabricks")

QUESTIONS = [
    "What is total revenue by product line?",
    "How many units of ZCPTM-SS-S-B0 do we have across facilities?",
    "Which SKUs are critical at FC-CLT?",
    "Which month had the highest revenue for the Elite line?",
    "What's our return policy for worn apparel?",   # fora de escopo: deve recusar
]


def main() -> None:
    project = AIProjectClient(
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(exclude_interactive_browser_credential=True,
                                          process_timeout=30),
    )
    oai = project.get_openai_client()

    for question in QUESTIONS:
        print("\n" + "=" * 78)
        print(f"Q: {question}")
        try:
            resp = oai.responses.create(
                input=question,
                extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
            )
        except Exception as exc:
            print(f"   ERRO: {type(exc).__name__}: {str(exc)[:300]}")
            continue

        for item in resp.output:
            kind = getattr(item, "type", "")
            if kind == "mcp_list_tools":
                names = [t.get("name") if isinstance(t, dict) else getattr(t, "name", "?")
                         for t in (getattr(item, "tools", None) or [])]
                print(f"   [tools] {', '.join(names)}")
            elif kind == "mcp_call":
                args = getattr(item, "arguments", "")
                try:
                    args = json.dumps(json.loads(args))[:150]
                except Exception:
                    args = str(args)[:150]
                print(f"   [call ] {getattr(item, 'name', '?')}  {args}")
                if getattr(item, "error", None):
                    print(f"   [error] {item.error}")
        print(f"\n   {resp.output_text.strip()[:900]}")


if __name__ == "__main__":
    sys.exit(main())
