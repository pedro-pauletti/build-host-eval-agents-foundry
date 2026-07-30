# DeliverySupport — Traces, Evaluations & Continuous Evaluations

Observability for the hosted DeliverySupport agent, using **Application Insights** (provisioned in
`rg-zava-demo`, connection string in `.env` as `APPLICATIONINSIGHTS_CONNECTION_STRING`).

## 1. Traces (OpenTelemetry → Application Insights)
The Microsoft Agent Framework emits OpenTelemetry spans for every turn, including **tool calls**.

- **Local:** set `APPLICATIONINSIGHTS_CONNECTION_STRING` in the agent's environment; `main.py`'s hosting
  adapter enables instrumentation.
- **Hosted:** Foundry injects `APPLICATIONINSIGHTS_CONNECTION_STRING` automatically when the project is
  linked to App Insights.
- **View:** Azure Portal → Application Insights (`appi-zava-…`) → **Investigate → Transaction search**
  (per-trace) or **Application map** (dependency graph, including calls to the Zava API).

## 2. Evaluations (batch)
Score the agent on a representative dataset (`evals/delivery_seed.jsonl`) with evaluators tuned for a
tool-using agent: **intent_resolution**, **task_adherence**, **tool_call_accuracy**, **relevance**.
The suite is declared in `eval.yaml`.

With the `azd ai agent` extension (after deploy):
```powershell
azd ai agent eval generate --gen-instruction "Zava order-tracking assistant" --no-wait --no-prompt
azd ai agent eval run
azd ai agent eval show -O results.json
```
Or run a quick local pass (invoke the agent + score) similarly to `agents/inventory-agent/run_eval.py`.

## 3. Continuous Evaluations (production monitoring)
Continuous evaluation samples **live production traces** and scores them automatically on a schedule, so
quality regressions (e.g. rising tool-call errors or dropping task adherence) surface in dashboards.

- Prerequisite: the agent is **deployed** and the project is **linked to Application Insights** (both true
  in this demo).
- Enable it from the Foundry portal (project → your agent → **Monitoring / Continuous evaluation**) or via
  the observability tooling; pick the evaluators and sampling rate.
- Results appear alongside traces in App Insights and the Foundry monitoring dashboards.

> Continuous evaluation is a preview capability; exact enablement UI may change. The signal it produces —
> ongoing, automatic scoring of real traffic — is what closes the loop from build → deploy → observe.
