"""Builder for notebooks/02_delivery_support_agent.pt-BR.ipynb (Portugues do Brasil).
Mesmo codigo do notebook em ingles; apenas a narrativa esta em PT-BR.
Run: .venv\\Scripts\\python.exe notebooks/_builders/build_delivery_pt.py
"""
import os
import nbformat as nbf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "02_delivery_support_agent.pt-BR.ipynb")

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))
def code(t): cells.append(nbf.v4.new_code_cell(t.strip("\n")))

md(r"""
# 📦 Zava · Construindo o **DeliverySupport Agent** no Microsoft Foundry

> **Hosted agent** · **Microsoft Agent Framework (MAF)** · **Model Router** · ferramenta `lookupOrder` · **Memória** · **Traces + Evaluations + Evaluations Contínuas** · **Voice-live**
>
> 🇺🇸 Uma versão em inglês está disponível em `02_delivery_support_agent.en.ipynb`.

Os clientes da Zava — como **Jane**, **Priya** e **Diego** — querem rastrear seus pedidos ZavaCore Field e
entender atrasos sem esperar por um atendente. Neste notebook você constrói o **DeliverySupport Agent**: um
**hosted agent** escrito com o **Microsoft Agent Framework** e implantado no **Foundry Agent Service**.

Ele:
1. Roda no deployment **Model Router** (roteia entre modelos GPT por custo/qualidade).
2. Chama uma ferramenta **`lookupOrder`** contra o sistema de pedidos "de terceiros" da Zava (a API da Zava).
3. Mantém **memória** em dois níveis: **memória de sessão** dentro de uma conversa e **Foundry Memory** —
   recall durável por cliente, que sobrevive entre conversas.
4. Emite **traces** e é coberto por **evaluations** + **evaluations contínuas** (produção).
5. Suporta uma experiência **voice-live**.
""")

md(r"""
## 🏗️ Arquitetura

```mermaid
flowchart LR
  C[Cliente<br/>texto + voice-live] --> DEL[DeliverySupport<br/>hosted agent · MAF]
  DEL --> MR[Model Router<br/>deployment]
  DEL -->|lookupOrder / track_shipment| API[API de pedidos Zava<br/>sistema de terceiros]
  DEL --> SES[(Memória de sessão<br/>esta conversa)]
  DEL <-->|ContextProvider| FM[(Foundry Memory<br/>zava_delivery_memory)]
  DEL --> AI[(App Insights<br/>traces + evals contínuas)]
```

**Prompt agent vs. hosted agent.** O InventoryAgent (notebook 01) é um *prompt agent* — modelo +
instruções + ferramentas, gerenciado pelo serviço. O DeliverySupport é um **hosted agent**: seu próprio
**código** (um `Agent` do MAF com function tools em Python e memória customizada) empacotado e executado
pelo Foundry Agent Service. Você tem controle total da orquestração enquanto o Foundry cuida de hospedagem,
identidade e escala.
""")

md(r"""
## ✅ Pré-requisitos

- Infraestrutura provisionada (`scripts/provision.ps1`) — isso criou o deployment **`model-router`** e a API
  da Zava está implantada (`scripts/deploy_backend.ps1`).
- Os pacotes MAF estão instalados (no `.venv` do repo): `agent-framework`,
  `agent-framework-foundry-hosting`, `azure-identity`, `httpx`.
- `az login` feito (o agente usa `DefaultAzureCredential` localmente, managed identity quando hospedado).
- Um `.env` na raiz com os endpoints.
""")

code(r"""
# %pip install -r ../agents/delivery-support-agent/requirements.txt
import os, sys
from dotenv import load_dotenv

load_dotenv(os.path.join("..", ".env"))

# Torna o pacote do agente importável (agents/delivery-support-agent/src/agent.py)
AGENT_DIR = os.path.abspath(os.path.join("..", "agents", "delivery-support-agent"))
sys.path.insert(0, AGENT_DIR)

print("Model router:", os.environ.get("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))
print("Zava API    :", os.environ["ZAVA_API_BASE_URL"])
print("Account     :", os.environ["AZURE_AI_ACCOUNT_ENDPOINT"])
""")

md(r"""
## 1️⃣ A ferramenta `lookupOrder` — a sintaxe de tools do MAF

No Microsoft Agent Framework uma **ferramenta** é apenas uma função Python decorada. O decorator `@tool`
transforma a assinatura no schema JSON que o modelo enxerga: nomes dos parâmetros, suas descrições em
`Annotated[..., Field(...)]` e a docstring viram o contrato. `approval_mode="never_require"` significa que o
framework pode invocá-la sem uma rodada de aprovação humana.

Definimos as duas ferramentas reais **aqui no notebook** — é exatamente o padrão usado por
`agents/delivery-support-agent/src/agent.py`.
""")

code(r'''
import json
from typing import Annotated

import httpx
from agent_framework import tool          # <- o decorator de ferramentas do MAF
from pydantic import Field

ZAVA_API = os.environ["ZAVA_API_BASE_URL"].rstrip("/")


async def _get_tracking(path: str) -> str:
    """Chamada HTTP compartilhada contra o sistema de pedidos "de terceiros" da Zava."""
    async with httpx.AsyncClient(base_url=ZAVA_API, timeout=20.0) as client:
        response = await client.get(path)
    if response.status_code == 404:
        return json.dumps({"found": False, "message": "Não encontrei esse pedido ou código de rastreio."})
    response.raise_for_status()
    return json.dumps({"found": True, "tracking_card": response.json()}, ensure_ascii=False)


@tool(approval_mode="never_require")
async def lookup_order(
    order_id: Annotated[str, Field(description="O ID numérico do pedido Zava, por exemplo 23518.")],
) -> str:
    """Consulta um pedido Zava pelo ID numérico e retorna seu card de rastreamento."""
    print(f"[tool] lookup_order(order_id={order_id})", flush=True)
    return await _get_tracking(f"/orders/{str(order_id).strip()}")


@tool(approval_mode="never_require")
async def track_shipment(
    order_id: Annotated[str, Field(description="ID numérico do pedido Zava (opcional).")] = "",
    tracking_number: Annotated[str, Field(description="Código de rastreio da transportadora (opcional), ex. ZVX-7489201374829.")] = "",
) -> str:
    """Rastreia uma remessa por ID do pedido ou por código de rastreio."""
    print(f"[tool] track_shipment(order_id={order_id}, tracking_number={tracking_number})", flush=True)
    if str(order_id).strip():
        return await _get_tracking(f"/orders/{str(order_id).strip()}")
    if str(tracking_number).strip():
        return await _get_tracking(f"/track/{str(tracking_number).strip()}")
    return json.dumps({"found": False, "message": "Informe um ID de pedido ou um código de rastreio."})


# O decorator produziu um objeto de ferramenta do MAF, não uma função comum:
print(type(lookup_order).__name__)
print("name       :", lookup_order.name)
print("description:", lookup_order.description)
''')

md(r"""
## 2️⃣ O Model Router — o chat client do MAF

Em vez de fixar um modelo, o agente usa o deployment **`model-router`**. O Model Router inspeciona cada
requisição e a roteia para um modelo GPT apropriado — modelos mais baratos para consultas simples, modelos
mais fortes para explicações de atraso mais sutis — otimizando **custo vs. qualidade** automaticamente. Do
ponto de vista do agente, é apenas um nome de deployment.

No MAF o modelo é fornecido como um **chat client**. O `OpenAIChatCompletionClient` fala com a conta Foundry
com autenticação **Microsoft Entra** — sem chaves de API, porque a conta tem local auth desabilitado. A
credencial é passada como um *bearer-token provider*, então os tokens são renovados para você.
""")

code(r"""
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

chat_client = OpenAIChatCompletionClient(
    model=os.environ.get("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"),
    azure_endpoint=os.environ["AZURE_AI_ACCOUNT_ENDPOINT"].rstrip("/"),
    credential=token_provider,                # keyless: token Entra, renovado automaticamente
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
)

print("chat client:", type(chat_client).__name__)
print("deployment :", os.environ.get("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"))
""")

md(r"""
## 3️⃣ Construa o agente (com **memória de sessão**) e execute-o

Agora tudo se junta em um único objeto MAF. `Agent(...)` recebe o **chat client**, um **nome**, as
**instructions** (system prompt) e a lista de **tools** — essa é a definição inteira do agente. Não há
registro no serviço: este agente *é* o seu código.

`agent.create_session()` devolve o estado da conversa. Reutilizá-lo entre turnos é a **memória de curto
prazo** do agente — observe como o turno 2 (*"quando vai chegar?"*) é respondido sem repetir o número do
pedido.
""")

code(r'''
from agent_framework import Agent          # <- o tipo de chat-agent do MAF

INSTRUCTIONS = """
You are DeliverySupport, Zava\'s concise and empathetic order-tracking assistant.
Zava is ZavaCore Field athletic apparel. Customers track orders by numeric order ID
or carrier tracking number.

Rules:
- Never invent order, delivery, delay, or exception data.
- For every new order ID, tracking number, or explicit tracking request, call the
  lookup_order or track_shipment tool before answering.
- Use conversation/session history for follow-ups such as "when will it arrive?" so
  you can answer about the previously discussed order without asking again.
- When KNOWN CUSTOMER CONTEXT is provided, treat it as already confirmed: greet the
  customer by name and honour their stated delivery preferences.
- Include the exact status label, ETA, last location and destination when available.
- Keep answers brief, warm, and useful.
""".strip()

agent = Agent(
    client=chat_client,                    # Model Router, autenticação Entra
    name="DeliverySupport",
    instructions=INSTRUCTIONS,
    tools=[lookup_order, track_shipment],  # as funções @tool definidas acima
)

session = agent.create_session()           # <- a memória da conversa vive aqui
print(agent.name, "| tools:", [t.name for t in (lookup_order, track_shipment)])
''')

code(r"""
from collections.abc import Awaitable

async def say(prompt: str):
    resp = agent.run(prompt, session=session)   # mesma sessão -> contexto multi-turno
    if isinstance(resp, Awaitable):
        resp = await resp
    text = getattr(resp, "text", resp)
    print("Cliente:", prompt)
    print("DeliverySupport:", text, "\n")

await say("Hey, what's the status of order 23518?")   # -> lookup_order(23518): Delayed - Weather, ETA Feb 17
await say("When will it arrive?")                     # -> usa MEMÓRIA: responde Feb 17 sem re-perguntar
await say("What about order 23590?")                  # -> lookup_order(23590): Delivered
""")

md(r"""
> O agente publicado empacota exatamente essas três peças — tools, chat client, `Agent(...)` — atrás de
> `create_delivery_support_agent()` em `agents/delivery-support-agent/src/agent.py`, então o processo
> hospedado e este notebook executam a mesma definição:
>
> ```python
> from src.agent import create_delivery_support_agent, load_environment
> load_environment()
> agent = create_delivery_support_agent()
> ```
""")

md(r"""
### 💡 O que aconteceu
- Turno 1 → o agente chamou **`lookup_order("23518")`**, que acessou a API da Zava ao vivo e retornou o card
  *Delayed - Weather* (retido no CD de Memphis, ETA Feb 17). O agente explicou o atraso de forma clara.
- Turno 2 → *"when will it arrive?"* não tinha número de pedido, mas a **memória de sessão** permitiu ao
  agente responder **Feb 17, 2026** sobre o pedido 23518 — sem re-perguntar.
- Turno 3 → um novo id de pedido disparou uma nova chamada de ferramenta → *Delivered*.
""")

md(r"""
## 4️⃣ **Foundry Memory** — lembrar do cliente entre conversas

A memória de sessão morre junto com a conversa. Feche a aba, volte amanhã, e o agente esqueceu seu nome e
que você sempre quer as encomendas deixadas com a portaria. **Foundry Memory** resolve exatamente isso.

```mermaid
sequenceDiagram
  participant U as Cliente
  participant A as DeliverySupport (MAF)
  participant P as FoundryMemoryProvider<br/>(ContextProvider)
  participant F as Foundry Memory Store
  U->>A: "Como devo receber minha próxima entrega?"
  A->>P: before_run(messages)
  P->>F: search_memories(scope, query)
  F-->>P: perfil + resumos (busca semântica)
  P-->>A: context.instructions += fatos lembrados
  A-->>U: "Oi Marcus — assinatura obrigatória, como sempre."
  A->>P: after_run(messages)
  P->>F: begin_update_memories(scope, messages)
  Note over F: extrai memórias duráveis de forma assíncrona<br/>(com debounce de update_delay)
```

**Três conceitos**

| Conceito | Significado |
|---|---|
| **Store** | O banco de memórias. Tem um *chat model* (faz a extração), um *embedding model* (busca semântica), os *tipos* de memória a coletar e um *TTL*. |
| **Scope** | Uma partição = **um cliente**. Busca e exclusão são sempre com escopo, então clientes nunca veem memórias uns dos outros. |
| **Kinds** | `user_profile` (fatos duráveis), `chat_summary` (resumos rolantes da conversa), `procedural` (regras de comportamento aprendidas). |

### 4️⃣.1 Criando o store

`user_profile_details` é o parâmetro de maior impacto da feature inteira: é a instrução que o modelo de
extração segue para decidir o que vale a pena guardar — e o que nunca pode ser armazenado.
""")

code(r'''
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
)
stores = project.beta.memory_stores          # <- a superfície da API de Foundry Memory
STORE_NAME = os.environ.get("DELIVERY_MEMORY_STORE_NAME", "zava_delivery_memory")

USER_PROFILE_DETAILS = (
    "Remember the customer's preferred name, delivery preferences (safe place, concierge, "
    "signature requirements, preferred delivery window), preferred carrier, notification "
    "channel, accessibility needs, and the Zava orders or tracking numbers they follow. "
    "Do not store payment details, full street addresses, credentials, government IDs, "
    "precise geolocation, age or any other sensitive personal data."
)

try:
    store = stores.get(STORE_NAME)
    print("store já existe:", store.name)
except Exception:
    store = stores.create(
        name=STORE_NAME,
        description="Per-customer memory for Zava's DeliverySupport agent",
        definition=MemoryStoreDefaultDefinition(
            chat_model=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1"),        # extração
            embedding_model=os.environ.get("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large"),  # recall
            options=MemoryStoreDefaultOptions(
                user_profile_enabled=True,
                chat_summary_enabled=True,
                default_ttl_seconds=30 * 24 * 3600,   # esquece após 30 dias ociosos (0 = nunca)
                user_profile_details=USER_PROFILE_DETAILS,
            ),
        ),
    )
    print("store criado:", store.name)
''')

md(r"""
### 4️⃣.2 As quatro chamadas de memória

A feature inteira são quatro métodos em `project.beta.memory_stores`. Todo o resto — o provider, o painel do
web app, a demo do notebook — é construído em cima deles:

| Chamada | O que faz |
|---|---|
| `search_memories(store, scope, items)` | recall semântico para o turno atual |
| `begin_update_memories(store, scope, items, update_delay)` | devolve o turno concluído para extração (assíncrono, com debounce) |
| `list_memories(store, scope)` | tudo o que está guardado para um cliente |
| `delete_scope(store, scope)` | esquece um cliente por completo |

O wrapper abaixo é exatamente o que está em `src/memory.py` — escrito aqui para as chamadas de SDK ficarem
visíveis.
""")

code(r'''
class ZavaMemory:
    """Wrapper fino e síncrono sobre a API de Memory Store do Foundry."""

    def __init__(self, stores, name: str, update_delay: int = 5) -> None:
        self.stores, self.name, self.update_delay = stores, name, update_delay

    def recall(self, query: str, *, scope: str, limit: int = 8) -> list[dict]:
        result = self.stores.search_memories(self.name, scope=scope, items=query)
        memories = getattr(result, "memories", None) or getattr(result, "results", None) or []
        return [self._flatten(item) for item in list(memories)[:limit]]

    def remember(self, items: list[dict], *, scope: str):
        # Com debounce: o Foundry espera a conversa ficar quieta antes de consolidar.
        return self.stores.begin_update_memories(
            self.name, scope=scope, items=items, update_delay=self.update_delay
        )

    def list_items(self, *, scope: str, limit: int = 50) -> list[dict]:
        return [self._flatten(i) for i in self.stores.list_memories(self.name, scope=scope, limit=limit)]

    def clear_scope(self, *, scope: str):
        return self.stores.delete_scope(self.name, scope=scope)

    @staticmethod
    def _flatten(item) -> dict:
        # search_memories devolve MemorySearchItem (que embrulha memory_item); list_memories devolve MemoryItem.
        inner = getattr(item, "memory_item", None) or item
        kind = getattr(inner, "kind", None)
        return {
            "id": str(getattr(inner, "memory_id", None) or getattr(inner, "id", "")),
            "content": str(getattr(inner, "content", "") or ""),
            "kind": str(getattr(kind, "value", kind) or "memory"),
            "score": getattr(item, "score", None),
        }


KIND_LABEL = {"user_profile": "Profile", "chat_summary": "Past conversation", "procedural": "Learned habit"}

def format_recall(memories: list[dict]) -> str:
    """Renderiza as memórias recuperadas como um bloco de instruções para o modelo."""
    lines = [f"- ({KIND_LABEL.get(m['kind'], 'Memory')}) {m['content'].strip()}"
             for m in memories if m.get("content")]
    if not lines:
        return ""
    return ("KNOWN CUSTOMER CONTEXT (recalled from Zava's long-term memory — treat as already confirmed, "
            "use it proactively, never ask the customer to repeat it, and never invent additions):\n"
            + "\n".join(lines))


memory = ZavaMemory(stores, STORE_NAME, update_delay=int(os.environ.get("DELIVERY_MEMORY_UPDATE_DELAY", "5")))
print("wrapper de memória pronto para o store:", memory.name)
''')

md(r"""
### 4️⃣.3 Conectando memória a um agente MAF — o `ContextProvider`

O Foundry oferece uma ferramenta nativa **`memory_search_preview`**, mas ela é para **prompt agents**
(como o InventoryAgent do notebook 01). O DeliverySupport é um **hosted agent MAF**, então ele mesmo chama
as APIs de memória — o padrão documentado *"seu backend é dono das chamadas de memória"* — através de um
**`ContextProvider`** do MAF, o ponto de extensão oficial para injetar contexto em toda execução.

Um `ContextProvider` tem dois hooks, ambos recebendo o `context` da execução como keyword argument:

- **`before_run`** — busca no Foundry e **acrescenta em `context.instructions`**.
- **`after_run`** — devolve o turno concluído ao Foundry para extração.
""")

code(r'''
import asyncio

from agent_framework import ContextProvider          # <- ponto de extensão do MAF


def latest_user_text(messages) -> str:
    for message in reversed(list(messages or [])):
        role = str(getattr(getattr(message, "role", None), "value", getattr(message, "role", "")) or "").lower()
        text = getattr(message, "text", None) or ""
        if text and role in ("user", ""):
            return text
    return ""


class FoundryMemoryProvider(ContextProvider):
    """Dá ao agente memória durável por cliente, apoiada em um memory store do Foundry."""

    def __init__(self, memory: ZavaMemory, scope: str) -> None:
        super().__init__(source_id="foundry-memory")
        self.memory, self.scope = memory, scope

    async def before_run(self, *, agent, session, context, state) -> None:
        query = latest_user_text(context.input_messages)
        if not query:
            return
        memories = await asyncio.to_thread(self.memory.recall, query, scope=self.scope)
        block = format_recall(memories)                 # "KNOWN CUSTOMER CONTEXT: ..."
        if block:
            context.instructions.append(block)          # <- o recall entra nas INSTRUCTIONS
            print(f"[memory] recalled {len(memories)} item(s) for scope={self.scope}", flush=True)

    async def after_run(self, *, agent, session, context, state) -> None:
        user_text = latest_user_text(context.input_messages)
        answer = getattr(context.response, "text", "") or ""
        if not user_text or not answer:
            return
        await asyncio.to_thread(                        # fire-and-forget, com debounce no Foundry
            self.memory.remember,
            [
                {"type": "message", "role": "user", "content": user_text},
                {"type": "message", "role": "assistant", "content": answer},
            ],
            scope=self.scope,
        )
        print(f"[memory] queued update for scope={self.scope}", flush=True)


print("provider pronto:", FoundryMemoryProvider.__name__)
''')

md(r"""
Dois detalhes que importam:

- **O recall entra em `instructions`, não no histórico do chat.** Memórias são *contexto sobre* o cliente,
  não coisas que alguém disse. Fingir que são mensagens confunde o modelo e polui a transcrição.
- **As escritas são assíncronas e com debounce.** `begin_update_memories` retorna imediatamente; o Foundry
  espera `update_delay` segundos de silêncio e então roda o modelo de extração. Ou seja, uma memória dita
  *agora* costuma ficar buscável ~10–30 s depois — nunca faça `assert` sobre ela no mesmo turno.

Anexá-lo é um argumento a mais no mesmo construtor `Agent(...)` da seção 3:

```python
Agent(client=chat_client, name="DeliverySupport", instructions=INSTRUCTIONS,
      tools=[lookup_order, track_shipment],
      context_providers=[FoundryMemoryProvider(memory, scope)])   # <- a única diferença
```
""")

code(r"""
# Prova de recall entre sessões. A sessão 2 é um agente NOVO, com zero histórico de conversa.
import time
from collections.abc import Awaitable

async def ask(a, prompt):
    r = a.run(prompt)
    if isinstance(r, Awaitable):
        r = await r
    return getattr(r, "text", r)

def remembering_agent(scope: str) -> Agent:
    return Agent(
        client=chat_client,
        name="DeliverySupport",
        instructions=INSTRUCTIONS,
        tools=[lookup_order, track_shipment],
        context_providers=[FoundryMemoryProvider(memory, scope)],
    )

SCOPE = "zava-notebook-demo"
memory.clear_scope(scope=SCOPE)          # começa limpo para a demo

s1 = remembering_agent(SCOPE)
print(await ask(s1, "Hi, I'm Priya Raman. Always leave my Zava parcels with the building "
                    "concierge and text me instead of emailing. Can you check order 23518?"))

print("\naguardando o Foundry consolidar as memórias...")
items = []
for _ in range(24):
    time.sleep(5)
    items = memory.list_items(scope=SCOPE)
    if items:
        break
for i in items:
    print(f"  [{i['kind']}] {i['content'][:120]}")

# --- novo dia, nova conversa, sem histórico ---
s2 = remembering_agent(SCOPE)
print("\n", await ask(s2, "Hi again - how should my next delivery be handled?"))
# -> chama a Priya pelo nome e repete portaria + só SMS, sem nada na transcrição.
""")

md(r"""
### 💡 O que aconteceu
- A transcrição da sessão 1 foi entregue ao Foundry, que a destilou em fatos `user_profile`
  (*nome = Priya Raman*, *entrega = portaria*, *canal = SMS*, *acompanha o pedido 23518*) mais um
  `chat_summary`.
- A sessão 2 era um **objeto de agente novo, com sessão vazia**. O `before_run` buscou no mesmo **scope**,
  encontrou esses fatos e os injetou como instruções — então o agente respondeu como se conhecesse a Priya
  há meses.
- Rode `python agents/delivery-support-agent/test_memory.py` para a mesma verificação em script, ou inspecione
  o escopo direto com `memory.list_items(scope=SCOPE)` e limpe com `memory.clear_scope(scope=SCOPE)`.

> **Qual agente deve ter memória?** O DeliverySupport — ele fala com *a mesma pessoa* repetidamente sobre
> *as remessas dela*, então continuidade é o produto. O InventoryAgent é operacional e analítico: seu
> "estado" é o armazém ao vivo, e lembrar perguntas passadas de um gerente de operações agrega pouco.
> Regra prática: **memória pertence a onde existe um relacionamento durável com o usuário final.**
""")

md(r"""
## 5️⃣ Rode o servidor hospedado localmente

`main.py` encapsula o agente no adaptador de hospedagem do Foundry (`ResponsesHostServer`), então o *mesmo
código* roda localmente e no Foundry Agent Service:

```powershell
Set-Location agents/delivery-support-agent
..\..\.venv\Scripts\python.exe .\main.py         # serve /responses na porta 8088
# smoke test:
Invoke-WebRequest http://localhost:8088/responses -Method POST -ContentType application/json `
  -Body '{"input":"Track order 23518"}'
```
""")

md(r"""
## 6️⃣ Implantar no **Foundry Agent Service** (hosted)

Hosted agents são implantados com **`azd`** usando **deploy direto de código** — o Foundry compacta seu
código-fonte e constrói a imagem de runtime (sem Docker). O bloco de serviço do `azure.yaml` usa
`codeConfiguration`:

```yaml
services:
  delivery-support-agent:
    project: ./agents/delivery-support-agent
    host: azure.ai.agent
    config: { name: DeliverySupport }
    codeConfiguration:
      runtime: python_3_13
      entryPoint: main.py
      dependencyResolution: remote_build
    environmentVariables:
      AZURE_AI_ACCOUNT_ENDPOINT: ${AZURE_AI_ACCOUNT_ENDPOINT}
      MODEL_ROUTER_DEPLOYMENT_NAME: ${MODEL_ROUTER_DEPLOYMENT_NAME}
      ZAVA_API_BASE_URL: ${ZAVA_API_BASE_URL}
```

```powershell
# aponte o azd para o projeto Foundry existente e implante apenas este agente
azd env set AZURE_AI_PROJECT_ENDPOINT "<project-endpoint>"
azd deploy delivery-support-agent --no-prompt
azd ai agent show --output json
azd ai agent invoke "What's the status of order 23518?"
```

> A managed identity do hosted agent precisa de **Cognitive Services OpenAI User** na conta Foundry para
> chamar o `model-router`. Veja `agents/delivery-support-agent/README.md`.
""")

md(r"""
## 7️⃣ Traces — OpenTelemetry ponta a ponta

O MAF é **instrumentado com OpenTelemetry** seguindo as convenções semânticas de GenAI. Uma chamada a
`configure_otel_providers()` e cada chamada de modelo, chamada de ferramenta e execução de agente emite um
span com atributos `gen_ai.*` — sem wiring por agente.

A forma mais rápida de *ver* isso é exportar os spans para dentro do próprio notebook com um `SpanExporter`
mínimo, rodar um turno e imprimir o que o MAF produziu. Registramos o **exporter do Application Insights ao
mesmo tempo**, porque `configure_otel_providers()` configura o processo **uma única vez** — chamar de novo
no mesmo kernel não adiciona exporters.
""")

code(r'''
from agent_framework.observability import configure_otel_providers
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

CAPTURED = []

class NotebookSpanExporter(SpanExporter):
    """Coleta os spans finalizados em memória para imprimirmos aqui."""

    def export(self, spans):
        CAPTURED.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None

exporters = [NotebookSpanExporter()]
APPINSIGHTS = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
if APPINSIGHTS:                                   # exatamente o que o hosted agent faz em produção
    os.environ.setdefault("OTEL_SERVICE_NAME", "zava-delivery-support")
    exporters.append(AzureMonitorTraceExporter(connection_string=APPINSIGHTS))

# enable_sensitive_data também anexa prompts/respostas aos spans — apenas em tenants de demo.
configure_otel_providers(exporters=exporters, enable_sensitive_data=True)

from collections.abc import Awaitable

async def run_once(agent, prompt: str) -> str:
    response = agent.run(prompt)
    if isinstance(response, Awaitable):
        response = await response
    return getattr(response, "text", response)

print(f"OpenTelemetry configurado com {len(exporters)} exporter(s) — o MAF já emite spans GenAI")
''')

code(r'''
# Roda um turno, faz o flush e inspeciona os spans que o MAF emitiu.
traced = Agent(client=chat_client, name="DeliverySupport",
               instructions=INSTRUCTIONS, tools=[lookup_order, track_shipment])
print(await run_once(traced, "What's the status of order 23518?"), "\n")

trace.get_tracer_provider().force_flush()

for span in CAPTURED:
    attrs = dict(span.attributes or {})
    duration_ms = (span.end_time - span.start_time) / 1_000_000
    print(f"{span.name:<34s} {duration_ms:7.0f} ms")
    for key in sorted(k for k in attrs if k.startswith("gen_ai.")):
        value = str(attrs[key]).replace("\n", " ")
        print(f"    {key:<34s} {value[:90]}")
    print()
''')

md(r"""
Três formatos de span valem reconhecer, porque são o que o portal do Foundry e o Application Insights
renderizam:

- **`invoke_agent <nome>`** — a execução inteira do agente: `gen_ai.agent.name`, as instruções de sistema, as
  definições de ferramentas que o modelo podia escolher e o uso total de tokens.
- **`chat <modelo>`** — uma chamada de modelo, com `gen_ai.request.model`, `gen_ai.input.messages` /
  `gen_ai.output.messages` (só com `enable_sensitive_data`) e tokens por chamada.
- **`execute_tool <nome>`** — uma invocação de ferramenta, com `gen_ai.tool.name`,
  `gen_ai.tool.call.arguments` e `gen_ai.tool.call.result`. É o que prova que o agente *realmente consultou
  o pedido*.

### 7️⃣.1 Lendo os mesmos traces de volta no Application Insights

Esses spans também foram enviados ao **Application Insights** pelo exporter registrado acima — é tudo o que o
hosted agent faz em produção (`APPLICATIONINSIGHTS_CONNECTION_STRING` já vem do `scripts/provision.ps1`).

Traces só servem se você consegue consultá-los. Os spans do MAF caem na tabela **`dependencies`** com os
atributos GenAI em `customDimensions`, então *"quais ferramentas este agente chamou hoje e quanto tempo
levaram?"* é uma query KQL, não um print de tela.
""")

code(r'''
# pip install azure-monitor-query
from datetime import timedelta
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

# O provision.ps1 grava o nome do App Insights; o resource id sai dele.
RESOURCE_ID = os.environ.get("APPINSIGHTS_RESOURCE_ID") or (
    f"/subscriptions/{os.environ.get('AZURE_SUBSCRIPTION_ID', '')}"
    f"/resourceGroups/{os.environ.get('AZURE_RESOURCE_GROUP', '')}"
    f"/providers/Microsoft.Insights/components/{os.environ.get('APPLICATIONINSIGHTS_NAME', '')}"
)

QUERY = """
dependencies
| where timestamp > ago(1h)
| extend op    = tostring(customDimensions["gen_ai.operation.name"]),
         agent = tostring(customDimensions["gen_ai.agent.name"]),
         tool  = tostring(customDimensions["gen_ai.tool.name"]),
         model = tostring(customDimensions["gen_ai.request.model"]),
         tokens = toint(customDimensions["gen_ai.usage.output_tokens"])
| where isnotempty(op)
| project timestamp, op, agent, tool, model, tokens, ms = round(duration)
| order by timestamp desc
| take 15
"""

logs = LogsQueryClient(DefaultAzureCredential(exclude_interactive_browser_credential=True))
result = logs.query_resource(RESOURCE_ID, QUERY, timespan=timedelta(hours=1))
if result.status == LogsQueryStatus.SUCCESS and result.tables and result.tables[0].rows:
    table = result.tables[0]
    print(" | ".join(f"{c:<22s}" for c in table.columns))
    for row in table.rows:
        print(" | ".join(f"{str(v)[:22]:<22s}" for v in row))
else:
    print("Ainda sem linhas — a ingestão do App Insights leva de 1 a 3 minutos. Rode esta célula de novo,")
    print("ou abra o portal do Foundry -> Tracing / Application Insights -> Transaction search.")
''')


md(r"""
## 8️⃣ Evaluations

O Foundry pontua o agente **como serviço**, então os resultados ficam no projeto (portal → *Evaluations*, e a
aba *Evaluations* do web app) em vez de em uma variável local do notebook.

### Escolhendo os avaliadores certos para *este* agente

O DeliverySupport é um agente com ferramentas e voltado ao cliente, então o conjunto é montado em torno dos
seus modos de falha reais — não de um checklist genérico de qualidade:

| Avaliador | Tipo | A falha que ele pega |
|---|---|---|
| `builtin.intent_resolution` | built-in | entender errado o que o cliente pediu |
| `builtin.task_adherence` | built-in | ignorar as próprias regras (responder antes de consultar) |
| `builtin.tool_call_success` | built-in | `lookup_order` / `track_shipment` falhando em silêncio |
| `zava_tracking_facts` | **custom, código** | o status / ETA / localização reais faltando na resposta |
| `zava_no_fabrication` | **custom, código** | a pior de todas: inventar status, ETA ou código de rastreio |
| `zava_delivery_rubric` | **rubric** | qualidade geral do atendimento, ponderada e justificada |

Os dois últimos existem porque nenhum avaliador genérico conhece os dados da Zava. O dataset carrega os fatos
que a resposta **deve** conter (`must_include`) e, para as duas linhas em que o agente não tem o que
consultar — um pedido inexistente e uma pergunta sem número de pedido — as frases que ela **não pode** conter
(`forbidden`).
""")

code(r'''
# O dataset de avaliação: 9 perguntas reais de rastreamento com ground truth.
import json
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
)
oai = project.get_openai_client()
JUDGE = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")

EVAL_DATASET = os.path.join("..", "agents", "delivery-support-agent", "evals", "delivery_eval.jsonl")
rows = [json.loads(line) for line in open(EVAL_DATASET, encoding="utf-8") if line.strip()]
print(json.dumps(rows[0], indent=2)[:420])
print(f"\n{len(rows)} linhas "
      f"({sum(1 for r in rows if r.get('forbidden'))} delas são linhas anti-alucinação)")

# Versões de dataset são imutáveis, então incrementamos até achar uma livre.
def upload_dataset(name, file_path):
    last = None
    for version in range(1, 50):
        try:
            return project.datasets.upload_file(name=name, version=str(version), file_path=file_path)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"não foi possível subir {name}: {last}")

dataset = upload_dataset("zava-delivery-eval", EVAL_DATASET)
print("dataset id:", dataset.id)
''')

md(r"""
### 8️⃣.1 Os dois avaliadores **custom code-based**

Um avaliador code-based é uma função `grade(sample, item) -> float` que o Foundry roda em sandbox (sem rede,
2 minutos por chamada). Determinístico, barato, e nunca alucina sobre alucinação.
""")

code(r'''
from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

TRACKING_FACTS_CODE = """
def grade(sample: dict, item: dict) -> float:
    # Fracao dos fatos de rastreamento exigidos que aparecem na resposta.
    # Alternativas sao separadas por "|", entao uma data pode ser "Feb 17" ou "2026-02-17".
    try:
        response = item.get("sample", {}).get("output_text") or item.get("response") or ""
        required = item.get("must_include") or []
        if isinstance(required, str):
            required = [required]
        if not required:
            return 1.0 if response.strip() else 0.0
        haystack = response.lower().replace(",", "")
        hits = 0
        for entry in required:
            options = [o.strip().lower().replace(",", "") for o in str(entry).split("|") if o.strip()]
            if any(o in haystack for o in options):
                hits += 1
        return round(hits / len(required), 4)
    except Exception:
        return 0.0
"""

NO_FABRICATION_CODE = """
def grade(sample: dict, item: dict) -> float:
    # 1.0 quando a resposta nao contem nenhuma das frases proibidas, 0.0 caso contrario.
    # Usado nas linhas em que o agente nao tem o que consultar: inventar status, ETA ou codigo
    # de rastreio ali e o pior modo de falha de um agente de rastreamento.
    try:
        response = (item.get("sample", {}).get("output_text") or item.get("response") or "").lower()
        forbidden = item.get("forbidden") or []
        if isinstance(forbidden, str):
            forbidden = [forbidden]
        if not forbidden:
            return 1.0
        leaked = [f for f in forbidden if str(f).strip().lower() in response]
        return 0.0 if leaked else 1.0
    except Exception:
        return 0.0
"""

def register_code_evaluator(name, display_name, description, code_text, properties):
    return project.beta.evaluators.create_version(
        name=name,
        evaluator_version={
            "name": name,
            "categories": [EvaluatorCategory.QUALITY],
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
                                "properties": {"item": {"type": "object", "properties": properties}}},
            },
        },
    )

facts = register_code_evaluator(
    "zava_tracking_facts", "Zava Tracking Facts",
    "Fração dos fatos reais de status/ETA/localização presentes na resposta.",
    TRACKING_FACTS_CODE,
    {"query": {"type": "string"}, "ground_truth": {"type": "string"}, "must_include": {"type": "array"}},
)
guard = register_code_evaluator(
    "zava_no_fabrication", "Zava No Fabrication",
    "Barreira dura: a resposta não pode inventar status, ETA ou código de rastreio.",
    NO_FABRICATION_CODE,
    {"query": {"type": "string"}, "forbidden": {"type": "array"}},
)
print("registrados:", facts.name, "|", guard.name)
''')

md(r"""
### 8️⃣.2 A **rubrica** de entrega

Dimensões ponderadas, cada uma julgada de 1 a 5 por um LLM e normalizadas para 0–1. `lookup_before_answer` e
`no_fabrication` têm os maiores pesos porque são o que torna um agente de rastreamento confiável.
""")

code(r'''
DELIVERY_RUBRIC_DIMENSIONS = [
    {"id": "lookup_before_answer", "weight": 9, "description":
     "Calls lookup_order or track_shipment before stating any status, and asks the customer for an order "
     "or tracking number when none was given. Never answers from assumption."},
    {"id": "factual_tracking_detail", "weight": 7, "description":
     "Reports the exact status label, estimated delivery date, carrier and last known location returned "
     "by the tool, without altering or rounding them."},
    {"id": "delay_explanation", "weight": 6, "description":
     "Explains weather, customs, volume and address exceptions in plain language and says clearly whether "
     "the customer needs to do anything."},
    {"id": "no_fabrication", "weight": 8, "description":
     "Never invents an order, ETA, tracking number or delivery confirmation. For unknown orders it says so "
     "and asks the customer to check the number."},
    {"id": "conversational_continuity", "weight": 4, "description":
     "Uses the conversation and remembered customer preferences for follow-ups such as 'when will it "
     "arrive?' instead of asking for the order number again."},
    {"id": "tone", "weight": 3, "description":
     "Warm, brief and empathetic; acknowledges frustration without over-apologising."},
    {"id": "general_quality", "weight": 5, "always_applicable": True, "description":
     "Other important quality factors not covered by the listed criteria."},
]

rubric = project.beta.evaluators.create_version(
    name="zava_delivery_rubric",
    evaluator_version={
        "name": "zava_delivery_rubric",
        "categories": [EvaluatorCategory.AGENTS],
        "display_name": "Zava Delivery Quality",
        "description": "Critérios ponderados de qualidade para respostas de rastreamento da Zava.",
        "definition": {
            "type": EvaluatorDefinitionType.RUBRIC,
            "dimensions": DELIVERY_RUBRIC_DIMENSIONS,
            "pass_threshold": 0.6,
        },
    },
)
print("rubrica:", rubric.name, "v" + str(rubric.version))
''')

md(r"""
### 8️⃣.3 Executando contra o agente implantado

O `DeliverySupport` está registrado no Foundry, então a execução pode usá-lo como **agent target**: o Foundry
envia cada pergunta ao agente hospedado, captura a resposta *com as chamadas de ferramenta*
(`{{sample.output_items}}`) e pontua.
""")

code(r'''
import time
from azure.ai.projects.models import TestingCriterionAzureAIEvaluator
from openai.types.eval_create_params import DataSourceConfigCustom

def criterion(name, evaluator, mapping, init):
    return TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name=name, evaluator_name=evaluator,
        initialization_parameters=init, data_mapping=mapping,
    )

testing_criteria = [
    criterion("intent_resolution", "builtin.intent_resolution",
              {"query": "{{item.query}}", "response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
    criterion("task_adherence", "builtin.task_adherence",
              {"query": "{{item.query}}", "response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
    criterion("tool_call_success", "builtin.tool_call_success",
              {"response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
    criterion("tracking_facts", "zava_tracking_facts", {},
              {"deployment_name": JUDGE, "pass_threshold": 0.99}),
    criterion("no_fabrication", "zava_no_fabrication", {},
              {"deployment_name": JUDGE, "pass_threshold": 1.0}),
    criterion("delivery_rubric", rubric.name,
              {"query": "{{item.query}}", "response": "{{sample.output_items}}"}, {"deployment_name": JUDGE}),
]

evaluation = oai.evals.create(
    name="Zava DeliverySupport quality",
    data_source_config=DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"}, "ground_truth": {"type": "string"},
                "must_include": {"type": "array"}, "forbidden": {"type": "array"},
                "expected_tool": {"type": "string"},
            },
            "required": ["query"],
        },
        include_sample_schema=True,
    ),
    testing_criteria=testing_criteria,
)

eval_run = oai.evals.runs.create(
    eval_id=evaluation.id,
    name="delivery-agent-target",
    data_source={
        "type": "azure_ai_target_completions",
        "source": {"type": "file_id", "id": dataset.id},
        "input_messages": {"type": "template", "template": [
            {"type": "message", "role": "user", "content": {"type": "input_text", "text": "{{item.query}}"}},
        ]},
        "target": {"type": "azure_ai_agent", "name": "DeliverySupport"},
    },
)

while True:
    run = oai.evals.runs.retrieve(run_id=eval_run.id, eval_id=evaluation.id)
    if str(run.status) in ("completed", "failed", "canceled"):
        break
    time.sleep(10)

print(f"status={run.status}  linhas: {run.result_counts.passed}/{run.result_counts.total} aprovadas\n")
for c in run.per_testing_criteria_results:
    total = c.passed + c.failed
    print(f"  {c.testing_criteria:<20s} pass {c.passed:>2d}  fail {c.failed:>2d}   "
          f"{(c.passed / total if total else 0):.0%}")
print("\nPortal do Foundry:\n", run.report_url)
''')

md(r"""
### 💡 O que aconteceu

- O Foundry chamou o agente DeliverySupport **implantado** uma vez por linha do dataset, capturou a resposta
  *e* as chamadas `lookup_order` / `track_shipment`, e pontuou os seis critérios sobre isso.
- As linhas interessantes são as duas últimas: o pedido **99999** não existe e *"Where is my package?"* não
  tem número de pedido algum. Ali o `zava_no_fabrication` é uma barreira dura — qualquer status, ETA ou
  número `ZVX-…` inventado zera a nota.
- Os resultados ficam no projeto: `run.report_url` abre o **portal do Foundry**, e a mesma execução aparece
  na aba **Evaluations** do web app.

Equivalente em script (mesmos avaliadores, mesmo dataset):

```powershell
.\.venv\Scripts\python.exe agents/delivery-support-agent/run_eval.py
```

> **Evaluations contínuas:** com o agente implantado e o App Insights conectado, o portal pode amostrar
> tráfego de **produção** e rodar esse mesmo conjunto de critérios periodicamente, para que regressões
> apareçam em um dashboard em vez de em um ticket de suporte.
""")

md(r"""
## 9️⃣ Voice-live

A API **Azure AI Foundry Voice Live** dá ao DeliverySupport uma interface falada: o cliente pergunta
*"onde está meu pedido?"* em voz alta e ouve a resposta, enquanto as mesmas ferramentas rodam no servidor.

É um **WebSocket realtime**, não uma chamada REST. Três coisas definem a integração:

| Peça | Valor |
|---|---|
| Endpoint | `wss://<conta>/voice-live/realtime?api-version=…&model=gpt-realtime-mini` |
| Auth | `Authorization: Bearer <token Entra>` para `https://cognitiveservices.azure.com/.default` |
| Configuração | um evento `session.update`: instruções, formatos de áudio, detecção de turno, **as mesmas ferramentas** e a voz |

As células abaixo abrem uma sessão real contra o seu deployment. Para ficar executável em um notebook,
conduzimos o turno com **texto** em vez de microfone — todo o resto (tool calling, síntese de áudio) é
idêntico ao que o navegador faz em `webapp/inventory-dashboard/app/voice.py`.
""")

code(r'''
import json
import websockets
from azure.identity import DefaultAzureCredential

ACCOUNT = os.environ["AZURE_AI_ACCOUNT_ENDPOINT"].rstrip("/").replace("https://", "")
API_VERSION = os.environ.get("VOICE_LIVE_API_VERSION", "2026-06-01-preview")
REALTIME_MODEL = os.environ.get("REALTIME_DEPLOYMENT_NAME", "gpt-realtime-mini")

VOICE_URL = f"wss://{ACCOUNT}/voice-live/realtime?api-version={API_VERSION}&model={REALTIME_MODEL}"
TOKEN = DefaultAzureCredential(exclude_interactive_browser_credential=True).get_token(
    "https://cognitiveservices.azure.com/.default"
).token

# O modelo realtime precisa dos SCHEMAS das ferramentas (ele chama; o seu código executa).
VOICE_TOOLS = [
    {"type": "function", "name": "lookup_order",
     "description": "Look up a Zava order by numeric order id; returns the full tracking card.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"]}},
    {"type": "function", "name": "track_shipment",
     "description": "Track a shipment by order id or carrier tracking number (ZVX-...).",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"},
                                                     "tracking_number": {"type": "string"}}}},
]

# Locales que o cliente pode falar. Alimenta o reconhecimento de fala E o VAD multilingue.
VOICE_LOCALES = ["en-US", "pt-BR", "es-ES", "fr-FR", "de-DE", "it-IT"]

SESSION_UPDATE = {
    "type": "session.update",
    "session": {
        "instructions": (
            "You are Zava DeliverySupport on a live voice call with a customer tracking a ZavaCore Field "
            "order. Always call lookup_order or track_shipment before answering — never invent order, "
            "delay or ETA data. Be warm, concise and clear: this is spoken. Detect the language the "
            "customer speaks and reply in THAT language for the whole call."
        ),
        "modalities": ["text", "audio"],
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        # `azure-speech` (e não `whisper-1`) é o que aceita uma lista de locales.
        "input_audio_transcription": {"model": "azure-speech", "language": ",".join(VOICE_LOCALES)},
        # E transcrição `azure-speech` exige um detector de turno da família `azure_semantic_vad*`.
        "turn_detection": {"type": "azure_semantic_vad_multilingual", "threshold": 0.3,
                           "prefix_padding_ms": 200, "silence_duration_ms": 500,
                           "languages": VOICE_LOCALES},
        "tools": VOICE_TOOLS,
        "tool_choice": "auto",
        # Precisa ser uma voz *Multilingual*: uma voz mono-idioma fala português com sotaque americano.
        "voice": {"name": os.environ.get("VOICE_LIVE_VOICE", "en-US-AvaMultilingualNeural"),
                  "type": "azure-standard"},
    },
}

print(VOICE_URL)
''')

code(r'''
# Um turno real de Voice Live: conecta, configura a sessão, pergunta, executa a ferramenta, ouve a resposta.
import httpx

async def voice_turn(question: str) -> None:
    audio_bytes = 0
    async with websockets.connect(VOICE_URL, additional_headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
        await ws.send(json.dumps(SESSION_UPDATE))
        # Um microfone enviaria frames input_audio_buffer.append aqui.
        await ws.send(json.dumps({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": question}]}}))
        await ws.send(json.dumps({"type": "response.create"}))

        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=45))
            etype = event["type"]

            if etype == "response.audio.delta":                 # PCM16 em base64 que o navegador toca
                audio_bytes += len(event.get("delta", ""))
            elif etype == "session.updated":
                print("sessão configurada:", event["session"]["model"],
                      "| voz:", event["session"]["voice"]["name"])
            elif etype == "response.function_call_arguments.done":
                args = json.loads(event.get("arguments") or "{}")
                print(f"tool call -> {event['name']}({args})")
                with httpx.Client(base_url=os.environ["ZAVA_API_BASE_URL"].rstrip("/"), timeout=20) as c:
                    result = c.get(f"/orders/{args.get('order_id')}").json()
                await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                    "type": "function_call_output", "call_id": event["call_id"],
                    "output": json.dumps(result)[:1500]}}))
                await ws.send(json.dumps({"type": "response.create"}))
            elif etype == "response.audio_transcript.done":
                print("resposta falada:", event["transcript"])
            elif etype == "error":
                print("erro:", event); break
            elif etype == "response.done":
                if any(i.get("type") == "message" for i in event["response"].get("output", [])):
                    break

    print(f"\náudio recebido: {audio_bytes} caracteres base64 de PCM16 (o navegador toca isso)")

await voice_turn("Where is order 23518?")
''')

md(r"""
### 💡 O que aconteceu

1. O **`session.update`** configurou o modelo realtime: instruções, `pcm16` de entrada/saída, **VAD do lado
   do servidor** (o modelo decide quando o cliente parou de falar), os dois schemas de ferramenta da Zava e a
   voz neural.
2. O modelo decidiu chamar **`lookup_order("23518")`** e transmitiu os argumentos em eventos
   `response.function_call_arguments.delta`.
3. **O seu código executou a ferramenta** contra a API da Zava ao vivo e devolveu como um item
   `function_call_output` — o modelo realtime nunca toca no seu backend diretamente.
4. Um segundo `response.create` produziu a resposta falada: frames `response.audio.delta` (áudio PCM16) mais
   `response.audio_transcript.done` — baseados no registro real do pedido.

No navegador (`webapp/inventory-dashboard`) a única diferença é o caminho do áudio: a página envia os frames
do microfone como `input_audio_buffer.append` e toca os frames `response.audio.delta`, enquanto um relay
WebSocket em FastAPI guarda o token Entra para ele nunca chegar ao cliente.
""")

md(r"""
## 🔄 Recapitulando

Você construiu um agente **hospedado** no Foundry com o **Microsoft Agent Framework**:

| Capacidade | Como |
|---|---|
| Roteamento custo/qualidade | Deployment **Model Router** |
| Dados de pedido ao vivo | Function tool **`lookupOrder`** → API Zava |
| Contexto multi-turno | **Memória de sessão** (`agent.create_session()`) |
| Recall entre sessões | **Foundry Memory** store + **`ContextProvider`** do MAF |
| Hospedagem | `ResponsesHostServer` + `azd deploy` (código direto) |
| Observabilidade | **Traces** + **Evaluations** + **Evaluations Contínuas** (App Insights) |
| UX falada | **Voice-live** (gpt-realtime-mini) |

Junto com o notebook 01 (**InventoryAgent**), você agora tem os dois agentes da Zava — um agente *prompt* e
um agente *hosted* — cobrindo o kit completo: Foundry IQ, ferramentas MCP, Fabric IQ, Model Router, memória
de sessão + de longo prazo, evaluations, web + voz e Teams.

Faça o teardown com `scripts/teardown.ps1` ao terminar.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("Wrote", OUT, "with", len(cells), "cells")
