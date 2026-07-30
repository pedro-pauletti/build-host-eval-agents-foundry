# Zava · Demo de Agentes no Microsoft Foundry

> 🇺🇸 [English version](./README.md)

Uma demo/tutorial prática e **fácil de replicar** para a varejista fictícia **Zava** no **Microsoft
Foundry**. Contém **duas demos** que compartilham um cenário coeso, para que você possa clonar, trocar a
empresa e reaproveitar os padrões:

1. **Dois agentes com cara de produção** — *InventoryAgent* (prompt agent do Foundry) e *DeliverySupport*
   (hosted agent do Microsoft Agent Framework).
2. **Orquestração multi-framework** — três agentes construídos com frameworks *diferentes* (LangGraph, GitHub
   Copilot SDK, prompt agent do Foundry), orquestrados pelo Microsoft Agent Framework e hospedados no Foundry.

O destaque são **seis notebooks Jupyter didáticos** (três tópicos × EN/PT-BR) que explicam os conceitos,
mostram os diagramas e executam o código passo a passo. O restante do repositório é a stack funcional que os
notebooks orquestram.

---

## Os dois agentes

### 1. InventoryAgent — *prompt agent* (SDK do Foundry Agent Service)
Responde perguntas de inventário para a equipe de operações da Zava.

- **Base de conhecimento** via **Foundry IQ** (*knowledge base* `zava-kb` do Azure AI Search sobre o índice `zava-docs`) — respostas com citações.
- **Ferramentas** via um **Foundry Toolbox** (`zava-toolbox`) que encapsula o **servidor MCP real da Zava**.
- **Fabric Data Agent** (criado sobre um modelo semântico do Fabric) conectado pela ferramenta `fabric_dataagent_preview`.
- **Web app** para conversar por **texto + voz** (Voice Live) com um **dashboard de inventário** ao vivo.
- **Publicado no Microsoft Teams**.
- **Evaluations** configuradas — built-in + custom (código e prompt) + rubric, executadas na nuvem e visíveis no portal do Foundry e na aba **Evaluations** do web app.

### 2. DeliverySupport Agent — *hosted agent* (Microsoft Agent Framework)
Cuida do rastreamento de pedidos para clientes da Zava.

- **Model Router** como modelo.
- Ferramenta **`lookupOrder`** contra sistemas "de terceiros" (APIs / MCP da Zava).
- **Memória de sessão** entre turnos **e [Foundry Memory](./agents/delivery-support-agent/README.md#long-term-memory-foundry-memory)** — recall durável por cliente (nome, preferência de entrega, canal de notificação, pedidos acompanhados) que sobrevive entre conversas, conectado via um `ContextProvider` do MAF.
- **Traces + Evaluations + Evaluations contínuas** (App Insights).
- Interação **Voice-live**.

---

## Demo #2 — Orquestração multi-framework de agentes (MAF + Foundry Hosted Agents)

Uma segunda demo, autocontida, mostra como **integrar agentes construídos com frameworks diferentes**,
orquestrá-los com o **Microsoft Agent Framework (MAF)** através de um **Agent Harness** comum, e **hospedar**
a orquestração no **Foundry**. O cenário é um **incidente de engenharia da Zava**: o *serviço de reorder*
noturno gerou quantidades de recompra negativas. Três agentes cooperam num pipeline determinístico:

| Etapa | Agente | Framework | Papel |
|-------|--------|-----------|-------|
| 1 | **Triage** | **LangGraph** | Classifica severidade/categoria/componente e roteia o incidente. |
| 2 | **Code Fix** | **GitHub Copilot SDK** | Executa um harness real *plan → execute (shell/fs) → assess → iterate* num **sandbox isolado** até o `pytest` passar. |
| 3 | **Compliance** | **Prompt agent do Foundry** | Revisa a correção contra a política de engenharia da Zava → aprovar / precisa de ajustes. |

Cada agente é exposto ao MAF por um adaptador `BaseChatClient` uniforme (o **Agent Harness comum**),
orquestrado pelo MAF `SequentialBuilder`, encapsulado como um `WorkflowAgent` e servido pelo
`ResponsesHostServer`. A orquestração inteira é registrada no Foundry como um **único hosted agent,
`IncidentOrchestrator`** (`azd deploy incident-orchestration`) — frameworks heterogêneos na entrada, um
agente Foundry na saída. O mesmo container também roda no Azure Container Apps, usado pelo web app para o
stream de eventos passo a passo. Ensinado no **notebook 03** (EN + PT-BR) e executável ao vivo na página
**Incident Response** do web app — um **diagrama de fluxo** da orquestração em tempo real + **dashboard**
por agente. Veja
[`agents/incident-orchestration/`](./agents/incident-orchestration/).

---

## Arquitetura

Veja [`docs/architecture.md`](./docs/architecture.md) para o diagrama completo e os fluxos de dados.
Prompts prontos para demonstrar os três agentes: [`docs/test-prompts.pt-BR.md`](./docs/test-prompts.pt-BR.md).

```
Clientes (Web app · Teams · Voice-live)
        │
        ▼
Projeto Azure AI Foundry ── InventoryAgent (prompt) ── Foundry IQ KB `zava-kb` ── Azure AI Search (docs Zava)
        │                                    │        └ Fabric Data Agent ── Modelo semântico Fabric (Zava-Demos)
        │                                    └ Toolbox `zava-toolbox` ── Servidor MCP Zava ── APIs REST Zava
        └───────────────── DeliverySupport (hosted, MAF) ── Model Router · lookupOrder
                                             │            └ Foundry Memory `zava_delivery_memory` (escopo por cliente)
                                    App Insights (traces + evals)
```

---

## Organização do repositório

| Caminho | Conteúdo |
|---------|----------|
| `notebooks/` | Os 6 notebooks didáticos (3 tópicos × EN + PT-BR) — **comece por aqui** |
| `infra/` | IaC azd + Bicep (projeto Foundry, modelos, AI Search, Container Apps, App Insights) |
| `data/` | Conteúdo fictício da Zava: `docs/` (KB), `structured/` (Fabric), `company/`, `semantic-model/` |
| `services/zava-api/` | APIs REST fictícias da Zava (FastAPI) |
| `services/zava-mcp/` | O servidor MCP **real** da Zava |
| `agents/inventory-agent/` | Scripts do InventoryAgent, wiring de ferramentas, publish no Teams, evals |
| `agents/delivery-support-agent/` | Hosted agent DeliverySupport (Microsoft Agent Framework) |
| `agents/incident-orchestration/` | **Demo #2**: Triage (LangGraph) + Code Fix (Copilot SDK) + Compliance (Foundry) + harness/orquestração MAF + hosting no Foundry |
| `webapp/inventory-dashboard/` | Web app de texto + voz + dashboard (Inventory · Delivery · **Incident Response**) |
| `scripts/` | Provisionamento, RBAC, indexação de docs, carga no Fabric, teardown |
| `docs/` | Arquitetura, diagramas e o [guia de prompts de teste](./docs/test-prompts.pt-BR.md) |

---

## Pré-requisitos

- **Assinatura Azure** com permissão para criar recursos e atribuir papéis (roles).
- **Azure CLI** (`az`) e **Azure Developer CLI** (`azd`), ambos autenticados.
- **Python 3.11+**, **Node.js 18+**, **Docker**.
- Licença do **Microsoft Fabric** + um workspace (esta demo reutiliza o `Zava-Demos`).
- Para publicação no Teams e Voice Live: **Microsoft 365** e consentimento de admin do tenant (passos manuais documentados).

---

## Início rápido

Windows PowerShell (os scripts são `.ps1`; notebooks/scripts usam Python + o `.venv` do repositório).

```powershell
# 1. Autenticar
az login

# 2. Provisionar os recursos Azure principais no rg-zava-demo (projeto Foundry + modelos,
#    Azure AI Search, ambiente Container Apps + ACR, App Insights, conexões, RBAC).
#    Escreve todos os endpoints em um .env na raiz
./scripts/provision.ps1

# 3. (Opcional) regenerar os dados canônicos fictícios
python data/structured/generate_data.py

# 4. Implantar os backends da Zava (API REST + servidor MCP) no Azure Container Apps
./scripts/deploy_backend.ps1

# 5. Indexar os docs da Zava no Azure AI Search
python scripts/index_docs.py

# 6. Criar a knowledge base do Foundry IQ + a zava-toolbox (conexões incluídas)
python agents/inventory-agent/setup_foundry_iq_and_toolbox.py --test

# 7. Criar o InventoryAgent (toolbox + Foundry IQ + Fabric Data Agent) e testar
python agents/inventory-agent/create_agent.py --test

# 8. Implantar o hosted agent DeliverySupport (Microsoft Agent Framework)
#    veja agents/delivery-support-agent/README.md

# 8b. Implantar a orquestração multi-framework como hosted agent do Foundry (Demo #2)
azd env set GITHUB_TOKEN "<token do GitHub com acesso ao Copilot>"
azd deploy incident-orchestration --no-prompt

# 9. Seguir os notebooks didáticos
#    notebooks/01_inventory_agent.pt-BR.ipynb   (ou .en.ipynb)
#    notebooks/02_delivery_support_agent.pt-BR.ipynb

# 10. (Demo #2) Orquestração multi-framework — registrar o prompt agent Compliance,
#    rodar o pipeline de ponta a ponta e implantar no Container Apps.
python agents/incident-orchestration/create_compliance_agent.py
python agents/incident-orchestration/test_orchestration.py     # Triage -> Code Fix -> Compliance (local)
#    A página "Incident Response" do web app roda tudo ao vivo, em processo; notebook de ensino:
#    notebooks/03_multi_agent_orchestration.pt-BR.ipynb   (ou .en.ipynb)

# Rodar o web app localmente (Inventory · Delivery · Incident Response)
cd webapp/inventory-dashboard; ../../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8501
```

> Um ambiente virtual Python (`.venv`) com as bibliotecas cliente é usado pelos scripts e notebooks.
> Opcional: o Fabric Data Agent (analytics) e a ativação de Teams/Voice-live são documentados à parte
> (`data/semantic-model/`, `agents/inventory-agent/TEAMS.md`) por exigirem passos de admin do Fabric/M365.

---

## Custo & limpeza

Esta demo provisiona recursos Azure **cobrados** (modelos do Foundry, AI Search, Container Apps, App Insights).
Execute o script de teardown em `scripts/` para excluir o `rg-zava-demo` e parar de gerar custo. O Fabric usa
a capacidade **Trial** existente por padrão.

---

## Qual modelo roda onde

| Componente | Deployment | Motivo |
|---|---|---|
| **DeliverySupport** (hosted agent MAF) | `model-router` | As function tools são executadas pelo MAF no processo, não pelo Foundry. |
| **Triage** (LangGraph) | `model-router` | Chat completion simples em modo JSON — sem tools. |
| **Compliance** (prompt agent do Foundry) | `model-router` | Prompt agent **sem tools** → seguro para o router. |
| **InventoryAgent** (prompt agent do Foundry) | `gpt-4.1` 📌 | **Fixado** — veja abaixo. |
| **Knowledge base do Foundry IQ** (`zava-kb`) | `gpt-4.1` 📌 | O AI Search rejeita `model-router` (allow-list: gpt-4o / gpt-4.1 / gpt-5.x). |
| **Juiz das evals** (`eval.yaml`, `run_eval.py`) | `gpt-4.1` 📌 | Um juiz precisa ser determinístico, não roteado. |
| **Code Fix** (GitHub Copilot SDK) | `claude-sonnet-4.5` | Roda pelo Copilot SDK, fora do Foundry. |

> 📌 **`model-router` + tools MCP não funciona num prompt agent do Foundry.** Reproduzido várias vezes e
> isoladamente (só a toolbox MCP, com e sem `allowed_tools`): o modelo *lista* as ferramentas
> (`mcp_list_tools` funciona) mas toda **chamada** falha com `500 tool_function_not_found`. O mesmo agente
> com `gpt-4.1` chama `zava_tools___get_inventory_alerts` corretamente. Limitação de preview — reteste
> após uma atualização do serviço.

---

## Status & avisos

- Zava, seus dados, documentos, APIs e transportadoras são **totalmente fictícios**.
- Vários recursos são **preview** (Foundry IQ, Toolboxes, Fabric Data Agent, hosted agents, Voice Live,
  evals contínuas); as APIs podem mudar. As versões de SDK são fixadas quando possível.
