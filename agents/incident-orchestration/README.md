# Zava · Incident-Response **Multi-Framework Orchestration** (MAF + Foundry Hosted Agents)

This package is the second Zava demo: it shows how to **integrate agents built with different
frameworks**, wrap them behind a **common Microsoft Agent Framework (MAF) harness**, **orchestrate**
them as a deterministic pipeline, and **host** the whole orchestration on **Foundry Agent Service**.

## The scenario — a Zava engineering incident
Zava's **nightly reorder service** produced *negative* reorder quantities for well-stocked SKUs and
rounded genuine deficits **down** below target. Three agents cooperate to resolve the incident:

| Stage | Agent | Framework | What it does |
|---|---|---|---|
| 1 | **Triage** | **LangGraph** | Classifies the incident (severity / category / component) and routes it. |
| 2 | **Code Fix** | **GitHub Copilot SDK** | Runs a real *plan → execute (shell/filesystem) → assess → iterate* harness on an **isolated sandbox** until `pytest` passes. |
| 3 | **Compliance** | **Foundry prompt agent** | Reviews the proposed fix against Zava's engineering/change-management policy → **approve / needs-changes**. |

### Models

Both the model-driven stages run on the **`model-router`** deployment — neither carries tools, so the
router is free to pick a cheap model for the short triage classification and escalate to a stronger one
for a long, ambiguous diff review.

| Stage | Deployment | Why |
|---|---|---|
| Triage | `model-router` (`TRIAGE_MODEL`) | Short classification call in JSON mode — verified working. |
| Code Fix | `claude-sonnet-4.5` (`CODE_FIX_MODEL`) | Runs through the GitHub Copilot SDK, not Foundry. |
| Compliance | `model-router` (`COMPLIANCE_MODEL`) | Foundry prompt agent with **no tools** → router-safe. |

> ⚠️ `model-router` cannot be used for a Foundry prompt agent that carries **MCP tools** — tool calls fail
> with `tool_function_not_found` (500). That is why the InventoryAgent stays pinned to `gpt-4.1`.

```
Triage (LangGraph) ─▶ Code Fix (GH Copilot SDK) ─▶ Compliance (Foundry prompt agent)
        └──────────── common MAF Agent Harness + event bus ────────────┘
                     orchestrated by MAF · hosted on Foundry
```

## Layout
```
src/
  triage_langgraph.py    # Triage agent — a LangGraph StateGraph
  code_fix_copilot.py    # Code Fix agent — GitHub Copilot SDK harness on a sandbox copy
  compliance_foundry.py  # Compliance agent — Foundry prompt agent client
  harness.py             # common MAF harness: event bus + SharedTodoStore + OpenTelemetry
  orchestration.py       # MAF sequential workflow Triage → Code Fix → Compliance
sandbox_seed/            # the seeded buggy module + failing tests + incident.json
create_compliance_agent.py  # register the Foundry prompt agent (ComplianceReviewer)
main.py                  # Foundry hosting entrypoint (ResponsesHostServer)
test_orchestration.py    # end-to-end local run of the incident
```

## Harness capabilities

Beyond making three frameworks interchangeable, `harness.py` turns on two capabilities from the
[Agent Harnesses](https://learn.microsoft.com/agent-framework/agents/harness) doc:

| Capability | How | What you see |
|---|---|---|
| **Todo provider** | MAF `TodoProvider` bound to a custom **`SharedTodoStore`** (ignores `AgentSession`, so all three stages share **one** list) | Triage adds a 4-item remediation plan → Code Fix completes items from real signals (`pytest_runs`, `files_changed`, `test_passed`) → Compliance completes the review item, **or appends** its `required_changes`. Every mutation emits a `todo_updated` event. |
| **OpenTelemetry** | `setup_observability()` → `configure_otel_providers()` + the three `AzureMonitor*Exporter`s | One distributed GenAI trace spanning LangGraph, the Copilot SDK and the Foundry prompt agent — because they all reach MAF through `BaseChatClient`. |

Notes:
* `setup_observability()` is idempotent and never raises — no `APPLICATIONINSIGHTS_CONNECTION_STRING`
  simply means the run is untraced. `OTEL_SENSITIVE_DATA=true` attaches prompts/completions to spans.
* `TodoProvider` injects the checklist as a *user* message starting with `### Current todo list`;
  `last_user_text()` skips it so each stage still reads the incident.
* MAF hands the todo tools to an adapter in `options`, which is a plain **dict** — `HarnessTodos`
  reads `options["tools"]` (`getattr(options, "tools")` would silently return nothing).

## Run locally (repo root, venv)
```powershell
.\.venv\Scripts\python.exe agents\incident-orchestration\test_orchestration.py
```

## Deployed as a **Foundry Hosted Agent** ✅

The whole orchestration (all three agents + the harness) is registered in the Foundry project as a
single hosted agent named **`IncidentOrchestrator`** — that is the point of the demo: heterogeneous
frameworks in, one Foundry agent out.

```powershell
azd env set FOUNDRY_MODEL_DEPLOYMENT_NAME "gpt-4.1"
azd env set TRIAGE_MODEL "model-router"
azd env set COMPLIANCE_MODEL "model-router"
azd env set COMPLIANCE_AGENT_NAME "ComplianceReviewer"
azd env set ORCHESTRATION_AGENT_NAME "IncidentResponseOrchestrator"
azd env set CODE_FIX_MODEL "claude-sonnet-4.5"
azd env set GITHUB_TOKEN "<a GitHub token with Copilot access>"

# required by the OpenTelemetry harness capability (setup_observability())
azd env set APPLICATIONINSIGHTS_CONNECTION_STRING "<App Insights connection string>"
azd env set OTEL_SENSITIVE_DATA "false"

azd deploy incident-orchestration --no-prompt
azd ai agent show incident-orchestration --output json
```

Responses endpoint:

```
https://<account>.services.ai.azure.com/api/projects/zava-project/agents/IncidentOrchestrator/endpoint/protocols/openai/responses?api-version=v1
```

```powershell
$tok  = az account get-access-token --resource "https://ai.azure.com" --query accessToken -o tsv
$body = @{ input = "INC-4471: Nightly reorder service produced negative reorder quantities for well-stocked SKUs." } | ConvertTo-Json
Invoke-WebRequest -Uri $url -Method POST -Headers @{Authorization="Bearer $tok"} -ContentType "application/json" -Body $body -TimeoutSec 1200
```

The agent's own managed identity (`instance_identity.principal_id` in `azd ai agent show`) needs, on
the Foundry **account**: `Cognitive Services OpenAI User` (Triage calls `model-router` directly),
`Cognitive Services User`, `Azure AI Developer` and `Foundry User` (Compliance calls the
`ComplianceReviewer` prompt agent through the Responses API).

### Gotchas found while hosting this

| Symptom | Cause / fix |
|---|---|
| `server_error: No module named 'harness'` | The hosted runtime may import `src/*.py` as **top-level** modules rather than as the `src` package. `main.py` now puts both the project root **and** `src/` on `sys.path`, and the modules select their import style with `if __package__:` instead of a `try/except ImportError` — the old `except ImportError` **masked the real error**. |
| Code Fix reports "no files changed" | `GITHUB_TOKEN` is empty in the container, so the Copilot SDK falls back to `use_logged_in_user=True`, which cannot work headless. Set it with `azd env set GITHUB_TOKEN`. |
| Verdict says `approve` but the text says *NEEDS CHANGES* | The model answers `approve`, the code compared against `approved`. Normalised in `_normalize_decision()` (fails closed). |
| No spans in Application Insights | `azure-monitor-opentelemetry-exporter` was missing from `requirements.txt`, so `setup_observability()` failed its import and silently returned `False`. It is pinned now. Also make sure `APPLICATIONINSIGHTS_CONNECTION_STRING` reaches the container — `azure.yaml` passes it, ACA reads it from the `appinsights-connection` secret. |
| `Overriding of current TracerProvider is not allowed` at startup | Harmless. `azure-ai-agentserver` already configures Azure Monitor through the `microsoft-opentelemetry` distro; our `configure_otel_providers(...)` then attaches the MAF GenAI instrumentation to that existing provider. Spans still reach App Insights under `cloud_RoleName = IncidentResponseOrchestrator`. |
| `az acr build` dies with `'charmap' codec can't encode…` | Windows console encoding, **not** a build failure. The ACR run keeps going — check it with `az acr task show-run --registry <acr> --run-id <id>`. |

### Deployment state (last verified)

| Target | Artifact | Verified |
|---|---|---|
| Foundry hosted agent `IncidentOrchestrator` | version **7** | Responses call returned `approved`, 13/13 compliance checks (85 s) |
| Azure Container Apps `zava-orchestrator` | image **`zava-orchestrator:v3`**, revision `--0000002` | `approved`, `test_passed: true`, `iterations: 2` (61 s) |
| Harness capabilities in-container | `todos_add` (Triage) → `todos_complete` (Code Fix) → `todos_complete` (Compliance) | one shared plan across all three frameworks |
| OpenTelemetry | `cloud_RoleName = IncidentResponseOrchestrator` | 12 GenAI spans (`invoke_agent CodeFix`, …) + the `model-router` HTTP dependency in `appi-zava-cvm43wkpxaiyg` |

The two secrets on the ACA app are stored as Container Apps secrets and referenced with `secretref:`:

```powershell
az containerapp secret set -n zava-orchestrator -g rg-zava-demo `
  --secrets "github-token=<token>" "appinsights-connection=<connection string>"

az containerapp update -n zava-orchestrator -g rg-zava-demo `
  --image acrzavacvm43wkpxaiyg.azurecr.io/zava-orchestrator:v3 `
  --set-env-vars "OTEL_SENSITIVE_DATA=false" `
                 "GITHUB_TOKEN=secretref:github-token" `
                 "APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-connection"
```

> There is also an **Azure Container Apps** deployment of the identical container
> (`ORCHESTRATION_AGENT_ENDPOINT`), which the web app uses for the live event stream — the hosted
> agent exposes only the final Responses output, not the per-step `harness_step` events.

## Safety
The Code Fix harness only ever operates on a **fresh temporary copy** of `sandbox_seed/` — it never
touches the real repository, runs a bounded number of iterations, and its shell/filesystem access is
scoped to the sandbox directory.

See the teaching notebooks `notebooks/03_multi_agent_orchestration.{en,pt-BR}.ipynb`.
