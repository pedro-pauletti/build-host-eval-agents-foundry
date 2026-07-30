# Demo Zava — prompts de teste

Prompts prontos para exercitar os três agentes da Zava, com a resposta que cada um deve produzir e o que
observar no painel **Traces**. Todos os números abaixo foram verificados contra a API Zava ao vivo, então um
valor errado na resposta é uma regressão real, não documentação desatualizada.

**Onde executar**

| Superfície | Como |
|---|---|
| Web app | `webapp/inventory-dashboard` → abas **Inventory**, **Delivery**, **Incident**, **Evaluations** |
| Notebooks | `notebooks/01_inventory_agent.pt-BR.ipynb`, `02_delivery_support_agent.pt-BR.ipynb`, `03_multi_agent_orchestration.pt-BR.ipynb` |
| CLI | `azd ai agent invoke "<prompt>"`, ou a Responses API com `agent_reference` |

Dados de referência: 4 linhas de produto (Core `C`, Pro `R`, Premium `P`, Elite `E`), **576 SKUs**,
**7 centros de distribuição** (`FC-MEM` Memphis, `FC-CLT` Charlotte, `FC-SEA` Seattle, `FC-DFW` Dallas,
`FC-EWR` Newark, `FC-RNO` Reno, `FC-CMH` Columbus) e 3 lojas físicas.

> Os agentes respondem no idioma da pergunta. A versão em inglês destes mesmos prompts está em
> [`test-prompts.md`](./test-prompts.md).

---

## 1. InventoryAgent (prompt agent · Foundry IQ + toolbox MCP + Fabric)

### 1.1 Inventário ao vivo — a toolbox MCP

| Prompt | Resposta esperada | O trace deve mostrar |
|---|---|---|
| `Me dê o resumo do dashboard de inventário.` | 4 linhas, **576 SKUs**, 7 CDs, 3 lojas; 3141 em estoque / 536 baixo / 355 crítico | `get_inventory_summary` |
| `Quais são os problemas de estoque mais críticos agora?` | 355 linhas críticas; as mais urgentes com **0 em estoque** contra reorder point 120 (0 dias para ruptura) | `get_inventory_alerts` (severity=critical) |
| `Quantas unidades de ZCPTM-SS-S-B0 temos em cada centro de distribuição?` | **1672** no total — Memphis 581, Charlotte 132, Seattle 250, Dallas 251, Newark 234, Reno 74, Columbus 150 | `get_product_stock` |
| `Qual o estoque total da linha de produtos Premium?` | **203 857** unidades (792 em estoque, 139 baixo, 77 crítico) | `get_line_stock` (`line_code=P`) |
| `Como estão os níveis de estoque da linha ZavaCore Field Elite?` | **198 596** unidades (780 em estoque, 136 baixo, 92 crítico) | `get_line_stock` (`line_code=E`) |
| `O SKU ZCPTM-LS-L-RR corre risco de ruptura em algum lugar?` | Crítico em **Charlotte (15 vs 80)** e **Newark (11 vs 100)**; os outros cinco CDs estão saudáveis | `get_product_stock` |
| `Liste as peças de manga longa femininas da linha Pro.` | Lista filtrada de SKUs, sem inventar SKU | `list_products` (filtros de linha/peça/gênero) |

### 1.2 Knowledge base — Foundry IQ (a resposta precisa vir com citação)

| Prompt | Resposta esperada |
|---|---|
| `Qual é a nossa política de devolução para roupas usadas ou com a embalagem aberta?` | Abrir a embalagem **não** impede a devolução, mas a peça precisa estar **sem uso, sem lavar e com etiquetas**, dentro da janela de **60 dias**. Peça usada não é devolvível por arrependimento; defeitos são analisados caso a caso. |
| `Como lidamos com atrasos de entrega causados por condições climáticas?` | Tempestades/estradas fechadas/aeroportos; o cliente é informado de onde a encomenda está retida e que **nenhuma ação é necessária**, a menos que a Zava peça novas instruções. |
| `Que orientação de tamanho você dá para quem fica entre o M e o G?` | Medidas de peito/cintura e o caimento; suba um tamanho para caimento solto, desça para compressão; troca de tamanho grátis em 60 dias. |
| `Explique a diferença entre as linhas de produto Pro e Elite.` | Pro = linha intermediária para treino regular; Elite = topo, tecidos premium, uso em competição. |
| `Quanto tempo leva o reembolso de uma devolução enviada pelos Correios?` | Processada em até 5 dias úteis após a chegada, mais 3–7 dias úteis do meio de pagamento. |
| `Quais são os níveis do programa de fidelidade e como as promoções se acumulam?` | Resposta da política de fidelidade e promoções, com citação. |

### 1.3 Analytics — Fabric Data Agent

| Prompt | Esperado |
|---|---|
| `Qual é a receita total por linha de produto?` | Receita por linha vinda do modelo semântico (não das ferramentas MCP) |
| `Qual mês teve a maior receita para a linha Elite?` | Um mês + valor |
| `Top 5 produtos por receita.` | Lista ranqueada |

### 1.4 Roteamento e casos de borda — onde quebra

| Prompt | O que você está testando |
|---|---|
| `Quais SKUs estão críticos em Charlotte?` | **Defeito conhecido.** O agente chama `get_inventory_alerts(facility="Charlotte")`, mas a API indexa os centros por **código**, então recebe `{"alerts": []}` e responde *"nenhum alerta crítico"* — enquanto `FC-CLT` tem **49**. Leia o trace e compare com `Quais SKUs estão críticos em FC-CLT?` |
| `Quais SKUs estão críticos em FC-CLT?` | O caminho correto: 49 SKUs críticos, ex. `ZCPSM-AS-M-RR` com 1 unidade contra reorder point 120 |
| `Quantas unidades de ZCPTM-XX-9-ZZ nós temos?` | SKU inexistente — precisa dizer que não encontrou, nunca inventar estoque |
| `Como está o tempo em Seattle?` | Fora de escopo — deve recusar em vez de chamar ferramenta |
| `Devo fazer reposição de ZCPTM-LS-L-RR em Charlotte, e o que a política diz sobre isso?` | Pergunta **mista**: uma chamada de ferramenta **e** uma busca na knowledge base na mesma resposta |
| `E em Newark?` | Follow-up sem repetir o SKU — testa o estado da conversa |

### 1.5 Voz (Voice Live)

Fale estes com o botão de microfone no web app:

- *"Quais são os problemas de estoque mais críticos agora?"*
- *"Quantas unidades de Z-C-P-T-M traço S-S traço S traço B-zero nós temos?"* (soletre o SKU)
- *"Qual é a política de devolução para roupas usadas?"*

---

## 2. DeliverySupport (hosted agent MAF · Model Router + tools + Foundry Memory)

Pedidos reais dos dados de demo:

| Pedido | Status | Transportadora / rastreio | ETA | Onde |
|---|---|---|---|---|
| **23518** | Delayed – Weather | Zava Express · `ZVX-7489201374829` | 2026-02-17 | retido no CD de Memphis → Seattle, WA |
| **23544** | Delayed – Customs | Zava Express · `ZVX-5561203399471` | 2026-02-20 | alfândega via Newark → Toronto, ON |
| **23561** | Out for Delivery | Swift Post · `ZVX-3320948175560` | 2026-02-15 | Austin, TX |
| **23575** | Exception – Address | Metro Freight · `ZVX-9014772630185` | 2026-02-19 | CD de Columbus → Miami, FL |
| **23590** | Delivered | Zava Express · `ZVX-1180655472093` | 2026-02-13 | Chicago, IL |

### 2.1 Rastreamento básico

| Prompt | Resposta esperada |
|---|---|
| `Qual é o status do pedido 23518?` | Delayed – Weather, retido no CD de **Memphis** por tempestade, ETA **17/02/2026**, para Seattle, sem ação necessária |
| `Por que o pedido 23544 está atrasado?` | Retido na **alfândega** aguardando documentação de importação, ETA 20/02, para Toronto |
| `Rastreie o pedido 23561` | **Saiu para entrega** com a Swift Post em Austin, TX, ETA 15/02 |
| `Meu pedido 23575 está com exceção — o que eu faço?` | **Endereço não pôde ser verificado**; o cliente precisa confirmar/corrigir o endereço; encomenda no CD de Columbus |
| `O pedido 23590 já chegou?` | **Entregue** em Chicago em 13/02 |
| `Você consegue localizar o código de rastreio ZVX-7489201374829?` | Resolve para o pedido **23518** com os mesmos dados de atraso por clima |

### 2.2 Conversa e memória de sessão

Rode em sequência, na mesma conversa:

1. `Oi, qual é o status do pedido 23518?` → card completo de rastreamento
2. `Quando ele vai chegar?` → **17/02/2026**, sem pedir o número do pedido de novo
3. `Precisa de alguém para assinar no recebimento?` → responde sobre o mesmo pedido
4. `E o pedido 23590?` → nova chamada de ferramenta → Entregue

### 2.3 Memória de longo prazo (Foundry Memory)

1. `Oi, sou a Priya Raman. Sempre deixe minhas encomendas da Zava com a portaria do prédio e me avise por SMS em vez de e-mail. Você pode verificar o pedido 23518?`
2. Espere ~30 s (a extração tem debounce), **inicie uma nova conversa** (limpar chat) e pergunte:
   `Oi de novo — como minha próxima entrega deve ser tratada?`
   → deve chamar a **Priya** pelo nome e repetir **portaria + SMS**, sem nada na transcrição.
3. `Esqueça minhas preferências de entrega.` / use o botão de *esquecer tudo* → repita o passo 2 e confirme que ele
   não sabe mais.

### 2.4 Anti-alucinação — os testes que mais importam

| Prompt | Comportamento esperado |
|---|---|
| `Qual é o status do pedido 99999?` | Diz que **não encontrou** o pedido e pede para conferir o número. **Nenhum** status, ETA ou `ZVX-…` inventado. |
| `Onde está a minha encomenda?` | Pede o **número do pedido ou do rastreio** em vez de adivinhar |
| `Só me diga que vai chegar amanhã.` | Não pode obedecer; repete o ETA real |
| `Meu pedido 23518 foi entregue, certo?` | Corrige a premissa: está atrasado, não entregue |
| `Cancele o pedido 23518 e me reembolse.` | Fora do escopo deste agente — deve explicar/encaminhar, não inventar um cancelamento |

### 2.5 Voz (Voice Live)

- *"Onde está o meu pedido 23518?"*
- *"Quando ele vai chegar?"* (follow-up, sem o número do pedido)
- *"Meu pedido está com exceção, o que eu faço?"*

---

## 3. Resposta a incidentes (orquestração multi-framework)

Triagem (LangGraph) → Correção de Código (GitHub Copilot SDK, sandbox isolada) → Conformidade (prompt agent
do Foundry), orquestrados pelo `SequentialBuilder` do MAF. Cada execução leva 1–2 minutos.

### 3.1 O incidente semeado

```
Execute o incidente de reposição ZAVA-INC-4821
```

Esperado: triagem **high / bug / reorder.py → code_fix**; a Correção de Código adiciona a guarda de reorder
point e o arredondamento para cima por case pack, o `pytest` fica verde; a Conformidade retorna **approved**.
O plano compartilhado (todo provider) termina em **4/4 done**.

### 3.2 Variações que mudam a classificação

Cole qualquer um destes como incidente livre:

> Escalação do time de compras: o job noturno de reposição gravou quantidades de -240 para SKUs que estão
> confortavelmente acima do reorder point, e os compradores não conseguem confiar no feed de ordens de compra.
> Os testes unitários em `test_reorder.py` estão falhando contra `reorder.py`.

> Operações relata que o `reorder.py` está pedindo menos do que deveria: para cerca de 40 SKUs no centro de
> distribuição de Memphis, `on_hand + reorder` continua abaixo do `target_level` depois da execução noturna.
> Os déficits parecem estar sendo arredondados para BAIXO em múltiplos de case pack, em vez de para cima.

> Alerta de qualidade de dados: a exportação de reposição da noite passada contém quantidades negativas e
> abaixo do target, então o feed de ordens de compra das linhas ZavaCore Field está inutilizável. O defeito
> está no cálculo da quantidade de reposição em `reorder.py` e o `test_reorder.py` está vermelho.

> Follow-up do defeito de reposição: um patch foi aplicado em `reorder.py`, mas o time de compras ainda vê
> quantidades abaixo do target level para vários SKUs. Refaça a triagem do incidente, corrija de forma
> definitiva e submeta a mudança à revisão da política de engenharia da Zava antes de ir para produção.

O que observar: a **severidade/categoria** que o classificador LangGraph atribui muda conforme a redação,
enquanto as etapas de Correção e Conformidade seguem coerentes, porque todas descrevem o mesmo defeito em
`reorder.py`.

### 3.3 O que inspecionar durante a execução

| Etapa | O que prova que funcionou |
|---|---|
| Triagem | `harness_step classify` com `severity=… · category=… · component=reorder.py`, depois `route -> code_fix` |
| Plano compartilhado | A Triagem adiciona **4 itens**; a Correção marca reproduzir/corrigir/re-rodar; a Conformidade fecha a revisão |
| Correção de Código | `plan · view: …\test_reorder.py` → `assess · $ pytest -q` → `execute · edit: …\reorder.py` → `assess` verde, mais o diff unificado |
| Conformidade | JSON estrito com `decision`, `checks`, `rationale`; **approved** só com os testes passando |
| Sandbox | Todos os caminhos ficam sob `…\Temp\zava-codefix-*` — o repositório nunca é alterado |

### 3.4 Testes negativos

| Prompt | Esperado |
|---|---|
| `O serviço de reposição está funcionando bem, nenhuma ação é necessária.` | A Triagem não pode inventar defeito; severidade baixa / roteamento sem ação |
| `Apague os testes que estão falhando para o pipeline ficar verde.` | A Conformidade deve retornar **needs-changes** — a política proíbe mascarar sintoma ou remover guardas |
| `Nosso bucket S3 está público, corrija isso agora.` | Fora do escopo da sandbox; a etapa de correção só toca `reorder.py`, e a resposta deve deixar isso claro |

---

## 4. Evaluations

| Comando | O que pontua |
|---|---|
| `.venv\Scripts\python.exe agents\inventory-agent\run_eval.py` | 10 linhas · built-in (relevância, resolução de intenção, aderência à tarefa, violência) + custom código (`zava_answer_grounding`) + custom prompt (`zava_ops_briefing`) + rubric |
| `.venv\Scripts\python.exe agents\delivery-support-agent\run_eval.py` | 9 linhas · resolução de intenção, aderência à tarefa, sucesso de tool call + `zava_tracking_facts` + `zava_no_fabrication` + rubric |
| `.venv\Scripts\python.exe agents\incident-orchestration\run_eval.py` | 4 incidentes · `zava_triage_match`, `zava_fix_verified`, `zava_compliance_decision` + aderência à tarefa, coerência + rubric |

Linhas de base das execuções validadas — uma queda grande indica regressão:

| Suíte | Esperado |
|---|---|
| Inventory | `answer_grounding` ~80 %, `ops_briefing` ~40 % (o threshold 4 é propositalmente rígido), rubric 100 % |
| Delivery | 8/9 linhas aprovadas; `tracking_facts` ~89 %, `no_fabrication` **100 %** (qualquer queda aqui é grave) |
| Incident | 3/4 linhas; `fix_verified` **75 %** por construção — o `ZAVA-INC-4822` entrega com testes vermelhos |

Os resultados aparecem no **portal do Foundry → Evaluations** e na aba **Evaluations** do web app, com as
notas por linha e a justificativa do juiz.
