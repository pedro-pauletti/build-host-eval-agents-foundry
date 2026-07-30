"""Builder for notebooks/01_inventory_agent.pt-BR.ipynb (Portugues do Brasil).

Mesmo codigo do notebook em ingles; apenas a narrativa (markdown) esta em PT-BR,
para que ambos criem exatamente o mesmo agente.
Run: .venv\\Scripts\\python.exe notebooks/_builders/build_inventory_pt.py
"""
import os
import nbformat as nbf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "01_inventory_agent.pt-BR.ipynb")

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))
def code(t): cells.append(nbf.v4.new_code_cell(t.strip("\n")))

md(r"""
# 🧵 Zava · Construindo o **InventoryAgent** no Microsoft Foundry

> **Prompt agent** · SDK do Foundry Agent Service · Base de conhecimento **Foundry IQ** · Ferramentas **MCP** em uma **Toolbox** · **Fabric Data Agent** · Web app (texto + voz) · Teams · Evaluations
>
> 🇺🇸 Uma versão em inglês deste notebook está disponível em `01_inventory_agent.en.ipynb`.

A **Zava** é uma marca fictícia de **vestuário atlético** (coleção *ZavaCore Field*: Core, Pro, Premium,
Elite), vendida direto ao consumidor (B2C). A equipe de operações de inventário — como a persona **Maya**,
gerente de operações de inventário — precisa de respostas rápidas, em linguagem natural, sobre o estoque
distribuído em 7 centros de distribuição.

Neste notebook você vai construir o **InventoryAgent**, um **prompt agent** do Foundry que:

1. Responde perguntas de **política / como-fazer** a partir de uma base de conhecimento **Foundry IQ**,
   com citações.
2. Responde perguntas de **inventário ao vivo** (estoque por SKU, alertas críticos, on-hand por linha de
   produto) chamando o **servidor MCP da Zava**, publicado através de uma **Toolbox** do Foundry.
3. Responde perguntas **analíticas** via um **Fabric Data Agent** sobre o modelo semântico da Zava.
""")

md(r"""
## 🏗️ Arquitetura

```mermaid
flowchart LR
  U[Usuário / Maya<br/>texto + voz] --> INV[InventoryAgent<br/>prompt agent]
  INV -->|política & how-to| KB[Foundry IQ<br/>knowledge base zava-kb]
  KB --> KS[knowledge source<br/>zava-docs-ks]
  KS --> SEARCH[(Azure AI Search<br/>índice zava-docs)]
  INV -->|estoque & pedidos ao vivo| TB[Toolbox<br/>zava-toolbox]
  TB --> MCP[Servidor MCP Zava<br/>Azure Container Apps]
  MCP --> API[APIs REST Zava<br/>FastAPI]
  INV -->|analytics| FAB[Fabric Data Agent<br/>ZavaDataAgent]
  FAB --> SM[(Modelo semântico Fabric)]
  INV --> AI[(App Insights<br/>traces + evals)]
```

**Por que cada peça?**
- O **Foundry IQ** ancora o agente nos *documentos* da Zava. Diferente de consultar um índice de busca cru,
  uma *knowledge base* planeja a consulta, federa fontes e devolve uma **resposta sintetizada com citações**.
- As **ferramentas MCP** dão ao agente dados *estruturados e ao vivo*. O Foundry só aceita endpoints MCP
  **remotos**, então o servidor MCP da Zava roda no **Azure Container Apps** e chama a API REST da Zava.
- Uma **Toolbox** agrupa essas ferramentas MCP em um único endpoint versionado, permitindo trocar
  ferramentas sem re-versionar cada agente que as utiliza.
- O **Fabric Data Agent** permite que o mesmo agente delegue perguntas *analíticas* a um modelo semântico do
  Fabric — perguntas em linguagem natural sobre os dados corporativos.
""")

md(r"""
## ✅ Pré-requisitos

- A infraestrutura da demo já foi provisionada (`scripts/provision.ps1`), os backends implantados
  (`scripts/deploy_backend.ps1`) e a base de conhecimento indexada (`scripts/index_docs.py`).
- Existe um **`.env`** na raiz do repositório com os endpoints dos recursos (criado no provisionamento).
  Nós o carregamos abaixo.
- Você está autenticado: `az login` (o SDK usa `DefaultAzureCredential`).
- Use o ambiente virtual do repositório como kernel do Jupyter (`.venv`).

Instale as bibliotecas cliente (já presentes se você usou o `.venv` do repositório):
""")

code(r"""
# %pip install azure-ai-projects --pre azure-identity openai python-dotenv httpx
import os
from dotenv import load_dotenv

# Carrega os endpoints produzidos pelo provisionamento.
load_dotenv(os.path.join("..", ".env"))

PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
MODEL            = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
SEARCH_CONN      = os.environ.get("AZURE_SEARCH_CONNECTION_NAME", "zava-search")
INDEX            = os.environ.get("AZURE_SEARCH_INDEX_NAME", "zava-docs")
MCP_URL          = os.environ["ZAVA_MCP_URL"]

print("Project :", PROJECT_ENDPOINT)
print("Model   :", MODEL)
print("KB index:", INDEX, "via connection", SEARCH_CONN)
print("MCP     :", MCP_URL)
""")

md(r"""
## 1️⃣ Conecte-se ao projeto Foundry

Tudo passa pelo **`AIProjectClient`** — o ponto de entrada do SDK para um projeto Foundry. Ele usa
`DefaultAzureCredential`, então o mesmo código funciona localmente (`az login`) e em produção (managed
identity).
""")

code(r"""
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())

# A conexão do AI Search foi criada de forma declarativa (infra/modules/connections.bicep).
search_conn = client.connections.get(SEARCH_CONN)
print("AI Search connection id:\n", search_conn.id)
""")

md(r"""
## 2️⃣ A base de conhecimento — **Foundry IQ**

Os documentos da Zava (`data/docs/*.md` — trocas & devoluções, SLA de entrega, tamanhos & cuidados,
política de reposição, visão geral das linhas, FAQ…) foram **fatiados, vetorizados e indexados** em um
índice do Azure AI Search chamado `zava-docs` (veja `scripts/index_docs.py`). O índice tem um campo
`content` pesquisável, um `content_vector` de 3072 dimensões, um **vetorizador** Azure OpenAI integrado e
uma configuração **semântica**.

Mas nós **não** entregamos esse índice cru ao agente. Colocamos o **Foundry IQ** por cima dele.

### Índice cru vs. Foundry IQ

| | `AzureAISearchTool` (índice cru) | **Foundry IQ** (knowledge base) |
|---|---|---|
| Entrada | uma *query* de busca | uma *pergunta* em linguagem natural |
| Planejamento | nenhum — uma query, como escrita | decompõe e reescreve em sub-consultas |
| Fontes | um índice | várias **knowledge sources** federadas |
| Saída | uma lista de trechos que o modelo precisa ler | uma **resposta sintetizada com citações** |
| Ajuste | `top_k`, tipo de query | `retrievalInstructions`, `answerInstructions`, `outputMode` |

O Foundry IQ é implementado pelas **knowledge bases** do Azure AI Search. São dois objetos, ambos no plano
de dados do **serviço de busca** (não no projeto Foundry):

1. uma **knowledge source** (`zava-docs-ks`) — encapsula o índice `zava-docs`,
2. uma **knowledge base** (`zava-kb`) — uma ou mais fontes + um modelo de raciocínio + instruções.

O script `agents/inventory-agent/setup_foundry_iq_and_toolbox.py` cria os dois de forma idempotente:
""")

code(r'''
import httpx
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"].rstrip("/")
SEARCH_API      = "2026-05-01-preview"   # knowledge bases exigem uma api-version 2026+ (preview)
KS_NAME, KB_NAME = "zava-docs-ks", "zava-kb"

hdr = {"Authorization": "Bearer " + DefaultAzureCredential()
                                      .get_token("https://search.azure.com/.default").token,
       "Content-Type": "application/json"}

# 1) knowledge source — `searchIndexName` é o único parâmetro obrigatório
httpx.put(f"{SEARCH_ENDPOINT}/knowledgeSources/{KS_NAME}?api-version={SEARCH_API}", headers=hdr,
          json={"name": KS_NAME, "kind": "searchIndex",
                "searchIndexParameters": {"searchIndexName": INDEX}}, timeout=90).raise_for_status()

# 2) knowledge base — fontes + modelo de raciocínio + como recuperar e como responder
httpx.put(f"{SEARCH_ENDPOINT}/knowledgeBases/{KB_NAME}?api-version={SEARCH_API}", headers=hdr, json={
    "name": KB_NAME,
    "description": "Manual de operações oficial da Zava. FONTE AUTORITATIVA de políticas e regras.",
    "knowledgeSources": [{"name": KS_NAME}],
    "models": [{"kind": "azureOpenAI", "azureOpenAIParameters": {
        "resourceUri": f"https://{os.environ['FOUNDRY_ACCOUNT_NAME']}.openai.azure.com",
        "deploymentId": MODEL, "modelName": MODEL}}],
    "retrievalInstructions": "O corpus é o manual interno de operações da Zava…",
    "answerInstructions":    "Responda apenas com base nos documentos e sempre cite o título do documento.",
    "outputMode": "answerSynthesis",   # devolve uma resposta escrita, não apenas trechos
}, timeout=90).raise_for_status()

print("Knowledge base Foundry IQ pronta:", KB_NAME)
''')

md(r"""
### Como um agente consome o Foundry IQ

**Não** existe um `KnowledgeBaseTool` dedicado. Uma knowledge base publica o seu próprio **endpoint MCP**:

```
https://<servico-de-busca>.search.windows.net/knowledgeBases/<kb>/mcp?api-version=2026-05-01-preview
```

…expondo uma única ferramenta, **`knowledge_base_retrieve`**. O agente se conecta com um `MCPTool` normal.

Dois detalhes que custam horas se você errar:

- o argumento é **`queries`** — um **array** JSON com uma pergunta completa em linguagem natural (não `query`);
- para não guardar um token na definição do agente, crie uma **conexão `RemoteTool`** com
  `authType: ProjectManagedIdentity` e `audience: "https://search.azure.com/"`. O `audience` precisa ser uma
  propriedade **de primeiro nível** — dentro de `metadata` ele vira `null` silenciosamente e você recebe 401.
""")

code(r'''
KB_MCP_URL = f"{SEARCH_ENDPOINT}/knowledgeBases/{KB_NAME}/mcp?api-version={SEARCH_API}"

r = httpx.post(KB_MCP_URL,
    headers={**hdr, "Accept": "application/json, text/event-stream"},
    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
          "params": {"name": "knowledge_base_retrieve",
                     "arguments": {"queries": ["Qual é o prazo de devolução da Zava?"]}}},
    timeout=120)
print(r.text[:500])   # -> uma resposta sintetizada COM citação [ref_id / source]
''')

md(r"""
## 3️⃣ As ferramentas — o **servidor MCP da Zava**

O **Model Context Protocol (MCP)** é um padrão aberto para expor ferramentas a LLMs. O servidor MCP da Zava
(`services/zava-mcp`, implantado no Azure Container Apps) encapsula a API REST da Zava e expõe ferramentas
como `get_product_stock`, `get_inventory_alerts`, `get_inventory_summary`, `get_line_stock`,
`list_products`, `lookup_order` e `track_shipment`.

Como o Foundry só aceita endpoints MCP **remotos**, o servidor está acessível em `ZAVA_MCP_URL`
(`https://…/mcp`). Vamos listar suas ferramentas diretamente via MCP para ver o que o agente poderá chamar:
""")

code(r"""
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

async def list_mcp_tools(url):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            return [(t.name, (t.description or "").split("\n")[0]) for t in tools]

for name, desc in await list_mcp_tools(MCP_URL):
    print(f"• {name:22s} {desc}")
""")

md(r"""
### Agrupando ferramentas em uma **Toolbox**

Anexar servidores MCP um a um em cada agente não escala: cada definição repete todas as URLs, labels e
conexões, e adicionar uma ferramenta exige re-versionar todos os agentes.

Uma **toolbox** é um *pacote nomeado e versionado* de ferramentas publicado em um único endpoint MCP:

```
{project_endpoint}/toolboxes/{name}/mcp?api-version=v1
```

Os agentes se conectam a esse endpoint único com um `MCPTool` normal. Dentro dela, as ferramentas recebem
o namespace `<server_label>___<tool_name>` (três underscores), ex.: `zava_tools___get_inventory_alerts`.

Toolboxes são **versionadas**: `POST /toolboxes/{name}/versions` acrescenta uma versão, e o endpoint MCP
serve a `default_version` — então é preciso **promover** a nova versão com `PATCH /toolboxes/{name}` para
que os agentes a enxerguem. É exatamente isso que torna a toolbox útil: você troca ferramentas por baixo de
uma frota de agentes sem tocar em nenhuma definição de agente.
""")

code(r'''
PROJECT = PROJECT_ENDPOINT.rstrip("/")
TOOLBOX = "zava-toolbox"
phdr = {"Authorization": "Bearer " + DefaultAzureCredential()
                                       .get_token("https://ai.azure.com/.default").token,
        "Content-Type": "application/json"}

body = {
    "name": TOOLBOX,
    "description": "Toolbox de operações da Zava: ferramentas ao vivo + knowledge base Foundry IQ.",
    "tools": [
        {"type": "mcp", "server_label": "zava_tools", "server_url": MCP_URL,
         "server_description": "Inventário, alertas, KPIs e produtos da Zava ao vivo.",
         "require_approval": "never"},
        {"type": "mcp", "server_label": "zava_kb", "server_url": KB_MCP_URL,
         "server_description": "Knowledge base Foundry IQ — autoritativa para políticas da Zava.",
         "allowed_tools": ["knowledge_base_retrieve"], "require_approval": "never",
         "project_connection_id": "zava-kb-mcp"},          # NOME da conexão, não um id ARM
    ],
}

exists = httpx.get(f"{PROJECT}/toolboxes/{TOOLBOX}?api-version=v1", headers=phdr).status_code == 200
url = f"{PROJECT}/toolboxes/{TOOLBOX}/versions?api-version=v1" if exists else f"{PROJECT}/toolboxes?api-version=v1"
version = str(httpx.post(url, headers=phdr, json=body, timeout=120).json()["version"])

# Promova a versão, senão o endpoint MCP continua servindo a default_version anterior.
httpx.patch(f"{PROJECT}/toolboxes/{TOOLBOX}?api-version=v1", headers=phdr,
            json={"default_version": version}, timeout=60).raise_for_status()

tools_listed = httpx.post(f"{PROJECT}/toolboxes/{TOOLBOX}/mcp?api-version=v1",
    headers={**phdr, "Accept": "application/json, text/event-stream"},
    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, timeout=90)
print("toolbox versão", version)
print(tools_listed.text[:400])
''')

md(r"""
## 4️⃣ Crie o **InventoryAgent** (prompt agent)

Um **prompt agent** é definido por um `PromptAgentDefinition`: um modelo, instruções e uma lista de
ferramentas. Nosso conjunto final é propositalmente pequeno — a *toolbox* faz o agrupamento:

| Ferramenta | Para quê |
|---|---|
| `MCPTool` → **`zava-toolbox`** | inventário / pedidos ao vivo (`zava_tools___*`) |
| `MCPTool` → **`zava-kb`** (Foundry IQ) | respostas de política com citações |
| `MicrosoftFabricPreviewTool` | analytics histórico via **Fabric Data Agent** |

Aprendizados de construir isso de verdade:

- A **autenticação** usa `project_connection_id` = o **nome** de uma conexão `RemoteTool`. A managed
  identity **do projeto** chama o endpoint — nenhum token na definição do agente. Atenção: a MI do
  **projeto** é um principal diferente da MI da **conta**, e é a do projeto que precisa de
  `Foundry User` / `Azure AI Developer` na conta e `Search Index Data Reader` no serviço de busca.
- O **Foundry IQ é anexado diretamente ao agente além de estar na toolbox.** No preview atual a ferramenta
  aninhada da knowledge base é silenciosamente omitida do `mcp_list_tools` quando a toolbox é enumerada
  pela MI do projeto; o binding direto é o que de fato a torna chamável.
- A ferramenta do **Fabric Data Agent não pode ficar em uma toolbox** — `ToolboxToolType` só expõe
  `fabric_iq_preview`, e não o tipo `fabric_dataagent_preview` que usamos.
- ⚠️ **Uma única ferramenta com endpoint falhando quebra TODAS as requisições ao agente**, mesmo perguntas
  que nunca a usariam. O Foundry resolve todos os endpoints MCP a cada chamada. Sempre teste após adicionar.

Boas **instruções** são o que tornam o roteamento confiável — repare na *regra dura de roteamento* que
força perguntas de política para o Foundry IQ, em vez de deixar o modelo inferir política de números ao vivo.

> 🧪 **Nota da demo:** criamos o agente com um **nome separado** (`InventoryAgent-Demo`) para que este
> passo a passo **não** altere o **`InventoryAgent`** de produção que já alimenta o web app e o Teams. As
> ferramentas e instruções são idênticas — só o nome muda. Remova quando quiser com
> `client.agents.delete("InventoryAgent-Demo")`.
""")

code(r'''
from azure.ai.projects.models import (
    PromptAgentDefinition, MCPTool,
)

INSTRUCTIONS = """You are InventoryAgent, the operations copilot for Zava — a DTC athletic apparel brand
(ZavaCore Field: Core, Pro, Premium, Elite; Tops/Tees, Shorts, Pants; sizes S/M/L/XL). Inventory is stored
across 7 distribution centers (Memphis, Charlotte, Seattle, Dallas, Newark, Reno, Columbus).

Tool routing:
1. zava_kb___knowledge_base_retrieve (Foundry IQ) — ANY policy, procedure or rule question: returns &
   exchanges, shipping SLAs, reorder policy, sizing/fabric care, supplier onboarding. Quote the citation.
2. zava_tools___* — live operational data: get_product_stock, get_inventory_alerts, get_line_stock,
   get_inventory_summary, list_products, lookup_order, track_shipment.
3. Fabric Data Agent — historical/aggregate analytics: revenue by product line, sales trends, comparisons.

HARD ROUTING RULE: if the question contains policy, procedure, rule, threshold, SLA, window, eligible,
return, exchange, refund, sizing, care or supplier — call zava_kb___knowledge_base_retrieve FIRST and
answer from its result. Live numbers are NOT documented policy; never infer one from the other.

Be concise and lead with the number/answer. Name facilities and SKUs. For critical stock, say how many
alerts exist and call out the MOST URGENT first. Never invent SKUs, quantities, or policies.

Formatting: reply in GitHub-flavored Markdown. When listing multiple items with attributes, use a compact
Markdown table with clear headers; use bold for key numbers and cite the source for policy answers."""

tools = [
    MCPTool(server_label="zava_toolbox",
            server_url=f"{PROJECT}/toolboxes/{TOOLBOX}/mcp?api-version=v1",
            require_approval="never", project_connection_id="zava-toolbox-mcp"),
    MCPTool(server_label="zava_kb", server_url=KB_MCP_URL, require_approval="never",
            allowed_tools=["knowledge_base_retrieve"], project_connection_id="zava-kb-mcp"),
]
# (a ferramenta do Fabric Data Agent é adicionada na seção 6)

# Use um nome DISTINTO para que esta demo NÃO sobrescreva o "InventoryAgent" de produção
# que alimenta o web app / Teams. Altere livremente nas suas execuções.
AGENT_NAME = "InventoryAgent-Demo"

agent = client.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(model=MODEL, instructions=INSTRUCTIONS, tools=tools),
)
print("Agente criado:", agent.name, "versão", getattr(agent, "version", "?"))
''')

md(r"""
## 5️⃣ Converse com o agente

Invocamos o agente pela **Responses API** compatível com OpenAI exposta pelo projeto
(`client.get_openai_client()`), passando um `agent_reference`. O agente executa o loop de tool-calling
automaticamente: decide chamar as ferramentas MCP ou a KB do AI Search e então compõe a resposta final.

Teste os três cenários canônicos (que correspondem à UI de referência):
""")

code(r'''
oai = client.get_openai_client()

def ask(question: str):
    resp = oai.responses.create(
        model=MODEL,
        input=question,
        extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
    )
    print("P:", question)
    print("R:", resp.output_text, "\n")

ask("What are my most critical stock issues right now?")              # -> MCP get_inventory_alerts
ask("How many units of ZCPTM-SS-S-B0 do we have across facilities?")  # -> MCP get_product_stock
ask("What's our return policy for worn or opened apparel?")           # -> KB (Azure AI Search) com citação
''')

md(r"""
### 💡 O que aconteceu

- *"most critical stock issues"* → o agente chamou **`get_inventory_alerts`** no servidor MCP da Zava, que
  leu o inventário ao vivo da API da Zava e resumiu os itens mais urgentes (0 em estoque primeiro).
- *"how many units of ZCPTM-SS-S-B0"* → **`get_product_stock`** retornou a distribuição por centro.
- *"return policy for worn apparel"* → o agente chamou **`knowledge_base_retrieve`** na knowledge base
  **Foundry IQ**, que planejou a consulta, recuperou de `zava-docs` e devolveu uma resposta sintetizada
  **com citação** — com base nos dados, sem alucinar.

O mesmo agente atende perguntas **não estruturadas** (documentos) e **estruturadas/ao vivo** (API).
""")

md(r"""
### 🔍 Rastreando o que o agente realmente fez

`resp.output_text` é só a última linha da história. A **lista `resp.output` é o trace**: cada listagem de
ferramentas, cada chamada MCP com argumentos e resultado bruto, cada citação e o uso de tokens. Para um
*prompt agent* essa é a superfície de observabilidade — o serviço roda o loop e devolve exatamente o que
executou.

| Tipo de item | O que significa |
|---|---|
| `mcp_list_tools` | o agente descobriu as ferramentas de um servidor MCP (`server_label`) |
| `mcp_call` | uma invocação de ferramenta: `name`, `arguments`, `output`, `error`, `status` |
| `message` | a resposta final, com `annotations` carregando as citações da knowledge base |

São os mesmos dados que o web app renderiza no painel **Traces** e que a aba **Tracing** do portal do Foundry
mostra para cada execução.
""")

code(r'''
import json

oai = client.get_openai_client()

def trace_run(question: str):
    """Executa o agente e imprime o trace completo a partir dos itens da resposta."""
    resp = oai.responses.create(
        model=MODEL,
        input=question,
        extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
    )
    print("Q:", question, "\n")
    for item in resp.output or []:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        kind = data.get("type")

        if kind == "mcp_list_tools":
            names = [t.get("name") for t in data.get("tools", [])]
            print(f"[tools ] {data.get('server_label'):<14s} {len(names)} tools: {', '.join(names[:4])}…")

        elif kind == "mcp_call":
            status = "ERROR" if data.get("error") else data.get("status", "ok")
            print(f"[call  ] {data.get('name')}  ({status})")
            print(f"         args   : {data.get('arguments')}")
            print(f"         result : {str(data.get('output') or '')[:160]}")

        elif kind == "message":
            for content in data.get("content", []):
                for note in content.get("annotations") or []:
                    print(f"[cite  ] {note.get('title') or note.get('file_id') or note}")
            print(f"[answer] {str(data.get('content', [{}])[0].get('text', ''))[:220]}…")

    usage = resp.usage
    print(f"\n[usage ] in={usage.input_tokens} out={usage.output_tokens} total={usage.total_tokens}"
          f"  (cached={usage.input_tokens_details.cached_tokens})")
    return resp

resp = trace_run("Which SKUs are critical at Charlotte?")
''')

md(r"""
> **Leia o trace e ache o bug.** Na execução acima o agente chamou
> `get_inventory_alerts(facility="Charlotte", severity="critical")` e recebeu `{"alerts": []}` — então
> respondeu *"nenhum alerta crítico em Charlotte"*. Mas a API da Zava indexa os centros por **código**
> (`FC-CLT`), não por cidade, então o filtro não casou com nada silenciosamente. Sem o trace a resposta
> parece confiante e correta; com ele, a correção é óbvia (ensinar os códigos de facility nas instruções, ou
> fazer a ferramenta aceitar os dois). É exatamente a falha que o avaliador `zava_answer_grounding` pega na
> seção 9.

**Onde os traces ficam em produção**

| Superfície | O que você obtém |
|---|---|
| Portal do Foundry → **Tracing** | cada execução do agente, com as mesmas chamadas de ferramenta e citações, pesquisável |
| Application Insights | os spans crus quando a aplicação está instrumentada com OTel (veja o notebook 02 para o `configure_otel_providers()` e uma query KQL sobre `dependencies`) |
| Painel **Traces** do web app | `webapp/inventory-dashboard` renderiza `resp.output` ao vivo, uma linha por item |
""")

md(r"""
## 6️⃣ Analytics — o **Fabric Data Agent**

Para perguntas *analíticas* ("Como as vendas da linha Elite deste mês se comparam ao mês passado?", "Qual é
a receita por linha de produto?"), os dados estruturados da Zava (`data/structured/`) são carregados em um
**lakehouse do Microsoft Fabric** e em um **modelo semântico**, e um **Fabric Data Agent** (`ZavaDataAgent`)
é publicado sobre eles (veja `data/semantic-model/create_data_agent.py`). Ele traduz linguagem natural em
DAX e devolve o resultado — sem SQL, sem consultas escritas à mão.

Existem **dois tipos diferentes de ferramenta Fabric** no SDK, e escolher o errado custa um dia:

| | `FabricIQPreviewTool` (`fabric_iq_preview`) | **`MicrosoftFabricPreviewTool`** (`fabric_dataagent_preview`) |
|---|---|---|
| Configuração | `server_url` + conexão | `project_connections: [{project_connection_id}]` |
| Conexão | conexão Fabric/AAD | conexão **CustomKeys** com `metadata.type = "fabric_dataagent_preview"` |
| Auth | exige token *delegado de usuário* → app Entra + consentimento do admin | funciona só com a conexão |
| Resultado aqui | **401** | ✅ funciona |

Usamos o segundo. A conexão `fabric_zava_dataagent` é criada no portal do Foundry (ferramenta *Data Agent*
no agente) ou via ARM; o `create_agent.py` apenas a referencia pelo nome.
""")

code(r'''
from azure.ai.projects.models import (
    MicrosoftFabricPreviewTool, FabricDataAgentToolParameters,
)

fabric_tool = MicrosoftFabricPreviewTool(
    fabric_dataagent_preview=FabricDataAgentToolParameters(
        project_connections=[{"project_connection_id": "fabric_zava_dataagent"}]
    )
)

client.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(model=MODEL, instructions=INSTRUCTIONS,
                                     tools=tools + [fabric_tool]),
)

print(ask("Qual é a receita total por linha de produto?"))
''')

md(r"""
## 7️⃣ O web app — texto + **voz** + dashboard

`webapp/inventory-dashboard/` hospeda a experiência mostrada no topo: um painel de chat (texto **e voz**,
usando a API **Azure AI Foundry Voice Live** com o deployment `gpt-realtime-mini`) ao lado de um dashboard de
inventário ao vivo. O dashboard lê KPIs e cards de produto da **API da Zava** (`/inventory/summary`,
`/product-lines`, `/inventory/alerts`), e o chat conversa com este **InventoryAgent**.

Execute localmente seguindo `webapp/inventory-dashboard/README.md`. O caminho de voz está documentado lá; a
ativação final do Voice Live pode exigir habilitar o preview no seu tenant.
""")

md(r"""
## 8️⃣ Publicar no Microsoft **Teams**

O Foundry pode publicar um prompt agent no **Teams** (provisiona um Azure Bot + um app M365). Como isso exige
Microsoft 365 e **consentimento do admin do tenant**, é um passo guiado/manual:

1. No [portal do Foundry](https://ai.azure.com) → seu projeto → **InventoryAgent** → **Publish → Teams**.
2. Aprove o registro do Azure Bot + app M365 (consentimento de admin).
3. Instale o pacote do app do Teams gerado para o seu time.

> Observação: o **repasse de identidade do MCP não é suportado no Teams** — o agente usa a managed identity
> do projeto ao chamar ferramentas. Isso é adequado para as ferramentas da Zava, que autorizam no nível do serviço.
""")

md(r"""
## 9️⃣ Evaluations — **built-in**, **custom** e **rubric**

Um agente vale o quanto você consegue medir dele. O Microsoft Foundry executa evaluations **como serviço**:
você descreve os dados, lista os *testing criteria*, e o serviço gera as respostas, pontua e guarda tudo no
seu projeto — então os resultados aparecem no **portal do Foundry → Evaluations** (e na aba *Evaluations* do
web app), não apenas no seu terminal.

Três tipos de avaliador, todos usáveis na mesma execução:

| Tipo | O que é | Use para |
|---|---|---|
| **Built-in** | Avaliadores curados pela Microsoft, referenciados por nome (`builtin.relevance`, `builtin.intent_resolution`, `builtin.task_adherence`, `builtin.violence`, …) | qualidade, comportamento de agente, segurança — a linha de base |
| **Custom** | Seu próprio avaliador registrado no catálogo do projeto: **code-based** (uma função Python `grade()` em sandbox) ou **prompt-based** (um prompt de juiz LLM) | checagens determinísticas de fatos, regras de domínio, estilo da casa |
| **Rubric** | Critérios ponderados (`dimensions`) que um juiz LLM pontua de 1 a 5 cada, normalizados para 0–1 | "o que significa *bom* para **este** agente" |

Uma avaliação na nuvem sempre tem os mesmos três passos:

1. **Definir** — um `data_source_config` (o formato das linhas) + `testing_criteria` (os avaliadores).
2. **Criar** — `openai_client.evals.create(...)` devolve uma *evaluation* (um contêiner de execuções).
3. **Executar** — `openai_client.evals.runs.create(...)` aponta para os dados e, opcionalmente, para um
   **target** (um modelo ou um agente) que gera as respostas a serem pontuadas.

Usamos um **agent target**: o Foundry envia cada pergunta ao InventoryAgent ao vivo, captura a resposta
*incluindo as chamadas de ferramenta MCP*, e pontua isso.
""")

code(r'''
# O dataset de avaliação: 10 perguntas reais da Zava com ground truth + os fatos que a resposta deve conter.
# (agents/inventory-agent/evals/inventory_eval.jsonl — 6 perguntas de ferramenta, 4 de knowledge base)
import json

EVAL_DATASET = os.path.join("..", "agents", "inventory-agent", "evals", "inventory_eval.jsonl")
rows = [json.loads(line) for line in open(EVAL_DATASET, encoding="utf-8") if line.strip()]
print(f"{len(rows)} linhas; primeira linha:")
print(json.dumps(rows[0], indent=2)[:400])

# Datasets são artefatos versionados do projeto, reutilizáveis entre execuções e visíveis no portal.
# Versões são imutáveis, então incrementamos até achar uma livre (reexecutar a célula continua simples).
def upload_dataset(name, file_path):
    last = None
    for version in range(1, 50):
        try:
            return client.datasets.upload_file(name=name, version=str(version), file_path=file_path)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"não foi possível subir {name}: {last}")

dataset = upload_dataset("zava-inventory-eval", EVAL_DATASET)
print("\ndataset id:", dataset.id)
''')

md(r"""
### 9️⃣.1 Avaliadores **built-in**

Referencie-os pelo nome em um `TestingCriterionAzureAIEvaluator`. Dois pontos importam:

- **`data_mapping`** conecta seus dados às entradas do avaliador. `{{item.<campo>}}` lê a linha do dataset;
  `{{sample.output_text}}` é o texto final do agente e `{{sample.output_items}}` é a saída estruturada
  *completa* (mensagens **e** chamadas de ferramenta) — avaliadores de agente querem a segunda.
- **`initialization_parameters`** carrega o modelo juiz (`deployment_name`) e um `threshold` opcional.
  Avaliadores de segurança como `builtin.violence` rodam no serviço de Content Safety e não precisam de modelo.
""")

code(r'''
from azure.ai.projects.models import TestingCriterionAzureAIEvaluator

JUDGE = MODEL   # gpt-4.1 — o juiz LLM dos avaliadores assistidos por IA

builtin_criteria = [
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="relevance", evaluator_name="builtin.relevance",
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_text}}"},
    ),
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="intent_resolution", evaluator_name="builtin.intent_resolution",
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_items}}"},
    ),
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="task_adherence", evaluator_name="builtin.task_adherence",
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_items}}"},
    ),
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="violence", evaluator_name="builtin.violence",
        initialization_parameters={},        # avaliador de segurança de serviço: sem modelo juiz
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_text}}"},
    ),
]

# O catálogo completo disponível no seu projeto:
for e in client.beta.evaluators.list(type="builtin"):
    print(" ", e.name)
''')

md(r"""
### 9️⃣.2 Avaliador **custom — code-based**

Um avaliador code-based é uma função Python `grade(sample, item) -> float` (0.0–1.0, maior é melhor) que o
Foundry roda em um **sandbox**: sem rede, 2 minutos e 2 GB por chamada, com numpy/pandas/rapidfuzz
disponíveis. Perfeito para as checagens que um juiz LLM nunca deveria fazer — números exatos, formatos, IDs.

O nosso responde a uma pergunta que nenhum avaliador genérico responde: *o agente realmente reportou os fatos
da Zava?* Cada linha traz uma lista `must_include` (alternativas separadas por `|`), e a nota é a fração
encontrada.

> Em uma avaliação de **dataset** você lê `item["response"]`; com um **target** de modelo/agente o texto
> gerado chega em `item["sample"]["output_text"]`. O código abaixo trata os dois casos.
""")

code(r'''
from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

ANSWER_GROUNDING_CODE = """
def grade(sample: dict, item: dict) -> float:
    # Fracao dos fatos exigidos da Zava que aparecem na resposta.
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

code_evaluator = client.beta.evaluators.create_version(
    name="zava_answer_grounding",
    evaluator_version={
        "name": "zava_answer_grounding",
        "categories": [EvaluatorCategory.QUALITY],
        "display_name": "Zava Answer Grounding",
        "description": "Fração dos fatos exigidos da Zava presentes na resposta (determinístico).",
        "definition": {
            "type": EvaluatorDefinitionType.CODE,
            "code_text": ANSWER_GROUNDING_CODE,
            "init_parameters": {
                "type": "object",
                "properties": {"deployment_name": {"type": "string"}, "pass_threshold": {"type": "number"}},
                "required": ["deployment_name", "pass_threshold"],
            },
            "metrics": {"result": {"type": "continuous", "desirable_direction": "increase",
                                   "min_value": 0.0, "max_value": 1.0}},
            "data_schema": {
                "type": "object", "required": ["item"],
                "properties": {"item": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "ground_truth": {"type": "string"},
                    "must_include": {"type": "array"},
                }}},
            },
        },
    },
)
print("registrado:", code_evaluator.name, "v" + str(code_evaluator.version))
''')

md(r"""
### 9️⃣.3 Avaliador **custom — prompt-based**

Mesmo catálogo, motor diferente: em vez de Python você fornece um **prompt de juiz**. As variáveis do
template usam `{{chaves_duplas}}` e são ligadas aos seus dados pelo `data_mapping`. O prompt precisa
retornar `{"result": <nota>, "reason": "<por quê>"}` — ordinal (1–5 aqui), contínuo ou binário.

Use para os julgamentos que código não faz. O nosso codifica o estilo da casa da Zava: *isto é um briefing
que a Maya consegue acionar em pé no armazém?*
""")

code(r'''
OPS_BRIEFING_PROMPT = """You grade answers written for Maya, a Zava inventory operations manager
who is standing on a warehouse floor. A great answer is a short operational briefing: it leads with
the number or status that matters, names the facility or SKU it refers to, and ends with the action
to take. A poor answer is a wall of prose, hedges without numbers, or buries the decision.

Rate the answer between one and five:

1 - Unusable: no numbers, no entities, or off-topic.
2 - Vague: mentions the topic but gives no actionable figures or entities.
3 - Acceptable: correct and readable, but padded or missing the next action.
4 - Good: concise, quantified, names SKUs/facilities, minor padding.
5 - Excellent: leads with the decisive number, names SKUs/facilities, states the next action, no filler.

Question:
{{query}}

Answer:
{{response}}

Output Format (JSON):
{
  "result": <integer from 1 to 5>,
  "reason": "<one sentence explaining the score>"
}
"""

prompt_evaluator = client.beta.evaluators.create_version(
    name="zava_ops_briefing",
    evaluator_version={
        "name": "zava_ops_briefing",
        "categories": [EvaluatorCategory.QUALITY],
        "display_name": "Zava Ops Briefing Quality",
        "description": "Juiz LLM: a resposta é um briefing operacional conciso e quantificado (1-5)?",
        "definition": {
            "type": EvaluatorDefinitionType.PROMPT,
            "prompt_text": OPS_BRIEFING_PROMPT,
            "init_parameters": {
                "type": "object",
                "properties": {"deployment_name": {"type": "string"}, "threshold": {"type": "number"}},
                "required": ["deployment_name", "threshold"],
            },
            "data_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "response": {"type": "string"}},
                "required": ["query", "response"],
            },
            "metrics": {"custom_prompt": {"type": "ordinal", "desirable_direction": "increase",
                                          "min_value": 1, "max_value": 5}},
        },
    },
)
print("registrado:", prompt_evaluator.name, "v" + str(prompt_evaluator.version))
''')

md(r"""
### 9️⃣.4 Avaliador **rubric**

Uma rubrica é um conjunto de **dimensões** ponderadas; um juiz LLM pontua cada dimensão aplicável de 1 a 5 e
a nota final é a média ponderada normalizada para 0–1, com uma justificativa por dimensão. Essa é a medida
*primária* recomendada de qualidade de agente, porque explicita os seus critérios.

Você pode escrever a rubrica à mão (abaixo) ou **gerá-la** a partir do contexto do próprio agente — o Foundry
lê as instruções e ferramentas do agente e propõe as dimensões. Defina `GENERATE_RUBRIC = True` para testar
esse caminho (roda um job de LLM e leva alguns minutos).
""")

code(r'''
GENERATE_RUBRIC = False   # True -> deixa o Foundry propor as dimensões a partir das instruções do agente

INVENTORY_RUBRIC_DIMENSIONS = [
    {"id": "source_routing", "weight": 9, "description":
     "Routes the question to the right source: live stock/alert questions call the Zava MCP toolbox, "
     "policy/how-to questions use the Foundry IQ knowledge base."},
    {"id": "numeric_fidelity", "weight": 8, "description":
     "Every quantity, SKU, facility code and status comes from a tool or knowledge-base result. "
     "No invented or rounded-away numbers."},
    {"id": "operational_completeness", "weight": 5, "description":
     "Answers the whole question: on-hand versus reorder point, the facility breakdown when asked, "
     "and the affected SKUs rather than only a count."},
    {"id": "citation_discipline", "weight": 4, "description":
     "Policy answers cite the Zava document they came from; tool answers make clear the data is live."},
    {"id": "briefing_clarity", "weight": 3, "description":
     "Concise and scannable: leads with the decisive number and closes with the recommended action."},
    {"id": "general_quality", "weight": 5, "always_applicable": True, "description":
     "Other important quality factors not covered by the listed criteria."},
]

if GENERATE_RUBRIC:
    import time
    from azure.ai.projects.models import (
        AgentEvaluatorGenerationJobSource, EvaluatorGenerationInputs, EvaluatorGenerationJob, JobStatus,
    )
    job = client.beta.evaluators.create_generation_job(job=EvaluatorGenerationJob(
        inputs=EvaluatorGenerationInputs(
            model=JUDGE,
            evaluator_name="zava_inventory_rubric",
            evaluator_display_name="Zava Inventory Quality (generated)",
            sources=[AgentEvaluatorGenerationJobSource(agent_name=AGENT_NAME)],
        )))
    while job.status not in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
        time.sleep(10)
        job = client.beta.evaluators.get_generation_job(job.id)
    rubric = job.result
else:
    rubric = client.beta.evaluators.create_version(
        name="zava_inventory_rubric",
        evaluator_version={
            "name": "zava_inventory_rubric",
            "categories": [EvaluatorCategory.AGENTS],
            "display_name": "Zava Inventory Quality",
            "description": "Critérios ponderados de qualidade para respostas de inventário da Zava.",
            "definition": {
                "type": EvaluatorDefinitionType.RUBRIC,
                "dimensions": INVENTORY_RUBRIC_DIMENSIONS,
                "pass_threshold": 0.6,
            },
        },
    )

print("rubrica:", rubric.name, "v" + str(rubric.version))
for d in rubric.definition.dimensions:
    print(f"  - {d.id} (peso {d.weight})")
''')

md(r"""
### 9️⃣.5 Executando contra o agente ao vivo

Agora os três tipos entram em **uma única** lista `testing_criteria`. A execução usa
`azure_ai_target_completions` com um target `azure_ai_agent`, então o próprio Foundry chama o agente para
cada linha antes de pontuar — sem coleta de respostas do seu lado.
""")

code(r'''
from openai.types.eval_create_params import DataSourceConfigCustom

testing_criteria = builtin_criteria + [
    # custom, code-based (sem data_mapping: o item inteiro é passado para grade())
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="answer_grounding", evaluator_name="zava_answer_grounding",
        initialization_parameters={"deployment_name": JUDGE, "pass_threshold": 0.99}, data_mapping={},
    ),
    # custom, prompt-based (propositalmente rígido: precisa de 4/5 para passar)
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="ops_briefing", evaluator_name="zava_ops_briefing",
        initialization_parameters={"deployment_name": JUDGE, "threshold": 4},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_text}}"},
    ),
    # rubric
    TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator", name="inventory_rubric", evaluator_name=rubric.name,
        initialization_parameters={"deployment_name": JUDGE},
        data_mapping={"query": "{{item.query}}", "response": "{{sample.output_items}}"},
    ),
]

evaluation = oai.evals.create(
    name="Zava InventoryAgent quality",
    data_source_config=DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ground_truth": {"type": "string"},
                "must_include": {"type": "array"},
                "expected_tool": {"type": "string"},
            },
            "required": ["query"],
        },
        include_sample_schema=True,     # expõe {{sample.output_text}} / {{sample.output_items}}
    ),
    testing_criteria=testing_criteria,
)

eval_run = oai.evals.runs.create(
    eval_id=evaluation.id,
    name="inventory-builtin-custom-rubric",
    data_source={
        "type": "azure_ai_target_completions",
        "source": {"type": "file_id", "id": dataset.id},
        "input_messages": {"type": "template", "template": [
            {"type": "message", "role": "user", "content": {"type": "input_text", "text": "{{item.query}}"}},
        ]},
        "target": {"type": "azure_ai_agent", "name": AGENT_NAME},
    },
)
print("evaluation:", evaluation.id)
print("run       :", eval_run.id)
''')

code(r'''
# Faz polling até a execução terminar e lê o placar agregado.
import time

while True:
    run = oai.evals.runs.retrieve(run_id=eval_run.id, eval_id=evaluation.id)
    if str(run.status) in ("completed", "failed", "canceled"):
        break
    print("status:", run.status)
    time.sleep(10)

counts = run.result_counts
print(f"\nstatus={run.status}  linhas: {counts.passed}/{counts.total} aprovadas\n")
for c in run.per_testing_criteria_results:
    total = c.passed + c.failed
    print(f"  {c.testing_criteria:<22s} pass {c.passed:>2d}  fail {c.failed:>2d}   "
          f"{(c.passed / total if total else 0):.0%}")

print("\nAbra no portal do Foundry:\n", run.report_url)
''')

code(r'''
# Detalhe por linha: o que cada avaliador disse sobre cada resposta.
for item in list(oai.evals.runs.output_items.list(run_id=eval_run.id, eval_id=evaluation.id))[:3]:
    source = item.datasource_item or {}
    print("Q:", str(source.get("query"))[:90])
    for result in item.results:
        data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        print(f"   {data.get('name'):<20s} score={data.get('score')!s:<8s} {data.get('label')}"
              f"  {(data.get('reason') or '')[:100]}")
    print()
''')

md(r"""
### 💡 O que você acabou de fazer

- Subiu um **dataset versionado** para o projeto e apontou uma avaliação para o **agente ao vivo** como target.
- Pontuou cada resposta com avaliadores **built-in** (relevância, resolução de intenção, aderência à tarefa,
  violência), avaliadores **custom** — um code-based (`zava_answer_grounding`, checagem determinística de
  fatos) e um prompt-based (`zava_ops_briefing`, um juiz LLM para o estilo da casa) — e uma **rubrica** com
  dimensões ponderadas e justificativa por dimensão.
- Tudo vive no projeto: abra `run.report_url` para a visão do **portal do Foundry**, ou a aba
  **Evaluations** do web app (`webapp/inventory-dashboard`), que lê exatamente as mesmas execuções via
  `GET /api/evals`.

O fluxo completo está scriptado em `agents/inventory-agent/run_eval.py`:

```powershell
.\.venv\Scripts\python.exe agents/inventory-agent/run_eval.py            # todas as 10 linhas
.\.venv\Scripts\python.exe agents/inventory-agent/run_eval.py --limit 3  # execução rápida
```

> **Próximos passos no portal:** agende a mesma avaliação, ou transforme-a em **evaluation contínua** para
> que uma amostra do tráfego de produção seja pontuada automaticamente e regressões de qualidade apareçam
> em um dashboard.
""")

md(r"""
## 🔄 Recapitulando & próximos passos

Você construiu um **prompt agent** do Foundry que combina:

| Capacidade | Suportada por |
|---|---|
| Respostas de política / how-to com citações | Knowledge base **Foundry IQ** `zava-kb` (sobre o índice `zava-docs`) |
| Estoque ao vivo, alertas, consulta de pedidos | Ferramentas **MCP** na **`zava-toolbox`** (servidor MCP Zava → API Zava) |
| Analytics | **Fabric Data Agent** (`fabric_dataagent_preview`) |
| UI de texto + voz + dashboard | `webapp/inventory-dashboard` (Voice Live) |
| Alcance | Publicação no **Teams** |
| Qualidade | **Evaluations** — built-in + custom (código e prompt) + rubric, executadas na nuvem |

**Próximo:** abra `02_delivery_support_agent.pt-BR.ipynb` para construir o **DeliverySupport Agent** — um
agente *hospedado* usando o **Microsoft Agent Framework**, com **Model Router**, ferramenta `lookupOrder`,
**memória**, **traces + evaluations contínuas** e **voice-live**.

Para remover todos os recursos do Azure ao terminar: `scripts/teardown.ps1`.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print("Wrote", OUT, "with", len(cells), "cells")
