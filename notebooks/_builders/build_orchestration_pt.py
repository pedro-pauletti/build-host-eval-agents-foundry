"""Builder for notebooks/03_multi_agent_orchestration.pt-BR.ipynb (Portugues do Brasil).
Mesmo codigo do notebook em ingles; apenas a narrativa esta em PT-BR.
Run: .venv\\Scripts\\python.exe notebooks/_builders/build_orchestration_pt.py
"""
import os
import nbformat as nbf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "03_multi_agent_orchestration.pt-BR.ipynb")

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))
def code(t): cells.append(nbf.v4.new_code_cell(t.strip("\n")))

md(r"""
# 🧭 Zava · **Orquestração de agentes multi-framework** no Microsoft Foundry

> **Microsoft Agent Framework (MAF)** · triagem com **LangGraph** · harness de correção de código com **GitHub Copilot SDK** · conformidade com **Foundry prompt agent** · `SequentialBuilder` · `WorkflowAgent` · hospedagem no Foundry
>
> 🇺🇸 Uma versão em inglês está disponível em `03_multi_agent_orchestration.en.ipynb`.

O **serviço noturno de reposição** da Zava produziu **quantidades de reposição NEGATIVAS** para SKUs bem
abastecidos e arredondou déficits reais **para baixo**, ficando abaixo do nível-alvo. Este notebook percorre
a Demo #2: três agentes criados com frameworks diferentes cooperando por meio de um **MAF Agent Harness
comum**:

1. **Agente de Triagem** — **LangGraph** classifica severidade/categoria/componente e roteia o incidente.
2. **Agente de Correção de Código** — **GitHub Copilot SDK** executa um loop real planejar → executar
   shell/fs → avaliar → iterar em um sandbox isolado até o `pytest` passar.
3. **Agente de Conformidade** — **Foundry prompt agent** revisa a correção contra a política de engenharia
   da Zava.

Em seguida, o mesmo pipeline é encapsulado como um `WorkflowAgent` do MAF e hospedado via runtime Responses
do Foundry.
""")

md(r"""
## 🏗️ Arquitetura

```mermaid
flowchart LR
  I[JSON do incidente<br/>quantidades de reposição negativas] --> H[MAF Agent Harness comum<br/>adaptadores BaseChatClient + EventBus]
  H --> T[Agente de Triagem<br/>LangGraph StateGraph]
  T --> C[Agente de Correção de Código<br/>harness do GitHub Copilot SDK]
  C --> P[Agente de Conformidade<br/>Foundry prompt agent]
  P --> R[Aprovado / requer alterações<br/>JSON estruturado]

  subgraph ORCH[Orquestração MAF]
    T -->|handoff em JSON demarcado| C -->|handoff em JSON demarcado| P
  end

  ORCH --> W[WorkflowAgent]
  W --> F[Foundry ResponsesHostServer<br/>Hosted Agent / fallback em ACA]
```

**Duas ideias do lado do cliente.**
- **Orquestração MAF:** `SequentialBuilder` conduz um pipeline determinístico, enquanto uma superfície
  uniforme de chat-client oculta se uma etapa é LangGraph, Copilot SDK ou um Foundry prompt agent.
- **Loop de agent harness com GitHub Copilot SDK:** o agente de Correção de Código planeja, executa
  ferramentas de shell/sistema de arquivos, avalia com `pytest` e itera até o sandbox ficar verde.

**Ideia Foundry do lado do servidor.** Todo o workflow pode ser hospedado como um agente Foundry: runtime
isolado, sessões com estado, cold starts sub-segundo, observabilidade e avaliações. Este repo tenta o deploy
como Foundry Hosted Agent e usa Azure Container Apps como fallback verificado porque o runtime Responses
hospedado atualmente tem um problema conhecido de preview com argumentos de ferramentas (mesmo padrão do
agente DeliverySupport).
""")

md(r"""
## ✅ Setup

Use o ambiente virtual do repo como kernel Jupyter (`.venv`). Os módulos ao vivo carregam o `.env` da raiz
do repo e esperam autenticação Azure / Copilot:

- Azure: `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_ACCOUNT_ENDPOINT`, nomes de deployments de modelo e
  `az login` / `DefaultAzureCredential`.
- GitHub Copilot SDK: pacote **`github-copilot-sdk`**, nome de import **`copilot`**.
- Provedor MAF: pacote **`agent-framework-github-copilot`**, expondo
  `agent_framework_github_copilot.GitHubCopilotAgent`, um `BaseAgent` nativo do MAF.
- Auth do Copilot: `use_logged_in_user=True` usa o usuário logado no GitHub Copilot CLI;
  `github_token=...` funciona para containers headless.

Pacotes usados por esta demo incluem:

```powershell
.\.venv\Scripts\pip.exe install langgraph github-copilot-sdk agent-framework `
  agent-framework-github-copilot agent-framework-orchestrations `
  agent-framework-foundry-hosting azure-ai-projects
```

> ⚠️ Células que chamam Azure ou GitHub Copilot precisam de autenticação e podem levar **1–2 minutos**.
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
# Preflight de autenticação Entra.
#
# `shared_credential()` devolve UM `DefaultAzureCredential` por processo, com `process_timeout=30`.
# Isso importa: uma credencial nova por chamada dispara `az account get-access-token` como subprocesso
# toda vez, e o timeout padrão de 10 s estoura com o kernel ocupado -> o erro
# `AzureCliCredential: Failed to invoke the Azure CLI`. Uma instância única mantém o token em memória.
#
# Pedimos o token aqui, no início, para que uma sessão `az login` expirada falhe nesta célula em vez de
# no meio de uma execução de dois minutos do pipeline.
from harness import COGNITIVE_SCOPE, shared_credential

try:
    token = shared_credential().get_token(COGNITIVE_SCOPE)
    print("Entra OK · token expira em:", __import__("datetime").datetime.fromtimestamp(token.expires_on))
except Exception as exc:
    print("AUTENTICAÇÃO FALHOU — rode `az login` (e `az account set -s <subscription>`) e reexecute.")
    print(" ", type(exc).__name__, str(exc)[:300])
""")

code(r"""
# Smoke check de auth do Copilot SDK. Ainda não roda o harness de correção.
#
# O SDK é async e o client precisa estar *conectado* antes de responder: `async with` sobe o
# processo do Copilot CLI por baixo e o encerra ao sair. Chamar `get_auth_status()` sem isso
# levanta `RuntimeError: Client not connected`.
from copilot import CopilotClient

async with CopilotClient(log_level="error", use_logged_in_user=True) as probe:
    print(await probe.get_auth_status())

# No harness de verdade:
# - auth interativa local: CopilotClient(working_directory=sandbox, use_logged_in_user=True)
# - auth headless/container: CopilotClient(working_directory=sandbox, github_token=os.environ["GITHUB_TOKEN"])
""")

md(r"""
## 1️⃣ O incidente + o sandbox

A fonte da verdade é `agents/incident-orchestration/sandbox_seed/`:

- `incident.json` descreve **ZAVA-INC-4821**.
- `reorder.py` contém o defeito semeado.
- `test_reorder.py` captura as regras de negócio esperadas.

O agente de Correção de Código nunca edita o repo. `code_fix_copilot.py` cria uma **cópia nova do sandbox**
para cada execução, depois executa ferramentas e `pytest` dentro desse diretório isolado.
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
## 2️⃣ Agente 1 — Triagem (**LangGraph**)

O agente de Triagem é um `StateGraph` compacto do LangGraph:

```mermaid
flowchart LR
  START((START)) --> classify[classify<br/>Azure OpenAI + token Entra<br/>JSON ESTRITO]
  classify --> route[route<br/>regra determinística]
  route --> END((END))
```

**Sintaxe do LangGraph:** o estado é um `TypedDict`; cada **nó** é uma função comum `estado -> estado
parcial`; `add_edge` liga os nós entre os sentinelas `START` e `END`; `compile()` devolve um grafo executável
que você invoca com um dict. Abaixo está a implementação real — o mesmo código de `src/triage_langgraph.py`.
""")

code(r'''
# Implementação real — mesmo código de agents/incident-orchestration/src/triage_langgraph.py
import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph      # <- LangGraph
from harness import CODE_FIX, build_azure_openai_client, triage_model


class TriageState(TypedDict, total=False):
    """O estado do grafo: cada nó o lê e devolve uma atualização parcial."""
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
    """Nó LangGraph: classificação do incidente em campos estruturados via LLM."""
    client = build_azure_openai_client()               # AzureOpenAI + token Entra, keyless
    completion = client.chat.completions.create(
        model=triage_model(),                          # deployment model-router
        temperature=0,
        response_format={"type": "json_object"},       # modo JSON -> estado parsável
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
    """Nó LangGraph: decisão de roteamento determinística (auditável)."""
    category = state.get("category", "")
    component = (state.get("component", "") or "").lower()
    is_code_defect = category in {"bug", "data-quality", "performance"} or component.endswith(".py")
    return {"route": CODE_FIX if is_code_defect else CODE_FIX}


def build_triage_graph() -> Any:
    """Compila o state graph `classify -> route` do LangGraph."""
    graph = StateGraph(TriageState)
    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "route")
    graph.add_edge("route", END)
    return graph.compile()


triage_graph = build_triage_graph()
print("grafo compilado:", type(triage_graph).__name__)
''')

code(r"""
# Executa o grafo LangGraph sozinho (ainda sem MAF) — precisa de .env + az login. Segundos.
raw_state = triage_graph.invoke({"incident": incident_text})
print(json.dumps(raw_state, indent=2))
""")

md(r"""
### Fazendo o agente LangGraph parecer um agente MAF

O MAF nunca enxerga o LangGraph. Ele enxerga um `BaseChatClient` cujo `_produce()` por acaso invoca um
grafo. O adaptador também emite eventos do harness e escreve o plano de remediação compartilhado usando as
ferramentas de todo que o MAF colocou em `options`. `Agent(client=adapter, ...)` então o transforma em um
agente MAF comum.
""")

code(r'''
# Implementação real — o adaptador MAF de src/triage_langgraph.py
import asyncio

from agent_framework import Agent, BaseChatClient
from harness import (
    TRIAGE, EventBus, HarnessChatClient, HarnessTodos, TriageResult,
    build_todo_provider, fenced_json, last_user_text,
)


class LangGraphTriageClient(HarnessChatClient, BaseChatClient):
    """Adaptador MAF que executa o grafo de triagem do LangGraph.

    Herança dupla, de propósito:
      * `BaseChatClient`   — contrato do MAF: é o que faz o `Agent` aceitar este objeto como client.
      * `HarnessChatClient` — nossa base (§5): implementa `_inner_get_response` uma única vez e
        delega para o `_produce()` abaixo, para que os três adaptadores tenham a mesma forma.

    Ou seja: subclassificar isto é tudo o que é preciso para plugar um framework novo no pipeline.
    """

    # Identidade nos eventos do bus — é assim que a UI sabe qual etapa emitiu cada passo.
    agent_id = TRIAGE

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    async def _produce(self, messages: Any, options: Any) -> str:
        """O único método que um adaptador precisa: transcrição entra, texto da etapa sai.

        `messages` é a conversa acumulada do workflow; `options` é o **dict** que o MAF passa,
        e é de onde tiramos as ferramentas de todo (ver §5.1).
        """
        # `last_user_text` pula a checklist injetada pelo TodoProvider e devolve o incidente.
        incident = last_user_text(messages)
        await self._emit("agent_started", note="Classifying & routing the incident with LangGraph")

        # O LangGraph é síncrono: `to_thread` evita bloquear o event loop do MAF.
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

        # A Triagem é dona do plano: ela escreve a checklist que as etapas seguintes vão executar.
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
    """Devolve a etapa de Triagem como um agente MAF."""
    return Agent(
        client=LangGraphTriageClient(bus=bus),
        name="Triage",
        description="Classifies and routes a Zava engineering incident (LangGraph).",
        instructions="You are the Zava incident Triage agent.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


print("adaptador pronto:", LangGraphTriageClient.__name__)
''')

code(r"""
# Agora execute como agente MAF. Chamada Azure: precisa de .env + az login.
bus = EventBus()
triage_agent = create_triage_agent(bus)
triage_response = await triage_agent.run(incident_text)

print(triage_response.text)
print("\nEvents:")
for event in bus.events:
    print(event.to_dict())
""")

md(r"""
## 3️⃣ Agente 2 — Correção de Código (**GitHub Copilot SDK**)

O agente de Correção de Código é a etapa de "trabalho real":

1. Copia `sandbox_seed/` para um sandbox novo.
2. Inicia `GitHubCopilotAgent` com um `CopilotClient` apontado para esse sandbox.
3. Deixa o harness do Copilot SDK planejar, ler arquivos, editar `reorder.py`, executar comandos shell e
   avaliar com `pytest -q`.
4. Usa `on_pre_tool_use` para **autoaprovar** cada chamada de ferramenta limitada ao sandbox e emitir eventos
   `harness_step` ao vivo rotulados como Plan / Execute / Assess.
5. Captura o diff final, a saída dos testes e o handoff estruturado `{"code_fix": ...}`.

Modelos disponíveis para esse provedor incluem `claude-sonnet-4.5`, `gpt-5.4` e outros modelos Copilot
expostos no ambiente.
""")

code(r'''
# Implementação real — mesmo código de agents/incident-orchestration/src/code_fix_copilot.py
import difflib, json, shutil, subprocess, sys, tempfile
from pathlib import Path

from agent_framework_github_copilot import GitHubCopilotAgent   # provider MAF para o Copilot SDK
from copilot import CopilotClient                               # o próprio GitHub Copilot SDK
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
    """Cópia temporária nova da sandbox semeada — o repo nunca fica gravável."""
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
    """Rótulo curto para um passo do harness (toolArgs chega como string JSON ou dict)."""
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
    """planejar -> executar (shell/fs) -> avaliar (pytest) -> iterar, dentro de uma sandbox."""
    sandbox = make_sandbox()
    original = (sandbox / "reorder.py").read_text(encoding="utf-8")
    pytest_runs = 0

    async def on_pre_tool_use(hook_input: Any, _ctx: Any) -> dict:
        """Hook do Copilot SDK: dispara antes de cada chamada de ferramenta do harness."""
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
        return {"permissionDecision": "allow"}      # auto-aprova: seguro *porque* é uma sandbox

    gh_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    auth = {"github_token": gh_token} if gh_token else {"use_logged_in_user": True}
    client = CopilotClient(working_directory=str(sandbox), log_level="error", **auth)

    async with GitHubCopilotAgent(
        name="CodeFix",
        client=client,
        default_options={
            "model": CODE_FIX_MODEL,
            "timeout": CODE_FIX_TIMEOUT,
            "on_pre_tool_use": on_pre_tool_use,     # <- onde o harness observa/aprova as ferramentas
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


print("seed da sandbox:", SANDBOX_SEED, "| modelo:", CODE_FIX_MODEL)
''')

code(r"""
# Execução real do Copilot SDK: precisa de auth do GitHub Copilot. Duração esperada: ~1–2 minutos.
bus = EventBus()
fix = await run_copilot_code_fix(bus)

print("LINHA DO TEMPO DO HARNESS")
for event in bus.events:
    print(f"  {event.data.get('step', ''):8s} {event.data.get('detail', '')}")

print("\ntestes passaram:", fix["test_passed"], "| iterações:", fix["iterations"])
print("\nDIFF\n" + fix["diff"])
print("\nRESUMO\n" + fix["summary"][:1500])
""")

md(r"""
### Fazendo o harness do Copilot parecer um agente MAF

Mesmo padrão de adaptador da Triagem: um `BaseChatClient` cujo `_produce()` conduz o loop do Copilot, lê o
bloco `{"triage": ...}` que veio antes na conversa e anexa o seu próprio bloco `{"code_fix": ...}`.
""")

code(r'''
# Implementação real — o adaptador MAF de src/code_fix_copilot.py
from harness import CodeFixResult, extract_last_json


class CopilotCodeFixClient(HarnessChatClient, BaseChatClient):
    """Adaptador MAF que roda o harness do GitHub Copilot SDK em uma sandbox."""

    agent_id = CODE_FIX

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    async def _produce(self, messages: Any, options: Any) -> str:
        triage = extract_last_json(messages, must_have="triage") or {}
        triage_info = triage.get("triage", triage)

        await self._emit("agent_started", note="Running the GitHub Copilot SDK harness on an isolated sandbox",
                         model=CODE_FIX_MODEL)
        outcome = await run_copilot_code_fix(self._bus)          # <- o loop do harness definido acima
        result = CodeFixResult(**outcome)
        await self._emit("agent_completed", result=result.to_dict())

        # Marca o plano que a Triagem escreveu — apenas a partir de sinais *reais* desta execução.
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
    """Devolve a etapa de Correção de Código como um agente MAF."""
    return Agent(
        client=CopilotCodeFixClient(bus=bus),
        name="CodeFix",
        description="Fixes the defect in an isolated sandbox using the GitHub Copilot SDK harness.",
        instructions="You are the Zava incident Code Fix agent.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


print("adaptador pronto:", CopilotCodeFixClient.__name__)
''')

md(r"""
## 4️⃣ Agente 3 — Conformidade (**Foundry prompt agent**)

O agente de Conformidade é registrado no Foundry por `create_compliance_agent.py`. Seu prompt incorpora
`data/company/zava-engineering-policy.md` e exige uma decisão em JSON estrito:

```json
{
  "decision": "approved | needs-changes",
  "checks": [{"id": "C1", "status": "pass | fail | n/a"}],
  "rationale": "short justification",
  "required_changes": []
}
```

`FoundryComplianceClient` o invoca pela Responses API com
`extra_body={"agent_reference": {"type": "agent_reference", "name": "ComplianceReviewer"}}`. Se o prompt
agent estiver indisponível, o módulo tem um fallback direto de modelo fundamentado na política para que o
pipeline ainda seja concluído.
""")

code(r'''
# Implementação real — mesmo código de agents/incident-orchestration/create_compliance_agent.py
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition     # <- definição de prompt agent do Foundry
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

# Prompt agents vivem *no serviço*: modelo + instruções (+ tools opcionais), versionados pelo Foundry.
compliance_version = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(model=COMPLIANCE_MODEL, instructions=INSTRUCTIONS),
)
print("registrado:", compliance_version.name, "versão", getattr(compliance_version, "version", "?"))
print("modelo    :", COMPLIANCE_MODEL, "| caracteres de política:", len(POLICY))
''')

md(r"""
O prompt agent é invocado pela **Responses API**: você chama o endpoint do *modelo* e aponta para o agente
registrado com `extra_body={"agent_reference": ...}`. Nenhum objeto de agente do SDK é instanciado
localmente — as instruções vivem no Foundry.
""")

code(r'''
# Chamada crua ao prompt agent do Foundry (ainda sem MAF).
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
### Fazendo o prompt agent do Foundry parecer um agente MAF

Terceiro adaptador, mesmo formato. Ele faz o parse da decisão em JSON estrito e — diferente das outras duas
etapas — pode **fazer o plano crescer**: um veredito *needs-changes* acrescenta os `required_changes` como
novos itens de todo.
""")

code(r'''
# Implementação real — o adaptador MAF de src/compliance_foundry.py
from harness import COMPLIANCE, ComplianceResult, extract_json


def normalize_decision(raw: Any) -> str:
    """Fail closed: o que não for claramente uma aprovação vira `needs-changes`."""
    value = str(raw or "").strip().lower().replace("_", "-")
    return "approved" if value in {"approve", "approved", "pass", "passed", "ok"} else "needs-changes"


class FoundryComplianceClient(HarnessChatClient, BaseChatClient):
    """Adaptador MAF que chama o prompt agent ComplianceReviewer do Foundry."""

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

        # A Conformidade fecha o plano OU o faz CRESCER com as mudanças que exige.
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
    """Devolve a etapa de Conformidade como um agente MAF."""
    return Agent(
        client=FoundryComplianceClient(bus=bus),
        name="Compliance",
        description="Reviews the fix against Zava engineering policy (Foundry prompt agent).",
        instructions="You are ComplianceReviewer for Zava.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


print("adaptador pronto:", FoundryComplianceClient.__name__)
''')

code(r"""
# Roda a etapa de conformidade como agente MAF sobre a correção produzida acima.
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
## 5️⃣ O **MAF Agent Harness** comum

Este é o principal padrão de integração. Cada framework heterogêneo é encapsulado como uma subclasse
`BaseChatClient` do MAF que implementa `_inner_get_response(self, *, messages, stream, options, **kwargs)`:

- sem streaming, retorna `ChatResponse(messages=[Message(role="assistant", contents=[text])])`
- com streaming, retorna `self._build_response_stream(async_gen_of_ChatResponseUpdate)`

Então `Agent(client=adapter, name=..., instructions=...)` faz cada framework parecer um agente MAF comum.
**Essa superfície uniforme de ChatClient é o Agent Harness comum.**

O mesmo harness também possui o `EventBus`, um pub/sub assíncrono pequeno que emite `agent_started`,
`harness_step`, `agent_completed` e `run_completed`. O notebook e os testes leem o mesmo stream.
""")

code(r'''
# Implementação real — o adaptador base + event bus de src/harness.py
import time
from dataclasses import dataclass, field
from typing import Any

@dataclass
class HarnessEvent:
    """Um fato observável do pipeline. `type` é a categoria (`harness_step`, `agent_completed`…),
    `agent` diz qual etapa o emitiu e `data` carrega o payload livre que a UI renderiza."""
    type: str
    agent: str
    ts: float
    data: dict[str, Any] = field(default_factory=dict)

class HarnessChatClient:
    """A base compartilhada pelos três adaptadores — *isto* é o Agent Harness comum.

    Ela traduz o contrato do MAF (`_inner_get_response`) para um único método simples de
    implementar (`_produce`), e adiciona emissão de eventos. Um framework novo entra no pipeline
    subclassificando isto — nada mais no MAF precisa mudar.
    """

    agent_id: str = "orchestrator"
    _bus = None

    async def _emit(self, type: str, **data: Any) -> None:
        """Publica um evento marcado com esta etapa. Sem bus, vira no-op."""
        if self._bus is not None:
            await self._bus.emit(type, self.agent_id, **data)

    async def _produce(self, messages, options) -> str:
        """Implementado por cada adaptador: roda o framework nativo e devolve o texto da etapa."""
        raise NotImplementedError

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        """O método que o MAF realmente chama. Assinatura fixa — keyword-only, com `stream`."""
        from agent_framework import ChatResponse, Message
        text = await self._produce(messages, options)
        if stream:
            # No caminho de streaming o MAF espera um stream de ChatResponseUpdate, não uma resposta.
            return self._build_response_stream(self._as_updates(text))
        return ChatResponse(
            messages=[Message(role="assistant", contents=[text])],
            response_id=f"{self.agent_id}-{int(time.time() * 1000)}",
        )

print("The real EventBus retains events and broadcasts them to async subscribers.")
''')

md(r"""
### O que é de fato um "harness" — e o que o nosso oferece

A doc da Microsoft sobre [Agent Harnesses](https://learn.microsoft.com/agent-framework/agents/harness)
define harness como **o scaffolding de runtime em volta de um modelo**: o loop que invoca ferramentas,
persiste histórico, compacta contexto, controla tarefas e aplica aprovações. O MAF traz uma *fábrica de
harness* (`create_harness_agent`) que monta essas peças para você; aqui construímos o scaffolding **à
mão**, porque nosso requisito é outro — não estamos envolvendo *um* modelo, estamos tornando **três
frameworks intercambiáveis**.

Na prática, nosso harness fixa estes **parâmetros** para que todo agente se comporte igual:

| Parâmetro | Valor | Por que importa |
|---|---|---|
| Orquestração | `SequentialBuilder` | Triage → Code Fix → Compliance determinístico sobre uma conversa compartilhada. |
| Superfície uniforme | `agent_framework.BaseChatClient` ×3 | Cada framework vira um chat client MAF comum — *essa camada de adapters é o harness*. |
| Formato de hand-off | JSON em bloco | Cada etapa anexa um bloco ` ```json `; a etapa seguinte pega seu objeto com `extract_last_json()`. |
| Event bus | pub/sub assíncrono | Um único stream alimenta o trace do notebook e os testes. |
| Aprovação de ferramentas | auto-aprovar (sandbox) | `on_pre_tool_use` retorna `permissionDecision=allow` — seguro *porque* o harness só toca uma cópia temporária. |
| Limite do loop | `CODE_FIX_TIMEOUT` (300 s) | Limita o loop plan → execute → assess do Copilot; o `pytest` passar é a condição de término. |
| Isolamento | sandbox temporária | `sandbox_seed/` é copiado a cada execução; o repositório real nunca é gravável. |
| Empacotado como | `WorkflowAgent` | Todo o workflow é exposto como um *único* agente e servido pelo `ResponsesHostServer`. |
| Todo provider | `SharedTodoStore` | Um único `TodoProvider` do MAF compartilhado pelas três etapas — um plano de remediação só, não três listas privadas. |
| Observabilidade | `configure_otel_providers()` | O MAF é instrumentado uma vez, então os três frameworks emitem **um** trace GenAI para o Application Insights. |

E estas são as **capacidades de harness** da doc, mapeadas honestamente nesta demo:

| Capacidade | Aqui | Nota |
|---|---|---|
| Invocação de funções | ✅ ativa | Cada adapter roda o loop de ferramentas do seu próprio framework. |
| Aprovação de ferramentas | ✅ ativa | Auto-aprovação, restrita à sandbox. |
| Loop até concluir | ✅ ativa | O Code Fix itera até os testes passarem ou o timeout estourar. |
| Ambiente de shell | ✅ ativa | O Copilot SDK recebe read/edit/shell dentro do diretório temporário. |
| **Todo provider** | ✅ ativa | O Triage escreve o plano, o Code Fix marca os itens, o Compliance verifica — §5.1 abaixo. |
| **OpenTelemetry** | ✅ ativa | `setup_observability()` exporta um trace distribuído único — §5.2 abaixo. |
| Persistência de histórico · compactação | ⚪ disponível | Desnecessário: três etapas limitadas em uma só conversa. |
| Agent mode · web search | ⛔ fábrica de harness | Vêm do `create_harness_agent`, não de adapters feitos à mão. |
""")

md(r"""
### 5️⃣.1 Capacidade do harness — o **todo provider** (um plano compartilhado)

O MAF traz um `TodoProvider` de verdade: um `ContextProvider` que injeta instruções de todo, cinco
ferramentas (`todos_add`, `todos_complete`, `todos_remove`, `todos_get_remaining`, `todos_get_all`) e a
checklist atual em cada turno. É exatamente a capacidade de "task tracking" da documentação de harness.

Há um detalhe que faz toda a diferença aqui. O `TodoSessionStore` padrão guarda os itens no
`AgentSession.state` — ou seja, **cada agente teria a sua própria lista**. Queremos o oposto: um plano de
remediação que o Triage escreve, o Code Fix executa e o Compliance verifica. Trocar o store é o ponto de
extensão documentado, então implementamos um store minúsculo que ignora a sessão:

```python
class SharedTodoStore:                      # faz duck-typing de agent_framework.TodoStore
    def __init__(self, bus=None):
        self.items, self.next_id, self._bus = [], 1, bus

    async def load_state(self, session, *, source_id):
        return list(self.items), self.next_id                 # a mesma lista para toda etapa

    async def load_items(self, session, *, source_id):
        return list(self.items)

    async def save_state(self, session, items, *, next_id, source_id):
        self.items, self.next_id = list(items), next_id
        if self._bus:                                          # republica para a UI animar
            await self._bus.emit("todo_updated", ORCHESTRATOR, todos=self.snapshot())
```

Aí os três agentes recebem um provider ligado ao **mesmo** store:

```python
store = SharedTodoStore(bus)
triage     = create_triage_agent(bus, store)
code_fix   = create_code_fix_agent(bus, store)
compliance = create_compliance_agent(bus, store)
# cada factory faz: context_providers=[TodoProvider(instructions=..., store=store)]
```

**Quem chama as ferramentas?** Num agente normal é o *modelo* que decide chamar `todos_add`. Nossos
adapters embrulham frameworks que devolvem resultados estruturados, então é o **harness** que as chama em
nome da etapa — mesmo provider, mesmo store, mesmo plano. O MAF entrega as ferramentas ao adapter em
`options`, que é um **dict** simples (detalhe importante — `getattr(options, "tools")` devolve nada
silenciosamente):

```python
class HarnessTodos:
    def __init__(self, options):
        tools = (options or {}).get("tools") or [] if isinstance(options, dict) else []
        self._tools = {t.name: t for t in tools}

    async def add(self, *titles):
        await self._tools["todos_add"].invoke(arguments={"todos": [{"title": t} for t in titles]})

    async def complete(self, *pairs):       # atenção: `items=`, não `completions=`
        await self._tools["todos_complete"].invoke(
            arguments={"items": [{"id": i, "reason": r} for i, r in pairs]})
```

Cada etapa então movimenta o plano **apenas a partir de sinais reais** — nunca de um palpite:

| Etapa | O que faz com o plano | Sinal |
|---|---|---|
| Triage | adiciona 4 itens (reproduzir · corrigir · rodar testes · revisão de política) | a própria classificação |
| Code Fix | conclui *reproduzir* / *corrigir* / *rodar testes* | `pytest_runs`, `files_changed`, `test_passed` |
| Compliance | conclui a *revisão*, **ou acrescenta** os `required_changes` que exigir | a sua decisão |

Essa última linha é a mais interessante: quando o Compliance responde *needs-changes*, o plano **cresce** —
o harness te entrega uma checklist de remediação viva e auditável em vez de um paredão de JSON.

> Mais uma sutileza: o `TodoProvider` injeta a checklist como uma mensagem de **usuário** começando com
> `### Current todo list`. Nosso `last_user_text()` ignora mensagens com esse marcador, então cada etapa
> continua lendo o texto do incidente em vez da checklist.
""")

md(r"""
### 5️⃣.2 Capacidade do harness — **OpenTelemetry** através de três frameworks

É aqui que um harness uniforme realmente compensa. Como LangGraph, Copilot SDK e o prompt agent do Foundry
chegam ao MAF por adapters `BaseChatClient`, **instrumentar o MAF instrumenta os três de forma idêntica** —
um trace distribuído, convenções semânticas GenAI, zero exporters por framework.

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

Pontos que vale memorizar:

* No `agent_framework` 1.12 o ponto de entrada é **`configure_otel_providers()`** (mais
  `enable_instrumentation()` se você configurar os providers por conta própria) — não existe
  `setup_observability` no pacote; a função acima é *nossa*.
* Precisa rodar **uma vez por processo**, então a implementação real protege com um flag de módulo e nunca
  levanta exceção: sem App Insights, o pipeline simplesmente roda sem trace.
* `enable_sensitive_data` controla se prompts/respostas vão anexados aos spans. Vem **desligado** e fica
  atrás de `OTEL_SENSITIVE_DATA` — deixe desligado fora de um tenant de demo.
* Você precisa do `azure-monitor-opentelemetry-exporter` (as três classes `AzureMonitor*Exporter`), e não
  da distro `azure-monitor-opentelemetry`.

Rode o pipeline e depois abra **Tracing** no portal do Foundry (ou App Insights → *Transaction search*):
você verá um único trace cujos filhos são as três etapas — LangGraph, Copilot e Foundry lado a lado.
""")

md(r"""
## 6️⃣ Orquestre com MAF

`orchestration.py` conecta os três agentes em uma sequência determinística — e entrega a todos o
**mesmo** event bus e o **mesmo** todo store, que é o que transforma três adapters em um harness:

```python
from agent_framework_orchestrations import SequentialBuilder

setup_observability()                     # um trace OTel único através dos três frameworks
bus, store = EventBus(), SharedTodoStore(bus)

workflow = SequentialBuilder(participants=[
    create_triage_agent(bus, store),
    create_code_fix_agent(bus, store),
    create_compliance_agent(bus, store),
]).build()
result = await workflow.run(incident_text)
```

Cada etapa escreve um bloco JSON demarcado (por exemplo `{"triage": {...}}`, `{"code_fix": {...}}`,
`{"compliance": {...}}`) mais um resumo legível por humanos. As etapas seguintes varrem a conversa
acumulada em busca do bloco relevante mais recente, então o handoff é estruturado e auditável.
""")

md(r"""
```mermaid
sequenceDiagram
  participant Ops as Incidente Ops
  participant MAF as MAF SequentialBuilder
  participant T as Triagem<br/>LangGraph
  participant C as Correção de Código<br/>Copilot SDK
  participant P as Conformidade<br/>Foundry prompt agent
  participant Todo as SharedTodoStore
  participant Bus as EventBus

  Ops->>MAF: texto do incidente
  MAF->>T: executar
  T-->>Bus: agent_started, classify, route, completed
  T->>Todo: todos_add x4 (plano de remediação)
  Todo-->>Bus: todo_updated
  T-->>MAF: ```json {"triage": ...}
  MAF->>C: transcrição com JSON de triagem
  C-->>Bus: eventos harness_step de Planejar / Executar / Avaliar
  C->>Todo: todos_complete (reproduzir, corrigir, rodar testes)
  Todo-->>Bus: todo_updated
  C-->>MAF: ```json {"code_fix": ...}
  MAF->>P: transcrição com JSON de code_fix
  P-->>Bus: policy-review, completed
  P->>Todo: conclui a revisão OU adiciona required_changes
  Todo-->>Bus: todo_updated
  P-->>MAF: ```json {"compliance": ...}
  MAF-->>Bus: run_completed (+ plano final)
```
""")

md(r"""
`build_incident_workflow()` em `src/orchestration.py` é exatamente a função abaixo: cria os três agentes de
cada framework, passa a eles o **mesmo** `EventBus` e o **mesmo** todo store, e constrói um workflow
sequencial do MAF. Aqui construímos a partir dos adaptadores definidos neste notebook.
""")

code(r'''
# Implementação real — mesmo código de agents/incident-orchestration/src/orchestration.py
from agent_framework_orchestrations import SequentialBuilder    # <- orquestração do MAF
from harness import ORCHESTRATOR, SharedTodoStore, setup_observability


def build_incident_workflow(bus: EventBus | None = None, todo_store: Any = None) -> Any:
    """Triagem (LangGraph) -> Correção de Código (Copilot SDK) -> Conformidade (prompt agent Foundry).

    `bus` e `todo_store` são passados aos TRÊS agentes de propósito: é compartilhar essas duas
    instâncias que transforma três adaptadores independentes em um harness único — um stream de
    eventos e um plano de remediação, em vez de três privados.
    """
    triage = create_triage_agent(bus, todo_store)
    code_fix = create_code_fix_agent(bus, todo_store)
    compliance = create_compliance_agent(bus, todo_store)
    # SequentialBuilder: executa os participantes em ordem sobre UMA conversa acumulada — a saída
    # de cada etapa é anexada à transcrição que a próxima recebe. Nada de roteamento por LLM aqui:
    # a ordem é determinística e auditável, que é o que se quer em resposta a incidentes.
    return SequentialBuilder(participants=[triage, code_fix, compliance]).build()


print("OpenTelemetry configurado:", setup_observability())   # um trace único nos três frameworks

bus = EventBus()
todo_store = SharedTodoStore(bus)          # um store para a execução INTEIRA -> um plano só (ver 5.1)
workflow = build_incident_workflow(bus, todo_store)
print("workflow sequencial construído:", type(workflow).__name__)
''')

code(r'''
# Execução ponta a ponta: precisa de auth Azure + Copilot. Duração esperada: ~1–2 minutos.
# Este é o corpo de `run_incident()` em src/orchestration.py.
await bus.emit("run_started", ORCHESTRATOR, incident=incident_text)
workflow_result = await workflow.run(incident_text)        # <- o MAF conduz as três etapas

outputs = workflow_result.get_outputs()
flat = [m for item in outputs for m in (item if isinstance(item, list) else [item])]
final_text = next((m.text for m in reversed(flat) if getattr(m, "text", None)), "")

def last_result(agent_id: str):
    for event in reversed(bus.events):
        if event.agent == agent_id and event.type == "agent_completed":
            return event.data.get("result")
    return None

print("LINHA DO TEMPO DE EVENTOS")
for event in bus.events:
    data = event.to_dict()
    detail = data.get("detail") or data.get("note") or data.get("decision") or ""
    print(f"{event.agent:12s} {event.type:16s} {detail}")

print("\nPLANO DE REMEDIACAO COMPARTILHADO (todo provider do MAF)")
for item in todo_store.snapshot():
    print(f"  [{'x' if item['done'] else ' '}] {item['title']}")

print("\nDECISAO FINAL")
print("testes passaram:", (last_result(CODE_FIX) or {}).get("test_passed"))
print("conformidade   :", (last_result(COMPLIANCE) or {}).get("decision"))
print("\nTexto final:")
print(final_text[:2000])
''')

md(r"""
> `orchestration.run_incident(incident_text, bus=bus)` empacota exatamente a célula acima (mais
> `bus.close()` e um dataclass `OrchestrationResult`), e é o que o serviço implantado chama.
""")

md(r"""
## 7️⃣ Avaliando o pipeline

Um pipeline multi-agente não é pontuado como um chatbot. A saída dele é **estruturada** — a Triagem emite
`{"triage": ...}`, a Correção de Código emite `{"code_fix": ...}`, a Conformidade emite `{"compliance": ...}`
— e as perguntas que importam têm resposta exata: *a severidade estava certa? os testes ficaram verdes de
verdade? o revisor de política falhou de forma segura?*

Isso torna os **avaliadores custom code-based** a medida principal aqui, não um juiz LLM:

| Avaliador | Tipo | O que verifica |
|---|---|---|
| `zava_triage_match` | **custom, código** | severidade / categoria / componente versus a classificação esperada |
| `zava_fix_verified` | **custom, código** | um arquivo realmente mudou **e** a suíte ficou verde (diff não vazio) |
| `zava_compliance_decision` | **custom, código** | o veredito bate com o esperado **e** nunca aprova testes vermelhos |
| `builtin.task_adherence` | built-in | a execução seguiu o pipeline que foi definido |
| `builtin.coherence` | built-in | o resumo final para o operador se sustenta |
| `zava_incident_rubric` | **rubric** | qualidade ponta a ponta da resposta a incidentes, ponderada |

A fonte de dados é um **dataset** de transcrições completas do pipeline
(`agents/incident-orchestration/evals/incident_eval.jsonl`) — quatro incidentes, sendo que um deles entrega
de propósito uma correção com testes falhando, para você ver o `zava_fix_verified` pegando. Reexecutar o
pipeline ao vivo para cada linha custaria minutos por incidente; pontuar transcrições gravadas é rápido,
repetível e comparável em CI.
""")

code(r'''
# Dataset: quatro transcrições completas de incidentes, cada uma com o resultado esperado.
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
    print(f"{row['incident_id']}  esperado: {row['expected_severity']}/{row['expected_category']}"
          f"/{row['expected_component']} -> {row['expected_decision']}")

# Versões de dataset são imutáveis, então incrementamos até achar uma livre.
def upload_dataset(name, file_path):
    last = None
    for version in range(1, 50):
        try:
            return project.datasets.upload_file(name=name, version=str(version), file_path=file_path)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"não foi possível subir {name}: {last}")

dataset = upload_dataset("zava-incident-eval", str(EVAL_DATASET))
print("\ndataset id:", dataset.id)

# Quer pontuar uma execução *ao vivo*? `run_eval.py --from-run` roda o pipeline real uma vez e
# acrescenta a saída dele como uma linha extra antes do upload.
''')

md(r"""
### 7️⃣.1 Avaliadores code-based sobre os hand-offs estruturados

Cada avaliador é uma `grade(sample, item) -> float` em sandbox. Todos partem do mesmo helper minúsculo que
faz o parse dos blocos JSON demarcados da transcrição — exatamente o formato de hand-off definido na §5.
""")

code(r'''
from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

# Prefixado a todo grader: o sandbox não compartilha imports entre avaliadores.
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
    # Fracao dos campos de triagem (severidade, categoria, componente) que batem com o esperado.
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
    # 1.0 apenas quando um arquivo mudou E a suite esta verde E existe um diff real.
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
    # O veredito bate com o esperado - e falha de forma segura com testes vermelhos.
    try:
        blocks = _blocks(_text(item))
        compliance = blocks.get("compliance") or {}
        code_fix = blocks.get("code_fix") or {}
        if not compliance:
            return 0.0
        decision = str(compliance.get("decision", "")).strip().lower().replace("_", "-")
        expected = str(item.get("expected_decision", "")).strip().lower().replace("_", "-")
        if decision == "approved" and code_fix and not code_fix.get("test_passed"):
            return 0.0                      # aprovar testes vermelhos e sempre errado
        if decision == "needs-changes" and not compliance.get("required_changes"):
            return 0.5                      # bloquear sem dizer o que mudar e meia resposta
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
     "Severidade, categoria e componente batem com a classificação esperada?", TRIAGE_MATCH_CODE),
    ("zava_fix_verified", "Zava Fix Verified",
     "A etapa de Correção mudou um arquivo e deixou os testes verdes?", FIX_VERIFIED_CODE),
    ("zava_compliance_decision", "Zava Compliance Decision",
     "O veredito de política bate com o esperado e falha de forma segura?", COMPLIANCE_DECISION_CODE),
]:
    evaluator = register_code_evaluator(name, display, description, code_text)
    print("registrado:", evaluator.name, "v" + str(evaluator.version))
''')

md(r"""
### 7️⃣.2 A **rubrica** de resposta a incidentes

Os avaliadores de código respondem *estava certo?*. A rubrica responde *estava bom?* — dimensões ponderadas
que um juiz LLM pontua de 1 a 5 com justificativa, cobrindo o que o ground truth não codifica: a correção foi
mínima, cada etapa carregou o resultado da anterior, um engenheiro de plantão entenderia o resumo.
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
        "description": "Critérios ponderados de qualidade para o pipeline multi-framework da Zava.",
        "definition": {
            "type": EvaluatorDefinitionType.RUBRIC,
            "dimensions": INCIDENT_RUBRIC_DIMENSIONS,
            "pass_threshold": 0.6,
        },
    },
)
print("rubrica:", rubric.name, "v" + str(rubric.version))
''')

code(r'''
# Executa: uma avaliação de dataset JSONL simples (sem target - as respostas já estão nas linhas).
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

print(f"status={run.status}  linhas: {run.result_counts.passed}/{run.result_counts.total} aprovadas\n")
for c in run.per_testing_criteria_results:
    total = c.passed + c.failed
    print(f"  {c.testing_criteria:<22s} pass {c.passed:>2d}  fail {c.failed:>2d}   "
          f"{(c.passed / total if total else 0):.0%}")
print("\nPortal do Foundry:\n", run.report_url)
''')

md(r"""
### 💡 O que observar

O `fix_verified` deve marcar **75%** — três incidentes entregam uma correção verificada, e o
**ZAVA-INC-4822** não: ele limita os valores negativos mas mantém a divisão para baixo, então dois testes
continuam vermelhos. Repare que o `compliance_decision` ainda passa nessa linha, porque *needs-changes* era o
veredito correto e ele listou mudanças concretas. Esse é o par que se quer numa avaliação de pipeline: um
critério pegando o defeito, outro confirmando que a barreira funcionou.

Tudo fica armazenado no projeto — `run.report_url` abre o **portal do Foundry**, e a mesma execução aparece
na aba **Evaluations** do web app.

Equivalente em script:

```powershell
.\.venv\Scripts\python.exe agents/incident-orchestration/run_eval.py
.\.venv\Scripts\python.exe agents/incident-orchestration/run_eval.py --from-run   # pontua uma execução real
```
""")

md(r"""
## 8️⃣ Hospedar no Foundry

`build_incident_agent()` encapsula o workflow sequencial como um único `WorkflowAgent` do MAF:

```python
from agent_framework import WorkflowAgent

WorkflowAgent(
    workflow=workflow,
    name=os.getenv("ORCHESTRATION_AGENT_NAME", "IncidentResponseOrchestrator"),
    description="Triage (LangGraph) -> Code Fix (GitHub Copilot SDK) -> Compliance (Foundry prompt agent).",
)
```

`main.py` o serve com:

```python
from agent_framework_foundry_hosting import ResponsesHostServer

agent = build_incident_agent()
app = ResponsesHostServer(agent=agent)
app.run()
```

Os clientes invocam o endpoint implantado por meio de:

- `ORCHESTRATION_AGENT_NAME`
- `ORCHESTRATION_AGENT_ENDPOINT`

O deploy como Foundry Hosted Agent é tentado primeiro. Azure Container Apps é o runtime fallback verificado
para este preview por causa do problema conhecido de argumentos de ferramentas no Responses hospedado.
""")

md(r"""
Para o caminho de runtime verificado, o repo cria `agents/incident-orchestration/Dockerfile`, envia a imagem
para o ACR e a implanta no **Azure Container Apps**; a URL `/responses` resultante é armazenada em
`ORCHESTRATION_AGENT_ENDPOINT`. Um deploy como Foundry Hosted Agent é tentado com o mesmo entrypoint do
agente, mas o runtime Responses hospedado atualmente tem o mesmo problema conhecido de preview com
argumentos de ferramentas descrito para o DeliverySupport. Em runtime de container headless, a etapa
**Correção de Código (Copilot SDK)** precisa de um token GitHub com acesso ao Copilot; localmente, ela usa
seu usuário logado no Copilot CLI.
""")

code(r"""
# ---------------------------------------------------------------------------
# De "workflow local" para "agente hospedado", em duas linhas de verdade.
# ---------------------------------------------------------------------------
# WorkflowAgent  -> classe do MAF que veste um `Workflow` inteiro com a MESMA interface de um
#                   agente comum (`.run()` / `.run_stream()`). É a peça que colapsa três
#                   frameworks e três etapas em UM objeto invocável. Quem chama de fora não sabe
#                   (nem precisa saber) que por dentro existe LangGraph, Copilot SDK e um prompt
#                   agent do Foundry: vê só um agente.
#
# ResponsesHostServer -> servidor ASGI do `agent-framework-foundry-hosting` que expõe qualquer
#                   agente MAF no protocolo **Responses** do Foundry (`POST /responses`, o mesmo
#                   contrato do Azure OpenAI). É o que torna o agente consumível por qualquer
#                   cliente Responses — portal do Foundry, SDK, curl — sem código de servidor.
from agent_framework import WorkflowAgent
from agent_framework_foundry_hosting import ResponsesHostServer

# Em processo hospedado não há notebook lendo o EventBus nem UI mostrando os todos, então aqui
# passamos instâncias novas e descartáveis: o pipeline continua funcionando, os eventos apenas
# não têm assinante. `build_incident_workflow` é a mesma função da §6.
orchestrator_agent = WorkflowAgent(
    workflow=build_incident_workflow(EventBus(), SharedTodoStore()),
    # `name` é a identidade do agente no Foundry — é por ele que o deploy e as traces o referenciam.
    name=os.getenv("ORCHESTRATION_AGENT_NAME", "IncidentResponseOrchestrator"),
    description="Zava incident response: Triage (LangGraph) -> Code Fix (Copilot SDK) -> Compliance (Foundry).",
)

# Entrypoint de agents/incident-orchestration/main.py (servido em 0.0.0.0:8088):
#
#   app = ResponsesHostServer(agent=orchestrator_agent)   # monta POST /responses sobre o agente
#   app.run()                                             # sobe o servidor ASGI e bloqueia
#
# Não chamamos `.run()` aqui porque isso bloquearia o kernel do notebook.
print("Agente hospedável:", orchestrator_agent.name)
print("Tipo             :", type(orchestrator_agent).__name__, "-> expõe .run() como qualquer agente MAF")
""")

code(r"""
# Invocação protegida do agente hospedado. Defina ORCHESTRATION_AGENT_ENDPOINT.
endpoint = os.environ.get("ORCHESTRATION_AGENT_ENDPOINT", "").rstrip("/")
if not endpoint:
    print("Defina ORCHESTRATION_AGENT_ENDPOINT para invocar a orquestração hospedada.")
else:
    import requests

    # A variável de ambiente pode ou não já trazer o caminho /responses.
    url = endpoint if endpoint.endswith("/responses") else endpoint + "/responses"
    # Corpo no formato Responses: `input` é o texto do usuário. O servidor o entrega ao
    # WorkflowAgent, que executa Triagem -> Correção -> Conformidade e devolve o texto final.
    # Timeout alto de propósito: a etapa do Copilot SDK roda pytest de verdade em uma sandbox.
    resp = requests.post(url, json={"input": incident_text}, timeout=300)

    # O ingress do Container Apps corta a conexão em ~240 s, então um pipeline lento devolve 504
    # mesmo com a execução seguindo no servidor. Em produção use o caminho assíncrono: crie a
    # response com `background=True` e faça polling em `GET /responses/{id}`.
    if resp.status_code in (502, 503, 504):
        print(f"HTTP {resp.status_code}: o ingress expirou antes de o pipeline terminar.")
        print("A execução continua no servidor — acompanhe pelas traces no portal do Foundry.")
    else:
        resp.raise_for_status()
        data = resp.json()
        print(data.get("output_text") or data)
""")

md(r"""
## 🔄 Recapitulando e próximos passos

Você viu como um incidente da Zava passa por uma equipe de agentes multi-framework:

| Etapa | Framework | Integração MAF | Saída |
|---|---|---|---|
| Triagem | LangGraph | `LangGraphTriageClient(BaseChatClient)` | severidade/categoria/componente/rota |
| Correção de Código | GitHub Copilot SDK | `CopilotCodeFixClient(BaseChatClient)` + `GitHubCopilotAgent` | diff, testes, resumo |
| Conformidade | Foundry prompt agent | `FoundryComplianceClient(BaseChatClient)` | approved / needs-changes |

…e duas capacidades de harness que só existem **porque** eles compartilham essa superfície uniforme:

| Capacidade | Implementação | O que você ganha |
|---|---|---|
| Todo provider | `TodoProvider` + um `SharedTodoStore` customizado | um plano de remediação vivo que as três etapas preenchem juntas |
| OpenTelemetry | `configure_otel_providers()` no `setup_observability()` | um trace GenAI distribuído cobrindo LangGraph + Copilot + Foundry |

Ideias para estender:

- adicionar evaluations e monitoramento contínuo no workflow hospedado,
- adicionar um quarto framework como outro adaptador `BaseChatClient`,
- persistir o todo store (um backend estilo `TodoFileStore`) para o plano sobreviver a um restart,
- transmitir o `EventBus` para telemetria mais rica.

Junto com os notebooks 01 e 02, isto completa a história da Zava: prompt agents, agentes MAF hospedados e,
agora, orquestração multi-framework no Foundry.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("Wrote", OUT, "with", len(cells), "cells")
