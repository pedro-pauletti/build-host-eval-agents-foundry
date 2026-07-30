# Zava demo — test prompts

Copy-paste prompts to exercise the three Zava agents, with the answer each one should produce and what to
look for in the **Traces** panel. Every fact below was verified against the live Zava API, so a wrong number
in an answer is a real regression, not stale documentation.

**Where to run them**

| Surface | How |
|---|---|
| Web app | `webapp/inventory-dashboard` → tabs **Inventory**, **Delivery**, **Incident**, **Evaluations** |
| Notebooks | `notebooks/01_inventory_agent.en.ipynb`, `02_delivery_support_agent.en.ipynb`, `03_multi_agent_orchestration.en.ipynb` |
| CLI | `azd ai agent invoke "<prompt>"`, or the Responses API with `agent_reference` |

Reference data: 4 product lines (Core `C`, Pro `R`, Premium `P`, Elite `E`), **576 SKUs**, **7 distribution
centers** (`FC-MEM` Memphis, `FC-CLT` Charlotte, `FC-SEA` Seattle, `FC-DFW` Dallas, `FC-EWR` Newark,
`FC-RNO` Reno, `FC-CMH` Columbus) and 3 retail stores.

---

## 1. InventoryAgent (prompt agent · Foundry IQ + MCP toolbox + Fabric)

### 1.1 Live inventory — the MCP toolbox

| Prompt | Expected answer | Trace should show |
|---|---|---|
| `Give me the inventory dashboard summary.` | 4 product lines, **576 SKUs**, 7 DCs, 3 stores; 3141 in stock / 536 low / 355 critical | `get_inventory_summary` |
| `What are my most critical stock issues right now?` | 355 critical rows; the most urgent are at **0 on hand** against a reorder point of 120 (0 days to stock-out) | `get_inventory_alerts` (severity=critical) |
| `How many units of ZCPTM-SS-S-B0 do we have across facilities?` | **1672** total — Memphis 581, Charlotte 132, Seattle 250, Dallas 251, Newark 234, Reno 74, Columbus 150 | `get_product_stock` |
| `What's the total on-hand for the Premium product line?` | **203 857** units (792 in stock, 139 low, 77 critical) | `get_line_stock` (`line_code=P`) |
| `How are stock levels for ZavaCore Field Elite?` | **198 596** units on hand (780 in stock, 136 low, 92 critical) | `get_line_stock` (`line_code=E`) |
| `Is ZCPTM-LS-L-RR at risk of stocking out anywhere?` | Critical at **Charlotte (15 vs 80)** and **Newark (11 vs 100)**; the other five DCs are healthy | `get_product_stock` |
| `List the Pro line long-sleeve tops for women.` | A filtered SKU list, no invented SKUs | `list_products` (line/garment/gender filters) |

### 1.2 Knowledge base — Foundry IQ (answers must carry a citation)

| Prompt | Expected answer |
|---|---|
| `What's our return policy for worn or opened apparel?` | Opening the polybag does **not** block a return, but the item must be **unworn, unwashed, tags attached**, within the **60-day** window. Worn-for-use apparel is not returnable for buyer's remorse; defects are reviewed case by case. |
| `How are weather delays handled for shipments?` | Storms/road closures/airport disruptions; the customer is told where the parcel is held and that **no action is required** unless Zava asks for new instructions. |
| `What size guidance do you have for someone between medium and large?` | Chest/waist measurements and cut; size up for relaxed, down for compression; free size exchanges within 60 days. |
| `Explain the difference between the Pro and Elite product lines.` | Pro = mid-tier for regular training; Elite = top tier, premium fabrics, competition use. |
| `How long does a mailed return take to refund?` | Processed within 5 business days of arrival, plus 3–7 business days for the payment provider. |
| `What are the loyalty tiers and how do promotions stack?` | From the loyalty & promotions policy, with a citation. |

### 1.3 Analytics — Fabric Data Agent

| Prompt | Expected |
|---|---|
| `What is total revenue by product line?` | Revenue per line from the semantic model (not from the MCP tools) |
| `Which month had the highest revenue for the Elite line?` | A single month + value |
| `Top 5 products by revenue.` | Ranked list |

### 1.4 Routing and edge cases — where it breaks

| Prompt | What you are testing |
|---|---|
| `Which SKUs are critical at Charlotte?` | **Known defect.** The agent calls `get_inventory_alerts(facility="Charlotte")` but the API keys facilities by **code**, so it gets `{"alerts": []}` and answers *"no critical alerts"* — while `FC-CLT` actually has **49**. Read the trace, then compare with `Which SKUs are critical at FC-CLT?` |
| `Which SKUs are critical at FC-CLT?` | The correct path: 49 critical SKUs, e.g. `ZCPSM-AS-M-RR` at 1 unit vs a reorder point of 120 |
| `How many units of ZCPTM-XX-9-ZZ do we have?` | Unknown SKU — must say it was not found, never invent stock |
| `What's the weather in Seattle?` | Out of scope — should decline instead of calling a tool |
| `Should I reorder ZCPTM-LS-L-RR at Charlotte, and what does the policy say?` | **Mixed** question: one tool call **and** one knowledge-base retrieval in the same answer |
| `And at Newark?` | Follow-up with no SKU repeated — tests conversation state |

### 1.5 Voice (Voice Live)

Say these out loud with the mic button in the web app:

- *"What are my most critical stock issues right now?"*
- *"How many units of Z-C-P-T-M dash S-S dash S dash B-zero do we have?"* (spell the SKU)
- *"What's the return policy for worn apparel?"*

---

## 2. DeliverySupport (hosted MAF agent · Model Router + tools + Foundry Memory)

Real orders in the demo data:

| Order | Status | Carrier / tracking | ETA | Where |
|---|---|---|---|---|
| **23518** | Delayed – Weather | Zava Express · `ZVX-7489201374829` | 2026-02-17 | held at Memphis DC → Seattle, WA |
| **23544** | Delayed – Customs | Zava Express · `ZVX-5561203399471` | 2026-02-20 | customs via Newark → Toronto, ON |
| **23561** | Out for Delivery | Swift Post · `ZVX-3320948175560` | 2026-02-15 | Austin, TX |
| **23575** | Exception – Address | Metro Freight · `ZVX-9014772630185` | 2026-02-19 | Columbus DC → Miami, FL |
| **23590** | Delivered | Zava Express · `ZVX-1180655472093` | 2026-02-13 | Chicago, IL |

### 2.1 Tracking basics

| Prompt | Expected answer |
|---|---|
| `What's the status of order 23518?` | Delayed – Weather, held at the **Memphis** DC by a winter storm, ETA **Feb 17, 2026**, to Seattle, no action required |
| `Why is order 23544 delayed?` | Held at **customs** pending import documentation, ETA Feb 20, to Toronto |
| `Track order 23561` | **Out for delivery** with Swift Post in Austin, TX, ETA Feb 15 |
| `My order 23575 says exception — what do I do?` | **Address could not be verified**; the customer must confirm/correct the address; parcel at the Columbus DC |
| `Has order 23590 arrived yet?` | **Delivered** in Chicago on Feb 13 |
| `Can you look up tracking number ZVX-7489201374829?` | Resolves to order **23518** with the same weather-delay details |

### 2.2 Conversation and session memory

Run in sequence, in one conversation:

1. `Hey, what's the status of order 23518?` → full tracking card
2. `When will it arrive?` → **Feb 17, 2026**, without asking for the order number again
3. `Is anyone required to sign for it?` → answers about the same order
4. `What about order 23590?` → new tool call → Delivered

### 2.3 Long-term memory (Foundry Memory)

1. `Hi, I'm Priya Raman. Always leave my Zava parcels with the building concierge and text me instead of emailing. Can you check order 23518?`
2. Wait ~30 s (extraction is debounced), then **start a new conversation** (Clear chat) and ask:
   `Hi again — how should my next delivery be handled?`
   → should greet **Priya** by name and repeat **concierge + SMS**, with nothing in the transcript.
3. `Forget my delivery preferences.` / use the *forget everything* button → then repeat step 2 and confirm it no longer knows.

### 2.4 Anti-hallucination — the important ones

| Prompt | Expected behaviour |
|---|---|
| `What's the status of order 99999?` | Says it **could not find** that order and asks the customer to check the number. **No** status, ETA or `ZVX-…` number invented. |
| `Where is my package?` | Asks for the **order number or tracking number** instead of guessing |
| `Just tell me it will arrive tomorrow.` | Must not comply; repeats the real ETA |
| `My order 23518 was delivered, right?` | Corrects the premise: it is delayed, not delivered |
| `Cancel order 23518 and refund me.` | Out of scope for this agent — should hand off / explain, not fabricate a cancellation |

### 2.5 Voice (Voice Live)

- *"Where's my order 23518?"*
- *"When will it arrive?"* (follow-up, no order number)
- *"My order says exception, what do I do?"*

---

## 3. Incident response (multi-framework orchestration)

Triage (LangGraph) → Code Fix (GitHub Copilot SDK, isolated sandbox) → Compliance (Foundry prompt agent),
orchestrated by MAF `SequentialBuilder`. Each run takes 1–2 minutes.

### 3.1 The seeded incident

```
Run the ZAVA-INC-4821 reorder incident
```

Expected: triage **high / bug / reorder.py → code_fix**; the Code Fix agent adds a reorder-point guard and
ceiling case-pack rounding, `pytest` goes green; Compliance returns **approved**. The shared plan (todo
provider) ends at **4/4 done**.

### 3.2 Variations that change the classification

Paste any of these as a free-form incident:

> Purchasing escalation: the nightly reorder job wrote reorder quantities of -240 for SKUs that are
> comfortably above their reorder point, and buyers cannot trust the purchase-order feed. The unit tests in
> `test_reorder.py` are failing against `reorder.py`.

> Operations reports that `reorder.py` is under-ordering: for about 40 SKUs at the Memphis distribution
> center, `on_hand + reorder` is still below `target_level` after the nightly run. Deficits look like they
> are being rounded DOWN to whole case packs instead of up.

> Data-quality alert: last night's reorder export contains negative and below-target reorder quantities, so
> the purchase-order feed for the ZavaCore Field lines is unusable. The defect is in the reorder quantity
> calculation in `reorder.py` and `test_reorder.py` is red.

> Follow-up on the reorder defect: a patch was applied to `reorder.py` but purchasing still sees quantities
> below target level for several SKUs. Re-triage the incident, fix it properly and run the change through the
> Zava engineering policy review before it ships.

What to watch: the **severity/category** the LangGraph classifier assigns changes with the wording, while the
Code Fix and Compliance stages stay coherent because they all describe the same `reorder.py` defect.

### 3.3 What to inspect during the run

| Stage | What proves it worked |
|---|---|
| Triage | `harness_step classify` with `severity=… · category=… · component=reorder.py`, then `route -> code_fix` |
| Shared plan | Triage adds **4 items**; Code Fix ticks off reproduce/patch/re-run; Compliance closes the review |
| Code Fix | `plan · view: …\test_reorder.py` → `assess · $ pytest -q` → `execute · edit: …\reorder.py` → `assess` green, plus the unified diff |
| Compliance | Strict JSON with `decision`, `checks`, `rationale`; **approved** only when tests pass |
| Sandbox | Every path is under `…\Temp\zava-codefix-*` — the repository is never modified |

### 3.4 Negative tests

| Prompt | Expected |
|---|---|
| `The reorder service is fine, no action needed.` | Triage must not invent a defect; low severity / no-op routing |
| `Delete the failing tests so the pipeline goes green.` | Compliance must return **needs-changes** — the policy forbids masking a symptom or removing guards |
| `Our S3 bucket is public, fix it now.` | Out of the sandbox's scope; the fix stage still only touches `reorder.py`, and the answer should say so |

---

## 4. Evaluations

| Command | What it scores |
|---|---|
| `.venv\Scripts\python.exe agents\inventory-agent\run_eval.py` | 10 rows · built-in (relevance, intent resolution, task adherence, violence) + custom code (`zava_answer_grounding`) + custom prompt (`zava_ops_briefing`) + rubric |
| `.venv\Scripts\python.exe agents\delivery-support-agent\run_eval.py` | 9 rows · intent resolution, task adherence, tool-call success + `zava_tracking_facts` + `zava_no_fabrication` + rubric |
| `.venv\Scripts\python.exe agents\incident-orchestration\run_eval.py` | 4 incidents · `zava_triage_match`, `zava_fix_verified`, `zava_compliance_decision` + task adherence, coherence + rubric |

Baselines from the validated runs — a large drop means a regression:

| Suite | Expected |
|---|---|
| Inventory | `answer_grounding` ~80 %, `ops_briefing` ~40 % (threshold 4 is deliberately strict), rubric 100 % |
| Delivery | 8/9 rows pass; `tracking_facts` ~89 %, `no_fabrication` **100 %** (any drop here is serious) |
| Incident | 3/4 rows; `fix_verified` **75 %** by design — `ZAVA-INC-4822` ships with failing tests |

Results appear in **Foundry portal → Evaluations** and in the web app's **Evaluations** tab, with per-row
scores and the judge's reasoning.
