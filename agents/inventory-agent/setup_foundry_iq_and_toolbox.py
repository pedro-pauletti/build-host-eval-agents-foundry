#!/usr/bin/env python3
r"""
Provision the **Foundry IQ knowledge base** and the **Agent Toolbox** that InventoryAgent uses.

This is the reproducible source of truth for everything `create_agent.py` depends on
(other than the raw `zava-docs` search index, which `data/documents/index_documents.py` builds).

What it creates (all idempotent — safe to re-run):

  1. Azure AI Search **knowledge source** `zava-docs-ks`  -> wraps the `zava-docs` index.
  2. Azure AI Search **knowledge base**   `zava-kb`       -> Foundry IQ retrieval + answer synthesis
                                                             (grounded on the knowledge source,
                                                              reasoning with the `gpt-4.1` deployment).
  3. Foundry connection `zava-kb-mcp`      -> RemoteTool pointing at the knowledge base MCP endpoint,
                                              authenticated with the *project managed identity*.
  4. Foundry connection `zava-toolbox-mcp` -> RemoteTool pointing at the toolbox MCP endpoint.
  5. Foundry **toolbox** `zava-toolbox`    -> bundles the Zava MCP server (live inventory/orders)
                                              + the Foundry IQ knowledge base MCP into ONE tool
                                              surface the agent binds to.

Key concepts
------------
* **Foundry IQ** is implemented by Azure AI Search *knowledge bases*. They live on the **search
  service data plane** (`/knowledgeSources`, `/knowledgeBases`) — NOT on the Foundry project.
  An agent consumes one through a plain `MCPTool` pointed at
  `https://<search>.search.windows.net/knowledgeBases/<kb>/mcp`, calling `knowledge_base_retrieve`.
  This replaces the older `AzureAISearchTool` (raw index querying, no query planning / synthesis).
* A **toolbox** is a named, versioned bundle of tools exposed as a single MCP endpoint at
  `{project_endpoint}/toolboxes/{name}/mcp?api-version=v1`. Agents bind to it with a normal
  `MCPTool`. Tools are namespaced as `<server_label>___<tool_name>`.
* Both remote endpoints are reached with the **project managed identity** via a `RemoteTool`
  connection, so no bearer tokens ever live in the agent definition.

Run (repo root, venv):
    .venv\Scripts\python.exe agents/inventory-agent/setup_foundry_iq_and_toolbox.py
    .venv\Scripts\python.exe agents/inventory-agent/setup_foundry_iq_and_toolbox.py --test
"""
from __future__ import annotations

import json
import os
import sys

import httpx
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(REPO, ".env"))

SUBSCRIPTION = os.environ["AZURE_SUBSCRIPTION_ID"]
RESOURCE_GROUP = os.environ["AZURE_RESOURCE_GROUP"]
FOUNDRY_ACCOUNT = os.environ["FOUNDRY_ACCOUNT_NAME"]
PROJECT_NAME = os.environ.get("FOUNDRY_PROJECT_NAME", "zava-project")
PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"].rstrip("/")

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"].rstrip("/")
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX_NAME", "zava-docs")
MODEL = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
MCP_URL = os.environ["ZAVA_MCP_URL"]

KS_NAME = os.environ.get("FOUNDRY_IQ_KNOWLEDGE_SOURCE", "zava-docs-ks")
KB_NAME = os.environ.get("FOUNDRY_IQ_KNOWLEDGE_BASE", "zava-kb")
KB_CONN = os.environ.get("FOUNDRY_IQ_CONNECTION_NAME", "zava-kb-mcp")
TOOLBOX_NAME = os.environ.get("FOUNDRY_TOOLBOX_NAME", "zava-toolbox")
TOOLBOX_CONN = os.environ.get("FOUNDRY_TOOLBOX_CONNECTION_NAME", "zava-toolbox-mcp")

# Data-plane api-versions. Knowledge bases require a 2026+ preview surface.
SEARCH_API = "2026-05-01-preview"
ARM_API = "2025-06-01"
TOOLBOX_API = "v1"

KB_MCP_URL = f"{SEARCH_ENDPOINT}/knowledgeBases/{KB_NAME}/mcp?api-version={SEARCH_API}"
TOOLBOX_MCP_URL = f"{PROJECT_ENDPOINT}/toolboxes/{TOOLBOX_NAME}/mcp?api-version={TOOLBOX_API}"

# The knowledge base plans queries and synthesises a cited answer. These instructions steer it.
RETRIEVAL_INSTRUCTIONS = (
    "The corpus is Zava's internal operations handbook: returns & exchanges, shipping SLAs, "
    "inventory reorder policy, sizing/fabric care, supplier onboarding and the ZavaCore Field "
    "product-line overview. Decompose questions that mix policy with product lines or facilities "
    "into separate sub-queries."
)
ANSWER_INSTRUCTIONS = (
    "Answer only from the retrieved Zava documents. Be specific about day counts, thresholds and "
    "SLA windows. Always cite the source document title. If the documents do not cover the "
    "question, say so plainly instead of guessing."
)

_cred = DefaultAzureCredential()


def _token(scope: str) -> str:
    return _cred.get_token(scope).token


def _search_headers() -> dict:
    return {
        "Authorization": "Bearer " + _token("https://search.azure.com/.default"),
        "Content-Type": "application/json",
    }


def _arm_headers() -> dict:
    return {
        "Authorization": "Bearer " + _token("https://management.azure.com/.default"),
        "Content-Type": "application/json",
    }


def _project_headers() -> dict:
    return {
        "Authorization": "Bearer " + _token("https://ai.azure.com/.default"),
        "Content-Type": "application/json",
    }


def _check(resp: httpx.Response, what: str) -> dict:
    if resp.status_code >= 300:
        raise RuntimeError(f"{what} failed [{resp.status_code}]: {resp.text[:900]}")
    return resp.json() if resp.content else {}


# --------------------------------------------------------------------------------------
# 1 + 2. Foundry IQ: knowledge source and knowledge base (Azure AI Search data plane)
# --------------------------------------------------------------------------------------
def create_knowledge_source() -> None:
    body = {
        "name": KS_NAME,
        "kind": "searchIndex",
        "description": "Zava policy and how-to documents.",
        # NOTE: `searchIndexName` is the only required parameter. `sourceDataSelect` is NOT valid.
        "searchIndexParameters": {"searchIndexName": SEARCH_INDEX},
    }
    r = httpx.put(
        f"{SEARCH_ENDPOINT}/knowledgeSources/{KS_NAME}?api-version={SEARCH_API}",
        headers=_search_headers(), json=body, timeout=90,
    )
    _check(r, "create knowledge source")
    print(f"[1/5] knowledge source '{KS_NAME}' -> index '{SEARCH_INDEX}'")


def create_knowledge_base() -> None:
    openai_uri = f"https://{FOUNDRY_ACCOUNT}.openai.azure.com"
    body = {
        "name": KB_NAME,
        "description": (
            "Zava's official operations handbook (Foundry IQ). AUTHORITATIVE SOURCE for all Zava "
            "POLICY, PROCEDURE and RULE questions: returns & exchanges rules and eligibility, "
            "shipping SLAs and delivery windows, the inventory reorder policy and its thresholds, "
            "safety-stock and replenishment rules, sizing charts and fabric-care instructions, "
            "supplier onboarding requirements, and the ZavaCore Field product-line overview. "
            "Does NOT contain live stock levels or sales figures."
        ),
        "knowledgeSources": [{"name": KS_NAME}],
        "models": [{
            "kind": "azureOpenAI",
            "azureOpenAIParameters": {
                "resourceUri": openai_uri,
                "deploymentId": MODEL,
                "modelName": MODEL,
            },
        }],
        "retrievalInstructions": RETRIEVAL_INSTRUCTIONS,
        "answerInstructions": ANSWER_INSTRUCTIONS,
        "outputMode": "answerSynthesis",
    }
    r = httpx.put(
        f"{SEARCH_ENDPOINT}/knowledgeBases/{KB_NAME}?api-version={SEARCH_API}",
        headers=_search_headers(), json=body, timeout=90,
    )
    _check(r, "create knowledge base")
    print(f"[2/5] knowledge base '{KB_NAME}' (outputMode=answerSynthesis, model={MODEL})")


# --------------------------------------------------------------------------------------
# 3 + 4. RemoteTool connections so the agent authenticates with the project managed identity
# --------------------------------------------------------------------------------------
def create_remote_tool_connection(name: str, target: str, audience: str) -> None:
    """
    `audience` MUST be a top-level property. Putting it inside `metadata` silently yields
    `audience: null` and the MCP call fails with 401.
    """
    url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.CognitiveServices/accounts/{FOUNDRY_ACCOUNT}/projects/{PROJECT_NAME}"
        f"/connections/{name}?api-version={ARM_API}"
    )
    body = {
        "properties": {
            "category": "RemoteTool",
            "authType": "ProjectManagedIdentity",
            "target": target,
            "audience": audience,
            "isSharedToAll": True,
            "metadata": {"ApiType": "Azure"},
        }
    }
    r = httpx.put(url, headers=_arm_headers(), json=body, timeout=120)
    _check(r, f"create connection {name}")
    print(f"      connection '{name}' -> {target.split('?')[0]}  (aud {audience})")


# --------------------------------------------------------------------------------------
# 5. Toolbox — bundles the Zava MCP server + the Foundry IQ knowledge base MCP
# --------------------------------------------------------------------------------------
def create_toolbox() -> dict:
    """
    Toolboxes are **versioned**: every POST to `/toolboxes/{name}/versions` appends a new version.
    The MCP endpoint serves the toolbox's `default_version`, so a new version must be promoted
    explicitly — otherwise agents keep seeing the old tool set.
    """
    body = {
        "name": TOOLBOX_NAME,
        "description": "Zava operations toolbox: live inventory/order tools + Foundry IQ knowledge base.",
        "tools": [
            {
                "type": "mcp",
                "server_label": "zava_tools",
                "server_url": MCP_URL,
                "server_description": "Live Zava inventory, alerts, KPIs, product lookups.",
                "require_approval": "never",
            },
            {
                "type": "mcp",
                "server_label": "zava_kb",
                "server_url": KB_MCP_URL,
                "server_description": (
                    "Foundry IQ knowledge base — the ONLY authoritative source for Zava policies, "
                    "procedures, thresholds, SLAs, sizing/care guidance and product-line overviews."
                ),
                "require_approval": "never",
                "allowed_tools": ["knowledge_base_retrieve"],
                # A connection NAME (not an ARM id) — the project MI authenticates the call.
                "project_connection_id": KB_CONN,
            },
        ],
    }
    base = f"{PROJECT_ENDPOINT}/toolboxes"
    exists = httpx.get(f"{base}/{TOOLBOX_NAME}?api-version={TOOLBOX_API}",
                       headers=_project_headers(), timeout=60).status_code == 200
    url = (f"{base}/{TOOLBOX_NAME}/versions?api-version={TOOLBOX_API}" if exists
           else f"{base}?api-version={TOOLBOX_API}")
    data = _check(httpx.post(url, headers=_project_headers(), json=body, timeout=120),
                  "create toolbox version")
    version = str(data.get("version", "1"))

    # Promote the freshly created version so the MCP endpoint actually serves it.
    _check(
        httpx.patch(f"{base}/{TOOLBOX_NAME}?api-version={TOOLBOX_API}",
                    headers=_project_headers(), json={"default_version": version}, timeout=60),
        "set default toolbox version",
    )
    print(f"[5/5] toolbox '{TOOLBOX_NAME}' version {version} (default) -> "
          f"{[t['server_label'] for t in body['tools']]}")
    return data


# --------------------------------------------------------------------------------------
def test() -> None:
    """Call both MCP endpoints directly with the *developer's* token (proves the plumbing)."""
    print("\n--- knowledge base MCP ---")
    r = httpx.post(
        KB_MCP_URL,
        headers={"Authorization": "Bearer " + _token("https://search.azure.com/.default"),
                 "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              # NOTE: the parameter is `queries` (an ARRAY), not `query`.
              "params": {"name": "knowledge_base_retrieve",
                         "arguments": {"queries": ["What is the Zava return window?"]}}},
        timeout=120,
    )
    print(r.status_code, r.text[:600].replace("\n", " "))

    print("\n--- toolbox MCP (tools/list) ---")
    r = httpx.post(
        TOOLBOX_MCP_URL,
        headers={"Authorization": "Bearer " + _token("https://ai.azure.com/.default"),
                 "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        timeout=120,
    )
    if r.status_code == 200:
        names = [t["name"] for t in json.loads(r.text)["result"]["tools"]]
        print(200, names)
    else:
        print(r.status_code, r.text[:600])


def main() -> None:
    if "--test-only" in sys.argv:
        test()
        return
    create_knowledge_source()
    create_knowledge_base()
    print("[3/5] connections")
    create_remote_tool_connection(KB_CONN, KB_MCP_URL, "https://search.azure.com/")
    print("[4/5] connections")
    create_remote_tool_connection(TOOLBOX_CONN, TOOLBOX_MCP_URL, "https://ai.azure.com/")
    create_toolbox()
    print(
        "\nRBAC reminder: the **project** managed identity (not the account MI) needs\n"
        "  - 'Foundry User' / 'Azure AI Developer' on the Foundry account  (read its own toolbox)\n"
        "  - 'Search Index Data Reader' on the search service              (read the knowledge base)\n"
        "See agents/inventory-agent/README.md."
    )
    if "--test" in sys.argv:
        test()


if __name__ == "__main__":
    main()
