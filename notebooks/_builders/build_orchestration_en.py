"""Builder for notebooks/03_multi_agent_orchestration.en.ipynb (English).

Run: .venv\\Scripts\\python.exe notebooks/_builders/build_orchestration_en.py
Mirrors the live IncidentResponseOrchestrator demo
(agents/incident-orchestration/): LangGraph + GitHub Copilot SDK +
Foundry prompt agent behind a common Microsoft Agent Framework harness.
"""
import os
import nbformat as nbf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "03_multi_agent_orchestration.en.ipynb")

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))
def code(t): cells.append(nbf.v4.new_code_cell(t.strip("\n")))

md(r"""
# 🧭 Zava · **Multi-framework Agent Orchestration** on Microsoft Foundry

> **Microsoft Agent Framework (MAF)** · **LangGraph** triage · **GitHub Copilot SDK** code-fix harness · **Foundry prompt agent** compliance · `SequentialBuilder` · `WorkflowAgent` · Foundry hosting
>
> 🇧🇷 A Portuguese version is available as `03_multi_agent_orchestration.pt-BR.ipynb`.

Zava's nightly **reorder service** produced **NEGATIVE reorder quantities** for well-stocked SKUs and
rounded real deficits **down** below the target level. This notebook walks through Demo #2: three agents
built with different frameworks cooperating through one **common MAF Agent Harness**:

1. **Triage Agent** — **LangGraph** classifies severity/category/component and routes the incident.
2. **Code Fix Agent** — **GitHub Copilot SDK** runs a real plan → execute shell/fs → assess → iterate loop
   on an isolated sandbox until `pytest` passes.
3. **Compliance Agent** — **Foundry prompt agent** reviews the fix against Zava engineering policy.

The same pipeline is then wrapped as a MAF `WorkflowAgent` and hosted via Foundry's Responses runtime.
""")

md(r"""
## 🏗️ Architecture

```mermaid
flowchart LR
  I[Incident JSON<br/>negative reorder quantities] --> H[Common MAF Agent Harness<br/>BaseChatClient adapters + EventBus]
  H --> T[Triage Agent<br/>LangGraph StateGraph]
  T --> C[Code Fix Agent<br/>GitHub Copilot SDK harness]
  C --> P[Compliance Agent<br/>Foundry prompt agent]
  P --> R[Approved / needs-changes<br/>structured JSON]

  subgraph ORCH[MAF orchestration]
    T -->|fenced JSON hand-off| C -->|fenced JSON hand-off| P
  end

  ORCH --> W[WorkflowAgent]
  W --> F[Foundry ResponsesHostServer<br/>Hosted Agent / ACA fallback]
```

**Two client-side ideas.**
- **MAF orchestration:** `SequentialBuilder` drives a deterministic pipeline, while a uniform chat-client
  surface hides whether a stage is LangGraph, Copilot SDK, or a Foundry prompt agent.
- **Agent harness loop by GitHub Copilot SDK:** the Code Fix agent plans, executes shell/filesystem tools,
  assesses with `pytest`, and iterates until the sandbox is green.

**Server-side Foundry idea.** The whole workflow can be hosted as a Foundry agent: isolated runtime,
stateful sessions, sub-second cold starts, observability, and evaluations. This repo attempts Foundry Hosted
Agent deployment and uses Azure Container Apps as the verified fallback because the hosted Responses runtime
currently has a known preview tool-argument issue (same pattern as the DeliverySupport agent).
""")

md(r"""
## ✅ Setup

Use the repo virtual environment as your Jupyter kernel (`.venv`). The live modules load the repo-root
`.env` and expect Azure / Copilot authentication:

- Azure: `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_ACCOUNT_ENDPOINT`, model deployment names, and `az login`
  / `DefaultAzureCredential`.
- GitHub Copilot SDK: package **`github-copilot-sdk`**, import name **`copilot`**.
- MAF provider: package **`agent-framework-github-copilot`**, exposing
  `agent_framework_github_copilot.GitHubCopilotAgent`, a native MAF `BaseAgent`.
- Copilot auth: `use_logged_in_user=True` uses the logged-in GitHub Copilot CLI user; `github_token=...`
  works for headless containers.

Packages used by this demo include:

```powershell
.\.venv\Scripts\pip.exe install langgraph github-copilot-sdk agent-framework `
  agent-framework-github-copilot agent-framework-orchestrations `
  agent-framework-foundry-hosting azure-ai-projects
```

> ⚠️ Cells that call Azure or GitHub Copilot need auth and can take **1–2 minutes**.
""")

code(r"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

# Notebook normally runs from notebooks/. Make imports robust if you run it elsewhere.
REPO = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
INCIDENT_DIR = REPO / "agents" / "incident-orchestration"
SRC = INCIDENT_DIR / "src"
sys.path.insert(0, str(INCIDENT_DIR))
sys.path.insert(0, str(SRC))

load_dotenv(REPO / ".env", override=False)

print("Repo       :", REPO)
print("Incident src:", SRC)
print("Project    :", os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "<set in .env>"))
print("Triage model:", os.environ.get("TRIAGE_MODEL") or os.environ.get("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))
print("Code-fix model:", os.environ.get("CODE_FIX_MODEL", "claude-sonnet-4.5"))
""")

code(r"""
# Entra authentication preflight.
#
# `shared_credential()` returns ONE `DefaultAzureCredential` per process, with `process_timeout=30`.
# That matters: a fresh credential per call shells out to `az account get-access-token` every time,
# and the 10 s default timeout is easy to blow past on a busy kernel -> the
# `AzureCliCredential: Failed to invoke the Azure CLI` error. A single instance caches the token.
#
# We ask for the token here, up front, so an expired `az login` fails in this cell rather than
# halfway through a two-minute pipeline run.
from harness import COGNITIVE_SCOPE, shared_credential

try:
    token = shared_credential().get_token(COGNITIVE_SCOPE)
    print("Entra OK · token expires:", __import__("datetime").datetime.fromtimestamp(token.expires_on))
except Exception as exc:
    print("AUTH FAILED — run `az login` (and `az account set -s <subscription>`), then re-run.")
    print(" ", type(exc).__name__, str(exc)[:300])
""")

code(r"""
# Copilot SDK auth smoke check. This does not run the code-fix harness yet.
#
# The SDK is async and the client must be *connected* before it answers: `async with` starts the
# underlying Copilot CLI process and shuts it down on exit. Calling `get_auth_status()` without
# that raises `RuntimeError: Client not connected`.
from copilot import CopilotClient

async with CopilotClient(log_level="error", use_logged_in_user=True) as probe:
    print(await probe.get_auth_status())

# In the real harness:
# - local interactive auth: CopilotClient(working_directory=sandbox, use_logged_in_user=True)
# - headless/container auth: CopilotClient(working_directory=sandbox, github_token=os.environ["GITHUB_TOKEN"])
""")

md(r"""
## 1️⃣ The incident + the sandbox

The source of truth is `agents/incident-orchestration/sandbox_seed/`:

- `incident.json` describes **ZAVA-INC-4821**.
- `reorder.py` contains the seeded defect.
- `test_reorder.py` captures the expected business rules.

The Code Fix agent never edits the repo. `code_fix_copilot.py` creates a **fresh sandbox copy** for every run,
then runs tools and `pytest` inside that isolated directory.
""")

code(r"""
from pathlib import Path
import json

seed = INCIDENT_DIR / "sandbox_seed"

for name in ["incident.json", "reorder.py", "test_reorder.py"]:
    print(f"\n===== {name} =====")
    text = (seed / name).read_text(encoding="utf-8")
    print(text[:2500])
""")

code(r"""
from orchestration import incident_text_from_seed

incident_text = incident_text_from_seed()
print(incident_text)
""")

md(r"""
## 2️⃣ Agent 1 — Triage (**LangGraph**)

The Triage agent is a compact LangGraph `StateGraph`:

```mermaid
flowchart LR
  START((START)) --> classify[classify<br/>Azure OpenAI + Entra token<br/>STRICT JSON]
  classify --> route[route<br/>deterministic rule]
  route --> END((END))
```

**LangGraph syntax:** state is a `TypedDict`; each **node** is a plain function `state -> partial state`;
`add_edge` wires them between the `START` and `END` sentinels; `compile()` returns a runnable graph you
invoke with a dict. Below is the real implementation — the same code as `src/triage_langgraph.py`.
""")

code(r'''
# Real implementation — same code as agents/incident-orchestration/src/triage_langgraph.py
import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph      # <- LangGraph
from harness import CODE_FIX, build_azure_openai_client, triage_model


class TriageState(TypedDict, total=False):
    """The graph state: every node reads it and returns a partial update."""
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


def classify_node(state: TriageState) -> TriageState:
    """LangGraph node: LLM classification of the incident into structured fields."""
    client = build_azure_openai_client()               # AzureOpenAI + Entra token, keyless
    completion = client.chat.completions.create(
        model=triage_model(),                          # model-router deployment
        temperature=0,
        response_format={"type": "json_object"},       # JSON mode -> parseable state
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
    """LangGraph node: deterministic (auditable) routing decision."""
    category = state.get("category", "")
    component = (state.get("component", "") or "").lower()
    is_code_defect = category in {"bug", "data-quality", "performance"} or component.endswith(".py")
    return {"route": CODE_FIX if is_code_defect else CODE_FIX}


def build_triage_graph() -> Any:
    """Compile the LangGraph `classify -> route` state graph."""
    graph = StateGraph(TriageState)
    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "route")
    graph.add_edge("route", END)
    return graph.compile()


triage_graph = build_triage_graph()
print("compiled graph:", type(triage_graph).__name__)
''')

code(r"""
# Run the LangGraph graph on its own (no MAF yet) — needs .env + az login. Seconds.
raw_state = triage_graph.invoke({"incident": incident_text})
print(json.dumps(raw_state, indent=2))
""")

md(r"""
### Making the LangGraph agent look like a MAF agent

MAF never sees LangGraph. It sees a `BaseChatClient` whose `_produce()` happens to invoke a graph. The
adapter also emits harness events and writes the shared remediation plan through the todo tools MAF put in
`options`. `Agent(client=adapter, ...)` then makes it an ordinary MAF agent.
""")

code(r'''
# Real implementation — the MAF adapter from src/triage_langgraph.py
import asyncio

from agent_framework import Agent, BaseChatClient
from harness import (
    TRIAGE, EventBus, HarnessChatClient, HarnessTodos, TriageResult,
    build_todo_provider, fenced_json, last_user_text,
)


class LangGraphTriageClient(HarnessChatClient, BaseChatClient):
    """MAF adapter that runs the LangGraph triage graph.

    Dual inheritance, on purpose:
      * `BaseChatClient`    — the MAF contract: what makes `Agent` accept this object as a client.
      * `HarnessChatClient` — our base (§5): implements `_inner_get_response` once and delegates
        to `_produce()` below, so all three adapters have the same shape.

    In other words: subclassing this is all it takes to plug a new framework into the pipeline.
    """

    # Identity on the event bus — this is how the UI knows which stage emitted each step.
    agent_id = TRIAGE

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    async def _produce(self, messages: Any, options: Any) -> str:
        """The only method an adapter needs: transcript in, stage text out.

        `messages` is the workflow's accumulated conversation; `options` is the **dict** MAF
        passes in, and where we pick up the todo tools (see §5.1).
        """
        # `last_user_text` skips the checklist the TodoProvider injects and returns the incident.
        incident = last_user_text(messages)
        await self._emit("agent_started", note="Classifying & routing the incident with LangGraph")

        # LangGraph is synchronous: `to_thread` keeps it off the MAF event loop.
        state: TriageState = await asyncio.to_thread(triage_graph.invoke, {"incident": incident})
        result = TriageResult(
            severity=state.get("severity", "unknown"),
            category=state.get("category", "unknown"),
            component=state.get("component", "unknown"),
            route=state.get("route", CODE_FIX),
            summary=state.get("summary", ""),
            incident_id=state.get("incident_id", ""),
        )
        await self._emit("harness_step", step="classify",
                         detail=f"severity={result.severity} · category={result.category} · component={result.component}")
        await self._emit("harness_step", step="route", detail=f"route -> {result.route}")

        # Triage owns the plan: it writes the checklist the later stages work through.
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
        human = (f"**Triage complete.** Severity **{result.severity}**, category **{result.category}**, "
                 f"component `{result.component}`. Routing to **{result.route}**.\n\n{result.summary}")
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


print("adapter ready:", LangGraphTriageClient.__name__)
''')

code(r"""
# Now run it as a MAF agent. Azure call: needs .env + az login.
bus = EventBus()
triage_agent = create_triage_agent(bus)
triage_response = await triage_agent.run(incident_text)

print(triage_response.text)
print("\nEvents:")
for event in bus.events:
    print(event.to_dict())
""")

md(r"""
## 3️⃣ Agent 2 — Code Fix (**GitHub Copilot SDK**)

The Code Fix agent is the "real work" stage:

1. Copy `sandbox_seed/` to a fresh sandbox.
2. Start `GitHubCopilotAgent` with a `CopilotClient` pointed at that sandbox.
3. Let the Copilot SDK harness plan, read files, edit `reorder.py`, run shell commands, and assess with
   `pytest -q`.
4. Use `on_pre_tool_use` to **auto-approve** each sandbox-scoped tool call and emit live `harness_step`
   events labelled Plan / Execute / Assess.
5. Capture the final diff, test output, and structured `{"code_fix": ...}` hand-off.

Models available to this provider include `claude-sonnet-4.5`, `gpt-5.4`, and other Copilot models exposed
in the environment.
""")

code(r'''
# Real implementation — same code as agents/incident-orchestration/src/code_fix_copilot.py
import difflib, json, shutil, subprocess, sys, tempfile
from pathlib import Path

from agent_framework_github_copilot import GitHubCopilotAgent   # MAF provider for the Copilot SDK
from copilot import CopilotClient                               # the GitHub Copilot SDK itself
from harness import CODE_FIX, EventBus

SANDBOX_SEED = INCIDENT_DIR / "sandbox_seed"
CODE_FIX_MODEL = os.getenv("CODE_FIX_MODEL", "claude-sonnet-4.5")
CODE_FIX_TIMEOUT = int(os.getenv("CODE_FIX_TIMEOUT", "300"))

FIX_PROMPT = """You are Zava's Code Fix agent working in an ISOLATED sandbox directory.

The file `reorder.py` implements the nightly reorder service. It has a defect: it produced
NEGATIVE reorder quantities for well-stocked SKUs and rounded genuine deficits DOWN below
target. The tests in `test_reorder.py` encode the correct behaviour and currently FAIL.

Do the following:
1. Run `pytest -q` to observe the failing tests.
2. Fix ONLY `reorder.py` so that every test passes. Do NOT modify the tests.
3. Keep the change minimal and preserve these invariants: a reorder quantity is never
   negative; it is 0 when on_hand is above the reorder point; otherwise it is rounded UP
   to whole case packs so on_hand + reorder >= target_level.
4. Re-run `pytest -q` to confirm all tests pass.

When finished, briefly summarise what was wrong and what you changed.
"""


def make_sandbox() -> Path:
    """Fresh temp copy of the seeded sandbox — the repo is never writable."""
    dest = Path(tempfile.mkdtemp(prefix="zava-codefix-"))
    for item in SANDBOX_SEED.glob("*"):
        if item.is_file():
            shutil.copy2(item, dest / item.name)
    return dest


def run_pytest(sandbox: Path) -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(sandbox),
                          capture_output=True, text=True, timeout=120)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def tool_summary(tool_name: str, tool_args: Any) -> str:
    """Short human label for a harness step (toolArgs arrives as a JSON string or a dict)."""
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except (json.JSONDecodeError, ValueError):
            tool_args = {"command": tool_args}
    args = tool_args if isinstance(tool_args, dict) else {}
    for key in ("command", "cmd", "script", "commandLine"):
        if args.get(key):
            return f"$ {str(args[key])[:80]}"
    for key in ("path", "filePath", "file_path", "file"):
        if args.get(key):
            return f"{tool_name}: {args[key]}"
    return tool_name


async def run_copilot_code_fix(bus: EventBus) -> dict:
    """plan -> execute (shell/fs) -> assess (pytest) -> iterate, inside a sandbox."""
    sandbox = make_sandbox()
    original = (sandbox / "reorder.py").read_text(encoding="utf-8")
    pytest_runs = 0

    async def on_pre_tool_use(hook_input: Any, _ctx: Any) -> dict:
        """Copilot SDK hook: fires before every tool call the harness wants to run."""
        nonlocal pytest_runs
        get = (lambda k: hook_input.get(k)) if isinstance(hook_input, dict) else (lambda k: getattr(hook_input, k, None))
        tool_name = get("toolName") or "tool"
        label = tool_summary(tool_name, get("toolArgs"))
        if "pytest" in label.lower():
            pytest_runs += 1
            phase = "assess"
        elif any(k in tool_name.lower() for k in ("write", "edit", "apply", "create")):
            phase = "execute"
        elif any(k in tool_name.lower() for k in ("read", "view")):
            phase = "plan"
        else:
            phase = "execute"
        await bus.emit("harness_step", CODE_FIX, step=phase, tool=tool_name, detail=label)
        return {"permissionDecision": "allow"}      # auto-approve: safe *because* it is a sandbox

    gh_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    auth = {"github_token": gh_token} if gh_token else {"use_logged_in_user": True}
    client = CopilotClient(working_directory=str(sandbox), log_level="error", **auth)

    async with GitHubCopilotAgent(
        name="CodeFix",
        client=client,
        default_options={
            "model": CODE_FIX_MODEL,
            "timeout": CODE_FIX_TIMEOUT,
            "on_pre_tool_use": on_pre_tool_use,     # <- where the harness observes/approves tools
        },
    ) as agent:
        response = await agent.run(FIX_PROMPT)

    test_passed, test_output = run_pytest(sandbox)
    fixed = (sandbox / "reorder.py").read_text(encoding="utf-8")
    diff = "".join(difflib.unified_diff(original.splitlines(keepends=True), fixed.splitlines(keepends=True),
                                        fromfile="reorder.py (before)", tofile="reorder.py (after)"))
    return {
        "summary": getattr(response, "text", None) or str(response),
        "test_passed": test_passed,
        "test_output": test_output[-1500:],
        "diff": diff,
        "files_changed": ["reorder.py"] if fixed != original else [],
        "iterations": max(pytest_runs, 1 if fixed != original else 0),
        "sandbox_path": str(sandbox),
    }


print("sandbox seed:", SANDBOX_SEED, "| model:", CODE_FIX_MODEL)
''')

code(r"""
# Live Copilot SDK run: needs GitHub Copilot auth. Expected duration: ~1–2 minutes.
bus = EventBus()
fix = await run_copilot_code_fix(bus)

print("HARNESS TIMELINE")
for event in bus.events:
    print(f"  {event.data.get('step', ''):8s} {event.data.get('detail', '')}")

print("\ntests passed:", fix["test_passed"], "| iterations:", fix["iterations"])
print("\nDIFF\n" + fix["diff"])
print("\nSUMMARY\n" + fix["summary"][:1500])
""")

md(r"""
### Making the Copilot harness look like a MAF agent

Same adapter pattern as Triage: a `BaseChatClient` whose `_produce()` drives the Copilot loop, reads the
upstream `{"triage": ...}` block out of the conversation, and appends its own `{"code_fix": ...}` block.
""")

code(r'''
# Real implementation — the MAF adapter from src/code_fix_copilot.py
from harness import CodeFixResult, extract_last_json


class CopilotCodeFixClient(HarnessChatClient, BaseChatClient):
    """MAF adapter that runs the GitHub Copilot SDK harness on a sandbox."""

    agent_id = CODE_FIX

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    async def _produce(self, messages: Any, options: Any) -> str:
        triage = extract_last_json(messages, must_have="triage") or {}
        triage_info = triage.get("triage", triage)

        await self._emit("agent_started", note="Running the GitHub Copilot SDK harness on an isolated sandbox",
                         model=CODE_FIX_MODEL)
        outcome = await run_copilot_code_fix(self._bus)          # <- the harness loop defined above
        result = CodeFixResult(**{k: v for k, v in outcome.items() if k != "triage"})
        await self._emit("agent_completed", result=result.to_dict())

        # Tick off the plan Triage wrote — only from *real* signals of this run.
        todos = HarnessTodos(options)
        changed = ", ".join(result.files_changed)
        if todos.available:
            done = []
            if result.iterations:
                item = await todos.find("reproduce")
                if item:
                    done.append((item, f"pytest executed {result.iterations}x in the sandbox"))
            if result.files_changed:
                item = await todos.find("patch")
                if item:
                    done.append((item, f"edited {changed}"))
            if result.test_passed:
                item = await todos.find("re-run", "test suite")
                if item:
                    done.append((item, "suite green after the fix"))
            if done:
                await todos.complete(*done)

        status = "✅ all tests pass" if result.test_passed else "❌ tests still failing"
        human = (f"**Code Fix complete** — {status} after {result.iterations} iteration(s); "
                 f"changed: {changed or 'none'}.\n\n{result.summary}")
        return fenced_json({"code_fix": {**result.to_dict(), "triage": triage_info}}) + "\n\n" + human


def create_code_fix_agent(bus: EventBus | None = None, todo_store: Any = None) -> Agent:
    """Return the Code Fix stage as a MAF agent."""
    return Agent(
        client=CopilotCodeFixClient(bus=bus),
        name="CodeFix",
        description="Fixes the defect in an isolated sandbox using the GitHub Copilot SDK harness.",
        instructions="You are the Zava incident Code Fix agent.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


print("adapter ready:", CopilotCodeFixClient.__name__)
''')

md(r"""
## 4️⃣ Agent 3 — Compliance (**Foundry prompt agent**)

The Compliance agent is registered in Foundry by `create_compliance_agent.py`. Its prompt embeds
`data/company/zava-engineering-policy.md` and requires a strict JSON decision:

```json
{
  "decision": "approved | needs-changes",
  "checks": [{"id": "C1", "status": "pass | fail | n/a"}],
  "rationale": "short justification",
  "required_changes": []
}
```

`FoundryComplianceClient` invokes it through the Responses API with
`extra_body={"agent_reference": {"type": "agent_reference", "name": "ComplianceReviewer"}}`. If the prompt
agent is unavailable, the module has a direct policy-grounded model fallback so the pipeline still completes.
""")

code(r'''
# Real implementation — same code as agents/incident-orchestration/create_compliance_agent.py
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition     # <- Foundry prompt-agent definition
from azure.identity import DefaultAzureCredential

AGENT_NAME = os.getenv("COMPLIANCE_AGENT_NAME", "ComplianceReviewer")
COMPLIANCE_MODEL = os.getenv("COMPLIANCE_MODEL", os.getenv("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))
POLICY = (REPO / "data" / "company" / "zava-engineering-policy.md").read_text(encoding="utf-8")

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

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
)

# Prompt agents are *service-side*: model + instructions (+ optional tools), versioned by Foundry.
compliance_version = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(model=COMPLIANCE_MODEL, instructions=INSTRUCTIONS),
)
print("registered:", compliance_version.name, "version", getattr(compliance_version, "version", "?"))
print("model     :", COMPLIANCE_MODEL, "| policy chars:", len(POLICY))
''')

md(r"""
The prompt agent is invoked through the **Responses API**: you call the *model* endpoint and point it at the
registered agent with `extra_body={"agent_reference": ...}`. No SDK agent object is instantiated locally —
the instructions live in Foundry.
""")

code(r'''
# Raw Foundry prompt-agent call (no MAF yet).
files = ", ".join(fix["files_changed"]) or "none"
review_input = (
    f"INCIDENT:\n{incident_text}\n\n"
    f"PROPOSED FIX SUMMARY:\n{fix['summary']}\n\n"
    f"TESTS PASSED: {fix['test_passed']}\n"
    f"TEST OUTPUT:\n{fix['test_output']}\n\n"
    f"FILES CHANGED: {files}\n\n"
    f"UNIFIED DIFF:\n{fix['diff']}\n"
)

oai = project.get_openai_client()
resp = oai.responses.create(
    model=COMPLIANCE_MODEL,
    input=review_input,
    extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
)
print(resp.output_text)
''')

md(r"""
### Making the Foundry prompt agent look like a MAF agent

Third adapter, same shape. It parses the strict JSON decision, and — unlike the other two stages — it can
**grow** the shared plan: a *needs-changes* verdict appends its `required_changes` as new todo items.
""")

code(r'''
# Real implementation — the MAF adapter from src/compliance_foundry.py
from harness import COMPLIANCE, ComplianceResult, extract_json


def normalize_decision(raw: Any) -> str:
    """Fail closed: anything that is not clearly an approval is `needs-changes`."""
    value = str(raw or "").strip().lower().replace("_", "-")
    return "approved" if value in {"approve", "approved", "pass", "passed", "ok"} else "needs-changes"


class FoundryComplianceClient(HarnessChatClient, BaseChatClient):
    """MAF adapter that calls the Foundry ComplianceReviewer prompt agent."""

    agent_id = COMPLIANCE

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    def _call_foundry(self, review_input: str) -> str:
        oai = project.get_openai_client()
        resp = oai.responses.create(
            model=COMPLIANCE_MODEL,
            input=review_input,
            extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
        )
        return resp.output_text

    async def _produce(self, messages: Any, options: Any) -> str:
        payload = extract_last_json(messages, must_have="code_fix") or {}
        code_fix = payload.get("code_fix", payload)
        incident = last_user_text(messages)

        await self._emit("agent_started",
                         note="Reviewing the fix against Zava engineering policy (Foundry prompt agent)")
        files = ", ".join(code_fix.get("files_changed", []) or []) or "none"
        review_input = (
            f"INCIDENT:\n{incident}\n\n"
            f"PROPOSED FIX SUMMARY:\n{code_fix.get('summary', '')}\n\n"
            f"TESTS PASSED: {code_fix.get('test_passed')}\n"
            f"TEST OUTPUT:\n{code_fix.get('test_output', '')}\n\n"
            f"FILES CHANGED: {files}\n\n"
            f"UNIFIED DIFF:\n{code_fix.get('diff', '')}\n"
        )
        text = await asyncio.to_thread(self._call_foundry, review_input)

        parsed = extract_json(text) or {}
        result = ComplianceResult(
            decision=normalize_decision(parsed.get("decision")),
            checks=parsed.get("checks", []) or [],
            rationale=str(parsed.get("rationale", text[:500])),
            required_changes=parsed.get("required_changes", []) or [],
        )
        await self._emit("harness_step", step="policy-review", detail=f"{len(result.checks)} checks evaluated")

        # Compliance either closes the plan or GROWS it with the changes it demands.
        todos = HarnessTodos(options)
        if todos.available:
            if result.decision == "approved":
                item = await todos.find("review", "policy")
                if item:
                    await todos.complete((item, f"{len(result.checks)} policy checks passed"))
            elif result.required_changes:
                await todos.add(*result.required_changes)

        await self._emit("agent_completed", result=result.to_dict())
        badge = "✅ APPROVED" if result.decision == "approved" else "⚠️ NEEDS CHANGES"
        lines = [f"**Compliance review — {badge}.**", "", result.rationale]
        lines += [f"- {item}" for item in result.required_changes]
        return fenced_json({"compliance": result.to_dict()}) + "\n\n" + "\n".join(lines)


def create_compliance_agent(bus: EventBus | None = None, todo_store: Any = None) -> Agent:
    """Return the Compliance stage as a MAF agent."""
    return Agent(
        client=FoundryComplianceClient(bus=bus),
        name="Compliance",
        description="Reviews the fix against Zava engineering policy (Foundry prompt agent).",
        instructions="You are ComplianceReviewer for Zava.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


print("adapter ready:", FoundryComplianceClient.__name__)
''')

code(r"""
# Run the compliance stage as a MAF agent over the fix produced above.
bus = EventBus()
compliance_agent = create_compliance_agent(bus)
compliance_response = await compliance_agent.run(
    fenced_json({"code_fix": fix}) + "\n\nReview this proposed fix."
)

print(compliance_response.text)
print("\nEvents:")
for event in bus.events:
    print(event.to_dict())
""")

md(r"""
## 5️⃣ The common **MAF Agent Harness**

This is the key integration pattern. Each heterogeneous framework is wrapped as a MAF `BaseChatClient`
subclass implementing `_inner_get_response(self, *, messages, stream, options, **kwargs)`:

- non-stream returns `ChatResponse(messages=[Message(role="assistant", contents=[text])])`
- stream returns `self._build_response_stream(async_gen_of_ChatResponseUpdate)`

Then `Agent(client=adapter, name=..., instructions=...)` makes each framework look like an ordinary MAF
agent. **That uniform ChatClient surface is the common Agent Harness.**

The same harness also owns `EventBus`, a tiny async pub/sub that emits `agent_started`, `harness_step`,
`agent_completed`, and `run_completed`. The notebook and the tests all read the same stream.
""")

code(r'''
# Real implementation — the base adapter + event bus from src/harness.py
import time
from dataclasses import dataclass, field
from typing import Any

@dataclass
class HarnessEvent:
    """One observable fact from the pipeline. `type` is the category (`harness_step`,
    `agent_completed`…), `agent` says which stage emitted it, `data` carries the free-form
    payload the UI renders."""
    type: str
    agent: str
    ts: float
    data: dict[str, Any] = field(default_factory=dict)

class HarnessChatClient:
    """The base shared by all three adapters — *this* is the common Agent Harness.

    It translates the MAF contract (`_inner_get_response`) into a single easy method to implement
    (`_produce`), and adds event emission. A new framework joins the pipeline by subclassing this
    — nothing else in MAF has to change.
    """

    agent_id: str = "orchestrator"
    _bus = None

    async def _emit(self, type: str, **data: Any) -> None:
        """Publish an event tagged with this stage. No bus, no-op."""
        if self._bus is not None:
            await self._bus.emit(type, self.agent_id, **data)

    async def _produce(self, messages, options) -> str:
        """Implemented by each adapter: run the native framework, return the stage's text."""
        raise NotImplementedError

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        """The method MAF actually calls. Fixed signature — keyword-only, including `stream`."""
        from agent_framework import ChatResponse, Message
        text = await self._produce(messages, options)
        if stream:
            # On the streaming path MAF expects a ChatResponseUpdate stream, not a response.
            return self._build_response_stream(self._as_updates(text))
        return ChatResponse(
            messages=[Message(role="assistant", contents=[text])],
            response_id=f"{self.agent_id}-{int(time.time() * 1000)}",
        )

print("The real EventBus retains events and broadcasts them to async subscribers.")
''')

md(r"""
### What a "harness" actually is — and what ours provides

Microsoft's [Agent Harnesses](https://learn.microsoft.com/agent-framework/agents/harness) doc defines a
harness as **the runtime scaffolding around a model**: the loop that invokes tools, persists history,
compacts context, tracks tasks and enforces approvals. MAF ships a *harness factory*
(`create_harness_agent`) that assembles those pieces for you; here we build the scaffolding **by hand**,
because our requirement is different — we are not wrapping one model, we are making **three frameworks
interchangeable**.

Concretely, our harness fixes these **parameters** so every agent behaves the same way:

| Parameter | Value | Why it matters |
|---|---|---|
| Orchestration | `SequentialBuilder` | Deterministic Triage → Code Fix → Compliance over one shared conversation. |
| Uniform surface | `agent_framework.BaseChatClient` ×3 | Every framework becomes an ordinary MAF chat client — *this adapter layer is the harness*. |
| Hand-off format | fenced JSON | Each stage appends a ` ```json ` block; the next stage picks up its object with `extract_last_json()`. |
| Event bus | async pub/sub | One stream feeds the notebook trace and the tests. |
| Tool approval | auto-approve (sandbox) | `on_pre_tool_use` returns `permissionDecision=allow` — safe *because* the harness only touches a temp copy. |
| Loop bound | `CODE_FIX_TIMEOUT` (300 s) | Caps the Copilot plan → execute → assess loop; `pytest` passing is the completion condition. |
| Isolation | temp sandbox | `sandbox_seed/` is copied per run; the real repository is never writable. |
| Wrapped as | `WorkflowAgent` | The whole workflow is exposed as a *single* agent and served by `ResponsesHostServer`. |
| Todo provider | `SharedTodoStore` | One MAF `TodoProvider` shared by all three stages — a single remediation plan, not three private lists. |
| Observability | `configure_otel_providers()` | MAF is instrumented once, so all three frameworks emit **one** GenAI trace to Application Insights. |

And these are the **harness capabilities** from the doc, mapped honestly onto this demo:

| Capability | Here | Note |
|---|---|---|
| Function invocation | ✅ active | Each adapter runs its framework's own tool loop. |
| Tool approval | ✅ active | Auto-approve, scoped to the sandbox. |
| Looping until done | ✅ active | Code Fix iterates until tests pass or the timeout hits. |
| Shell environment | ✅ active | Copilot SDK gets read/edit/shell inside the temp dir. |
| **Todo provider** | ✅ active | Triage writes the plan, Code Fix ticks items off, Compliance verifies — §5.1 below. |
| **OpenTelemetry** | ✅ active | `setup_observability()` exports one distributed trace — §5.2 below. |
| History persistence · compaction | ⚪ available | Not needed: three bounded stages in one conversation. |
| Agent mode · web search | ⛔ harness factory | Provided by `create_harness_agent`, not by hand-built adapters. |
""")

md(r"""
### 5️⃣.1 Harness capability — the **todo provider** (one shared plan)

MAF ships a real `TodoProvider`: a `ContextProvider` that injects todo instructions, five tools
(`todos_add`, `todos_complete`, `todos_remove`, `todos_get_remaining`, `todos_get_all`) and the current
checklist into every turn. It is exactly the "task tracking" capability from the harness doc.

There is one catch that matters enormously here. The default `TodoSessionStore` keeps items in
`AgentSession.state` — so **each agent would get its own list**. We want the opposite: one remediation
plan that Triage writes, Code Fix works through and Compliance verifies. Swapping the store is the
documented extension point, so we implement a tiny store that ignores the session:

```python
class SharedTodoStore:                      # duck-types agent_framework.TodoStore
    def __init__(self, bus=None):
        self.items, self.next_id, self._bus = [], 1, bus

    async def load_state(self, session, *, source_id):
        return list(self.items), self.next_id                 # same list for every stage

    async def load_items(self, session, *, source_id):
        return list(self.items)

    async def save_state(self, session, items, *, next_id, source_id):
        self.items, self.next_id = list(items), next_id
        if self._bus:                                          # republish so the UI can animate it
            await self._bus.emit("todo_updated", ORCHESTRATOR, todos=self.snapshot())
```

Then all three agents receive a provider bound to **the same** store:

```python
store = SharedTodoStore(bus)
triage     = create_triage_agent(bus, store)
code_fix   = create_code_fix_agent(bus, store)
compliance = create_compliance_agent(bus, store)
# each factory does: context_providers=[TodoProvider(instructions=..., store=store)]
```

**Who calls the tools?** In a normal agent the *model* decides to call `todos_add`. Our adapters wrap
frameworks that return structured results, so the **harness** calls them on the stage's behalf — same
provider, same store, same plan. MAF hands the tools to the adapter in `options`, which is a plain
**dict** (a detail worth knowing — `getattr(options, "tools")` silently returns nothing):

```python
class HarnessTodos:
    def __init__(self, options):
        tools = (options or {}).get("tools") or [] if isinstance(options, dict) else []
        self._tools = {t.name: t for t in tools}

    async def add(self, *titles):
        await self._tools["todos_add"].invoke(arguments={"todos": [{"title": t} for t in titles]})

    async def complete(self, *pairs):       # note: `items=`, not `completions=`
        await self._tools["todos_complete"].invoke(
            arguments={"items": [{"id": i, "reason": r} for i, r in pairs]})
```

Each stage then drives the plan from **real signals only** — never from a guess:

| Stage | What it does to the plan | Signal |
|---|---|---|
| Triage | adds 4 items (reproduce · patch · re-run tests · policy review) | its own classification |
| Code Fix | completes *reproduce* / *patch* / *re-run* | `pytest_runs`, `files_changed`, `test_passed` |
| Compliance | completes *policy review*, **or appends** the `required_changes` it demands | its decision |

That last row is the interesting one: when Compliance answers *needs-changes*, the plan **grows** —
the harness hands you a live, auditable remediation checklist instead of a wall of JSON.

> One more subtlety: `TodoProvider` injects the checklist as a **user** message beginning with
> `### Current todo list`. Our `last_user_text()` skips messages with that marker, so each stage still
> reads the incident text rather than the checklist.
""")

md(r"""
### 5️⃣.2 Harness capability — **OpenTelemetry** across three frameworks

This is where a uniform harness really pays off. Because LangGraph, the Copilot SDK and the Foundry
prompt agent all reach MAF through `BaseChatClient` adapters, **instrumenting MAF instruments all
three identically** — one distributed trace, GenAI semantic conventions, no per-framework exporters.

```python
def setup_observability() -> bool:
    from agent_framework.observability import configure_otel_providers
    from azure.monitor.opentelemetry.exporter import (
        AzureMonitorLogExporter, AzureMonitorMetricExporter, AzureMonitorTraceExporter,
    )
    conn = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    os.environ.setdefault("OTEL_SERVICE_NAME", ORCHESTRATION_SERVICE_NAME)
    configure_otel_providers(
        exporters=[AzureMonitorTraceExporter(connection_string=conn),
                   AzureMonitorLogExporter(connection_string=conn),
                   AzureMonitorMetricExporter(connection_string=conn)],
        enable_sensitive_data=_truthy(os.getenv("OTEL_SENSITIVE_DATA")),
    )
    return True
```

Notes worth remembering:

* In `agent_framework` 1.12 the entry point is **`configure_otel_providers()`** (plus
  `enable_instrumentation()` if you configure the providers yourself) — there is no `setup_observability`
  in the package; the function above is *ours*.
* It must run **once per process**, so the real implementation guards with a module-level flag and never
  raises: missing App Insights simply means the pipeline runs untraced.
* `enable_sensitive_data` controls whether prompts/completions are attached to spans. It is **off** by
  default and gated behind `OTEL_SENSITIVE_DATA` — leave it off outside a demo tenant.
* You need `azure-monitor-opentelemetry-exporter` (the three `AzureMonitor*Exporter` classes), not the
  `azure-monitor-opentelemetry` distro.

Run the pipeline, then in the Foundry portal open **Tracing** (or App Insights → *Transaction search*)
and you will see a single trace whose children are the three stages — LangGraph, Copilot and Foundry
side by side.
""")

md(r"""
## 6️⃣ Orchestrate with MAF

`orchestration.py` wires the three agents into a deterministic sequence — and hands all of them the
**same** event bus and the **same** todo store, which is what turns three adapters into one harness:

```python
from agent_framework_orchestrations import SequentialBuilder

setup_observability()                     # one OTel trace across the three frameworks
bus, store = EventBus(), SharedTodoStore(bus)

workflow = SequentialBuilder(participants=[
    create_triage_agent(bus, store),
    create_code_fix_agent(bus, store),
    create_compliance_agent(bus, store),
]).build()
result = await workflow.run(incident_text)
```

Each stage writes a fenced JSON block (for example `{"triage": {...}}`, `{"code_fix": {...}}`,
`{"compliance": {...}}`) plus a human-readable summary. Downstream stages scan the accumulated conversation
for the latest relevant block, so the hand-off is structured and auditable.
""")

md(r"""
```mermaid
sequenceDiagram
  participant Ops as Ops incident
  participant MAF as MAF SequentialBuilder
  participant T as Triage<br/>LangGraph
  participant C as Code Fix<br/>Copilot SDK
  participant P as Compliance<br/>Foundry prompt agent
  participant Todo as SharedTodoStore
  participant Bus as EventBus

  Ops->>MAF: incident text
  MAF->>T: run
  T-->>Bus: agent_started, classify, route, completed
  T->>Todo: todos_add x4 (remediation plan)
  Todo-->>Bus: todo_updated
  T-->>MAF: ```json {"triage": ...}
  MAF->>C: transcript with triage JSON
  C-->>Bus: Plan / Execute / Assess harness_step events
  C->>Todo: todos_complete (reproduce, patch, re-run)
  Todo-->>Bus: todo_updated
  C-->>MAF: ```json {"code_fix": ...}
  MAF->>P: transcript with code_fix JSON
  P-->>Bus: policy-review, completed
  P->>Todo: complete review item OR add required_changes
  Todo-->>Bus: todo_updated
  P-->>MAF: ```json {"compliance": ...}
  MAF-->>Bus: run_completed (+ final plan)
```
""")

md(r"""
`build_incident_workflow()` in `src/orchestration.py` is exactly the function below: create the three
per-framework agents, pass them the **same** `EventBus` and the **same** todo store, and build a MAF
sequential workflow. Here we build it from the adapters we defined in this notebook.
""")

code(r'''
# Real implementation — same code as agents/incident-orchestration/src/orchestration.py
from agent_framework_orchestrations import SequentialBuilder    # <- MAF orchestration
from harness import ORCHESTRATOR, SharedTodoStore, setup_observability


def build_incident_workflow(bus: EventBus | None = None, todo_store: Any = None) -> Any:
    """Triage (LangGraph) -> Code Fix (Copilot SDK) -> Compliance (Foundry prompt agent).

    `bus` and `todo_store` are handed to ALL THREE agents on purpose: sharing those two instances
    is what turns three independent adapters into a single harness — one event stream and one
    remediation plan, instead of three private ones.
    """
    triage = create_triage_agent(bus, todo_store)
    code_fix = create_code_fix_agent(bus, todo_store)
    compliance = create_compliance_agent(bus, todo_store)
    # SequentialBuilder: runs the participants in order over ONE accumulated conversation — each
    # stage's output is appended to the transcript the next one receives. No LLM routing here: the
    # order is deterministic and auditable, which is what incident response wants.
    return SequentialBuilder(participants=[triage, code_fix, compliance]).build()


print("OpenTelemetry configured:", setup_observability())   # one trace across the three frameworks

bus = EventBus()
todo_store = SharedTodoStore(bus)          # one store for the WHOLE run -> one shared plan (see 5.1)
workflow = build_incident_workflow(bus, todo_store)
print("sequential workflow built:", type(workflow).__name__)
''')

code(r'''
# End-to-end run: needs Azure + Copilot auth. Expected duration: ~1–2 minutes.
# This is the body of `run_incident()` in src/orchestration.py.
await bus.emit("run_started", ORCHESTRATOR, incident=incident_text)
workflow_result = await workflow.run(incident_text)        # <- MAF drives all three stages

outputs = workflow_result.get_outputs()
flat = [m for item in outputs for m in (item if isinstance(item, list) else [item])]
final_text = next((m.text for m in reversed(flat) if getattr(m, "text", None)), "")

def last_result(agent_id: str):
    for event in reversed(bus.events):
        if event.agent == agent_id and event.type == "agent_completed":
            return event.data.get("result")
    return None

print("EVENT TIMELINE")
for event in bus.events:
    data = event.to_dict()
    detail = data.get("detail") or data.get("note") or data.get("decision") or ""
    print(f"{event.agent:12s} {event.type:16s} {detail}")

print("\nSHARED REMEDIATION PLAN (MAF todo provider)")
for item in todo_store.snapshot():
    print(f"  [{'x' if item['done'] else ' '}] {item['title']}")

print("\nFINAL DECISION")
print("tests passed:", (last_result(CODE_FIX) or {}).get("test_passed"))
print("compliance  :", (last_result(COMPLIANCE) or {}).get("decision"))
print("\nFinal text:")
print(final_text[:2000])
''')

md(r"""
> `orchestration.run_incident(incident_text, bus=bus)` packages exactly the cell above (plus
> `bus.close()` and an `OrchestrationResult` dataclass), and is what the deployed service calls.
""")

md(r"""
## 7️⃣ Evaluating the pipeline

A multi-agent pipeline is not scored like a chatbot. Its output is **structured** — Triage emits
`{"triage": ...}`, Code Fix emits `{"code_fix": ...}`, Compliance emits `{"compliance": ...}` — and the
questions that matter have exact answers: *was the severity right? did the tests actually go green? did the
policy reviewer fail closed?*

That makes **custom code-based evaluators** the primary measure here, not an LLM judge:

| Evaluator | Flavour | What it checks |
|---|---|---|
| `zava_triage_match` | **custom, code** | severity / category / component versus the expected classification |
| `zava_fix_verified` | **custom, code** | a file really changed **and** the suite is green (diff not empty) |
| `zava_compliance_decision` | **custom, code** | the verdict matches ground truth **and** never approves red tests |
| `builtin.task_adherence` | built-in | the run followed the pipeline it was told to follow |
| `builtin.coherence` | built-in | the final operator summary hangs together |
| `zava_incident_rubric` | **rubric** | weighted end-to-end incident-response quality |

The data source is a **dataset** of completed pipeline transcripts
(`agents/incident-orchestration/evals/incident_eval.jsonl`) — four incidents, one of which deliberately ships
a fix with failing tests so you can watch `zava_fix_verified` catch it. Re-running the live pipeline for every
row would cost minutes per incident; scoring recorded transcripts is fast, repeatable and diff-able in CI.
""")

code(r'''
# Dataset: four completed incident transcripts, each with the expected outcome.
import json
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
)
oai = project.get_openai_client()
JUDGE = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")

EVAL_DATASET = INCIDENT_DIR / "evals" / "incident_eval.jsonl"
rows = [json.loads(line) for line in EVAL_DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
for row in rows:
    print(f"{row['incident_id']}  expected: {row['expected_severity']}/{row['expected_category']}"
          f"/{row['expected_component']} -> {row['expected_decision']}")

# Dataset versions are immutable, so bump until one is free (re-running this cell stays painless).
def upload_dataset(name, file_path):
    last = None
    for version in range(1, 50):
        try:
            return project.datasets.upload_file(name=name, version=str(version), file_path=file_path)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"could not upload {name}: {last}")

dataset = upload_dataset("zava-incident-eval", str(EVAL_DATASET))
print("\ndataset id:", dataset.id)

# Want to score a *live* run instead? `run_eval.py --from-run` executes the real pipeline once and
# appends its output as an extra row before uploading.
''')

md(r"""
### 7️⃣.1 Code-based evaluators over the structured hand-offs

Each evaluator is a sandboxed `grade(sample, item) -> float`. They all start from the same tiny helper that
re-parses the fenced JSON blocks out of the transcript — exactly the hand-off format §5 defined.
""")

code(r'''
from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

# Prepended to every grader: the sandbox shares no imports between evaluators.
JSON_HELPER = """
import json
import re


def _blocks(text: str) -> dict:
    merged = {}
    for match in re.findall(r"```json\\s*(\\{.*?\\})\\s*```", text or "", re.DOTALL):
        try:
            merged.update(json.loads(match))
        except Exception:
            continue
    return merged


def _text(item: dict) -> str:
    return item.get("sample", {}).get("output_text") or item.get("response") or ""
"""

TRIAGE_MATCH_CODE = JSON_HELPER + """

def grade(sample: dict, item: dict) -> float:
    # Fraction of triage fields (severity, category, component) matching ground truth.
    try:
        triage = _blocks(_text(item)).get("triage") or {}
        if not triage:
            return 0.0
        checks = [
            (str(triage.get("severity", "")).lower(), str(item.get("expected_severity", "")).lower()),
            (str(triage.get("category", "")).lower(), str(item.get("expected_category", "")).lower()),
            (str(triage.get("component", "")).lower(), str(item.get("expected_component", "")).lower()),
        ]
        checks = [(a, e) for a, e in checks if e]
        if not checks:
            return 0.0
        return round(sum(1 for a, e in checks if a == e) / len(checks), 4)
    except Exception:
        return 0.0
"""

FIX_VERIFIED_CODE = JSON_HELPER + """

def grade(sample: dict, item: dict) -> float:
    # 1.0 only when a file changed AND the suite is green AND there is a real diff.
    try:
        code_fix = _blocks(_text(item)).get("code_fix") or {}
        if not code_fix:
            return 0.0
        ok = bool(code_fix.get("files_changed")) and bool(code_fix.get("test_passed"))
        return 1.0 if (ok and str(code_fix.get("diff", "")).strip()) else 0.0
    except Exception:
        return 0.0
"""

COMPLIANCE_DECISION_CODE = JSON_HELPER + """

def grade(sample: dict, item: dict) -> float:
    # Verdict matches ground truth - and fails closed on red tests.
    try:
        blocks = _blocks(_text(item))
        compliance = blocks.get("compliance") or {}
        code_fix = blocks.get("code_fix") or {}
        if not compliance:
            return 0.0
        decision = str(compliance.get("decision", "")).strip().lower().replace("_", "-")
        expected = str(item.get("expected_decision", "")).strip().lower().replace("_", "-")
        if decision == "approved" and code_fix and not code_fix.get("test_passed"):
            return 0.0                      # approving red tests is always wrong
        if decision == "needs-changes" and not compliance.get("required_changes"):
            return 0.5                      # blocking without saying what to change is half an answer
        if not expected:
            return 1.0 if decision in ("approved", "needs-changes") else 0.0
        return 1.0 if decision == expected else 0.0
    except Exception:
        return 0.0
"""

ITEM_PROPERTIES = {
    "query": {"type": "string"},
    "response": {"type": "string"},
    "expected_severity": {"type": "string"},
    "expected_category": {"type": "string"},
    "expected_component": {"type": "string"},
    "expected_decision": {"type": "string"},
}

def register_code_evaluator(name, display_name, description, code_text):
    return project.beta.evaluators.create_version(
        name=name,
        evaluator_version={
            "name": name,
            "categories": [EvaluatorCategory.AGENTS],
            "display_name": display_name,
            "description": description,
            "definition": {
                "type": EvaluatorDefinitionType.CODE,
                "code_text": code_text,
                "init_parameters": {
                    "type": "object",
                    "properties": {"deployment_name": {"type": "string"},
                                   "pass_threshold": {"type": "number"}},
                    "required": ["deployment_name", "pass_threshold"],
                },
                "metrics": {"result": {"type": "continuous", "desirable_direction": "increase",
                                       "min_value": 0.0, "max_value": 1.0}},
                "data_schema": {"type": "object", "required": ["item"],
                                "properties": {"item": {"type": "object", "properties": ITEM_PROPERTIES}}},
            },
        },
    )

for name, display, description, code_text in [
    ("zava_triage_match", "Zava Triage Match",
     "Do severity, category and component match the expected classification?", TRIAGE_MATCH_CODE),
    ("zava_fix_verified", "Zava Fix Verified",
     "Did the Code Fix stage change a file and leave the tests green?", FIX_VERIFIED_CODE),
    ("zava_compliance_decision", "Zava Compliance Decision",
     "Does the policy verdict match ground truth and fail closed on red tests?", COMPLIANCE_DECISION_CODE),
]:
    evaluator = register_code_evaluator(name, display, description, code_text)
    print("registered:", evaluator.name, "v" + str(evaluator.version))
''')

md(r"""
### 7️⃣.2 The incident-response **rubric**

The code evaluators answer *was it right?*. The rubric answers *was it good?* — weighted dimensions an LLM
judge scores 1–5 with a reason, covering the things ground truth cannot encode: was the fix minimal, did each
stage carry the previous stage's result forward, would an on-call engineer understand the summary.
""")

code(r'''
INCIDENT_RUBRIC_DIMENSIONS = [
    {"id": "triage_correctness", "weight": 9, "description":
     "Classifies severity, category and the failing component correctly from the incident text alone, "
     "and routes the incident to the stage that can actually fix it."},
    {"id": "fix_quality", "weight": 8, "description":
     "The change is minimal, targets the real defect rather than the symptom, preserves the documented "
     "invariants, and is backed by a green test run."},
    {"id": "policy_enforcement", "weight": 7, "description":
     "Applies the Zava engineering policy honestly: never approves a change with failing tests or a removed "
     "validation guard, and lists concrete required changes when blocking."},
    {"id": "handoff_integrity", "weight": 5, "description":
     "Each stage carries the previous stage's structured result forward, so triage, fix and compliance "
     "describe the same incident and the same change."},
    {"id": "operator_summary", "weight": 4, "description":
     "The final message tells an on-call engineer what broke, what changed, whether tests pass and whether "
     "it may ship - without reading the JSON."},
    {"id": "general_quality", "weight": 5, "always_applicable": True, "description":
     "Other important quality factors not covered by the listed criteria."},
]

rubric = project.beta.evaluators.create_version(
    name="zava_incident_rubric",
    evaluator_version={
        "name": "zava_incident_rubric",
        "categories": [EvaluatorCategory.AGENTS],
        "display_name": "Zava Incident Response Quality",
        "description": "Weighted quality criteria for the Zava multi-framework incident pipeline.",
        "definition": {
            "type": EvaluatorDefinitionType.RUBRIC,
            "dimensions": INCIDENT_RUBRIC_DIMENSIONS,
            "pass_threshold": 0.6,
        },
    },
)
print("rubric:", rubric.name, "v" + str(rubric.version))
''')

code(r'''
# Run it: a plain JSONL dataset evaluation (no target - the responses are already in the rows).
import time
from azure.ai.projects.models import TestingCriterionAzureAIEvaluator
from openai.types.eval_create_params import DataSourceConfigCustom
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam, SourceFileID,
)

def criterion(name, evaluator, mapping, init):
    return TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name=name, evaluator_name=evaluator,
        initialization_parameters=init, data_mapping=mapping,
    )

testing_criteria = [
    criterion("triage_match", "zava_triage_match", {}, {"deployment_name": JUDGE, "pass_threshold": 0.99}),
    criterion("fix_verified", "zava_fix_verified", {}, {"deployment_name": JUDGE, "pass_threshold": 1.0}),
    criterion("compliance_decision", "zava_compliance_decision", {},
              {"deployment_name": JUDGE, "pass_threshold": 0.99}),
    criterion("task_adherence", "builtin.task_adherence",
              {"query": "{{item.query}}", "response": "{{item.response}}"}, {"deployment_name": JUDGE}),
    criterion("coherence", "builtin.coherence",
              {"query": "{{item.query}}", "response": "{{item.response}}"}, {"deployment_name": JUDGE}),
    criterion("incident_rubric", rubric.name,
              {"query": "{{item.query}}", "response": "{{item.response}}"}, {"deployment_name": JUDGE}),
]

evaluation = oai.evals.create(
    name="Zava incident orchestration quality",
    data_source_config=DataSourceConfigCustom(
        type="custom",
        item_schema={"type": "object", "properties": ITEM_PROPERTIES, "required": ["query", "response"]},
    ),
    testing_criteria=testing_criteria,
)

eval_run = oai.evals.runs.create(
    eval_id=evaluation.id,
    name="incident-pipeline-outcomes",
    data_source=CreateEvalJSONLRunDataSourceParam(
        type="jsonl", source=SourceFileID(type="file_id", id=dataset.id),
    ),
)

while True:
    run = oai.evals.runs.retrieve(run_id=eval_run.id, eval_id=evaluation.id)
    if str(run.status) in ("completed", "failed", "canceled"):
        break
    time.sleep(10)

print(f"status={run.status}  rows: {run.result_counts.passed}/{run.result_counts.total} passed\n")
for c in run.per_testing_criteria_results:
    total = c.passed + c.failed
    print(f"  {c.testing_criteria:<22s} pass {c.passed:>2d}  fail {c.failed:>2d}   "
          f"{(c.passed / total if total else 0):.0%}")
print("\nFoundry portal:\n", run.report_url)
''')

md(r"""
### 💡 What to look for

`fix_verified` should read **75%** — three incidents ship a verified fix, and **ZAVA-INC-4822** does not: it
clamps the negative values but keeps floor division, so two tests stay red. Notice that
`compliance_decision` still passes on that row, because *needs-changes* was the correct verdict and it listed
concrete required changes. That is the pair you want in a pipeline evaluation: one criterion catching the
defect, another confirming the guardrail worked.

Everything is stored in the project — `run.report_url` opens the **Foundry portal**, and the same run shows up
in the web app's **Evaluations** tab.

Scripted equivalent:

```powershell
.\.venv\Scripts\python.exe agents/incident-orchestration/run_eval.py
.\.venv\Scripts\python.exe agents/incident-orchestration/run_eval.py --from-run   # score a live run too
```
""")

md(r"""
## 8️⃣ Host on Foundry

`build_incident_agent()` wraps the sequential workflow as a single MAF `WorkflowAgent`:

```python
from agent_framework import WorkflowAgent

WorkflowAgent(
    workflow=workflow,
    name=os.getenv("ORCHESTRATION_AGENT_NAME", "IncidentResponseOrchestrator"),
    description="Triage (LangGraph) -> Code Fix (GitHub Copilot SDK) -> Compliance (Foundry prompt agent).",
)
```

`main.py` serves it with:

```python
from agent_framework_foundry_hosting import ResponsesHostServer

agent = build_incident_agent()
app = ResponsesHostServer(agent=agent)
app.run()
```

Clients invoke the deployed endpoint through:

- `ORCHESTRATION_AGENT_NAME`
- `ORCHESTRATION_AGENT_ENDPOINT`

Foundry Hosted Agent deployment is attempted first. Azure Container Apps is the verified runtime fallback for
this preview because of the known hosted Responses tool-argument issue.
""")

md(r"""
For the verified runtime path, the repo builds `agents/incident-orchestration/Dockerfile`, pushes the image to
ACR, and deploys it to **Azure Container Apps**; the resulting `/responses` URL is stored as
`ORCHESTRATION_AGENT_ENDPOINT`. A Foundry Hosted Agent deploy is attempted with the same agent entrypoint,
but the hosted Responses runtime currently has the same known preview tool-argument issue described for
DeliverySupport. In headless container runtime, the **Code Fix (Copilot SDK)** step needs a GitHub token with
Copilot access; locally it uses your logged-in Copilot CLI user.
""")

code(r"""
# ---------------------------------------------------------------------------
# From "local workflow" to "hosted agent", in two real lines.
# ---------------------------------------------------------------------------
# WorkflowAgent  -> MAF class that dresses an entire `Workflow` in the SAME interface as a plain
#                   agent (`.run()` / `.run_stream()`). It is the piece that collapses three
#                   frameworks and three stages into ONE invocable object. The caller does not
#                   know (and need not know) that LangGraph, the Copilot SDK and a Foundry prompt
#                   agent live inside: it just sees an agent.
#
# ResponsesHostServer -> ASGI server from `agent-framework-foundry-hosting` that exposes any MAF
#                   agent over the Foundry **Responses** protocol (`POST /responses`, the same
#                   contract as Azure OpenAI). That is what makes the agent consumable by any
#                   Responses client — Foundry portal, SDK, curl — with no server code of your own.
from agent_framework import WorkflowAgent
from agent_framework_foundry_hosting import ResponsesHostServer

# In a hosted process there is no notebook reading the EventBus and no UI rendering the todos, so
# we pass fresh throwaway instances: the pipeline still works, the events simply have no
# subscriber. `build_incident_workflow` is the same function from §6.
orchestrator_agent = WorkflowAgent(
    workflow=build_incident_workflow(EventBus(), SharedTodoStore()),
    # `name` is the agent's identity in Foundry — deployment and traces reference it by this name.
    name=os.getenv("ORCHESTRATION_AGENT_NAME", "IncidentResponseOrchestrator"),
    description="Zava incident response: Triage (LangGraph) -> Code Fix (Copilot SDK) -> Compliance (Foundry).",
)

# Entrypoint of agents/incident-orchestration/main.py (served on 0.0.0.0:8088):
#
#   app = ResponsesHostServer(agent=orchestrator_agent)   # mounts POST /responses over the agent
#   app.run()                                             # starts the ASGI server and blocks
#
# We do not call `.run()` here because it would block the notebook kernel.
print("Hostable agent:", orchestrator_agent.name)
print("Type          :", type(orchestrator_agent).__name__, "-> exposes .run() like any MAF agent")
""")

code(r"""
# Guarded hosted invocation. Set ORCHESTRATION_AGENT_ENDPOINT to your deployed endpoint.
endpoint = os.environ.get("ORCHESTRATION_AGENT_ENDPOINT", "").rstrip("/")
if not endpoint:
    print("Set ORCHESTRATION_AGENT_ENDPOINT to invoke the hosted orchestration.")
else:
    import requests

    # The env var may or may not already carry the /responses path.
    url = endpoint if endpoint.endswith("/responses") else endpoint + "/responses"
    # Responses-shaped body: `input` is the user text. The server hands it to the WorkflowAgent,
    # which runs Triage -> Code Fix -> Compliance and returns the final text.
    # The long timeout is deliberate: the Copilot SDK stage runs real pytest in a sandbox.
    resp = requests.post(url, json={"input": incident_text}, timeout=300)

    # Container Apps ingress cuts the connection at ~240 s, so a slow pipeline returns 504 even
    # though the run continues server-side. In production use the async path: create the response
    # with `background=True` and poll `GET /responses/{id}`.
    if resp.status_code in (502, 503, 504):
        print(f"HTTP {resp.status_code}: ingress timed out before the pipeline finished.")
        print("The run continues server-side — follow it in the Foundry portal traces.")
    else:
        resp.raise_for_status()
        data = resp.json()
        print(data.get("output_text") or data)
""")

md(r"""
## 🔄 Recap & next steps

You saw how one Zava incident moves through a multi-framework agent team:

| Stage | Framework | MAF integration | Output |
|---|---|---|---|
| Triage | LangGraph | `LangGraphTriageClient(BaseChatClient)` | severity/category/component/route |
| Code Fix | GitHub Copilot SDK | `CopilotCodeFixClient(BaseChatClient)` + `GitHubCopilotAgent` | diff, tests, summary |
| Compliance | Foundry prompt agent | `FoundryComplianceClient(BaseChatClient)` | approved / needs-changes |

…and two harness capabilities that only exist **because** they share that uniform surface:

| Capability | Implementation | What you get |
|---|---|---|
| Todo provider | `TodoProvider` + a custom `SharedTodoStore` | one live remediation plan the three stages fill in together |
| OpenTelemetry | `configure_otel_providers()` in `setup_observability()` | one distributed GenAI trace spanning LangGraph + Copilot + Foundry |

Ideas to extend:

- add evaluations and continuous monitoring on the hosted workflow,
- add a fourth framework as another `BaseChatClient` adapter,
- persist the todo store (a `TodoFileStore`-style backend) so a plan survives a restart,
- stream the `EventBus` to richer telemetry.

Together with notebooks 01 and 02, this completes the Zava story: prompt agents, hosted MAF agents, and now
multi-framework orchestration on Foundry.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("Wrote", OUT, "with", len(cells), "cells")
