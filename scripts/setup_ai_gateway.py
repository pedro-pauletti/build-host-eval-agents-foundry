#!/usr/bin/env python3
"""
Wire the Zava Foundry project through the **AI Gateway** (Azure API Management) so every model
and agent call is logged, attributable and costable.

What this configures, idempotently:

  1. **Diagnostic setting** on the APIM resource -> Log Analytics, with the ``GatewayLlmLogs``
     category. Without this the LLM logs are generated and then dropped, and the AI Gateway
     dashboard stays empty.
  2. **APIM diagnostic** ``largeLanguageModel`` logging, which is what makes APIM record prompts,
     completions and token counts in the first place. It is ``null`` by default.
  3. **API policy** with ``llm-emit-token-metric``, emitting token counts to Azure Monitor
     dimensioned by subscription, model and caller so cost can be split per agent.

Why this works at all: a Foundry **prompt agent** runs server-side, so APIM cannot see the
individual model calls the agent makes internally. It *can* see the Responses API call that
triggers the run, and that response carries the **aggregate** ``usage`` for the whole run -
tool calls included. That aggregate is the billable number, which is exactly what FinOps needs.

Prereqs:
    az login  (Contributor on the resource group)

Usage:
    .venv\\Scripts\\python.exe scripts/setup_ai_gateway.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env", override=False)

SUB = os.environ["AZURE_SUBSCRIPTION_ID"]
RG = os.getenv("AZURE_RESOURCE_GROUP", "rg-zava-demo")
APIM = os.getenv("AI_GATEWAY_NAME", "zava-demos-ai-gateway")
API = os.getenv("AI_GATEWAY_API_ID", "zava-foundry-cvm43wkpxaiyg")
WORKSPACE = os.getenv("LOG_ANALYTICS_WORKSPACE_NAME", "log-zava-cvm43wkpxaiyg")
APPINSIGHTS = os.getenv("APPLICATIONINSIGHTS_NAME", "appi-zava-cvm43wkpxaiyg")

ARM = "https://management.azure.com"
APIM_ID = (f"/subscriptions/{SUB}/resourceGroups/{RG}/providers"
           f"/Microsoft.ApiManagement/service/{APIM}")
WORKSPACE_ID = (f"/subscriptions/{SUB}/resourceGroups/{RG}/providers"
                f"/Microsoft.OperationalInsights/workspaces/{WORKSPACE}")

# APIM's built-in LLM parser understands the Azure OpenAI /chat/completions shape. It does NOT
# understand the Foundry Responses API (/openai/v1/responses): prompts and completions are logged
# but promptTokens/completionTokens/totalTokens all come back 0, and model/deployment are blank.
# So we read `usage` out of the response body ourselves and emit it as a dimensioned metric. This
# works for both payload shapes, which is what makes prompt agents costable at all.
OUTBOUND_FRAGMENT = """
        <choose>
            <when condition="@(context.Response.StatusCode == 200)">
                <set-variable name="zavaTokens" value="@{
                    try {
                        var body = context.Response.Body.As<JObject>(preserveContent: true);
                        var u = body["usage"];
                        if (u == null) { return "0|0|0|0"; }
                        long inp = (long?)u["input_tokens"] ?? (long?)u["prompt_tokens"] ?? 0;
                        long outp = (long?)u["output_tokens"] ?? (long?)u["completion_tokens"] ?? 0;
                        long tot = (long?)u["total_tokens"] ?? (inp + outp);
                        long cached = 0;
                        var det = u["input_tokens_details"] ?? u["prompt_tokens_details"];
                        if (det != null) { cached = (long?)det["cached_tokens"] ?? 0; }
                        return inp + "|" + outp + "|" + tot + "|" + cached;
                    } catch (Exception) { return "0|0|0|0"; }
                }" />
                <set-variable name="zavaModel" value="@{
                    try {
                        var body = context.Response.Body.As<JObject>(preserveContent: true);
                        var m = (string)body["model"];
                        return string.IsNullOrEmpty(m) ? "unknown" : m;
                    } catch (Exception) { return "unknown"; }
                }" />
                <emit-metric name="PromptTokens" namespace="zava-genai" value="@(double.Parse(((string)context.Variables["zavaTokens"]).Split('|')[0]))">
                    <dimension name="Caller" value="@(context.Request.Headers.GetValueOrDefault("x-zava-caller","unknown"))" />
                    <dimension name="Model" value="@((string)context.Variables["zavaModel"])" />
                    <dimension name="Agent" value="@(context.Request.Headers.GetValueOrDefault("x-zava-agent","none"))" />
                </emit-metric>
                <emit-metric name="CompletionTokens" namespace="zava-genai" value="@(double.Parse(((string)context.Variables["zavaTokens"]).Split('|')[1]))">
                    <dimension name="Caller" value="@(context.Request.Headers.GetValueOrDefault("x-zava-caller","unknown"))" />
                    <dimension name="Model" value="@((string)context.Variables["zavaModel"])" />
                    <dimension name="Agent" value="@(context.Request.Headers.GetValueOrDefault("x-zava-agent","none"))" />
                </emit-metric>
                <emit-metric name="CachedTokens" namespace="zava-genai" value="@(double.Parse(((string)context.Variables["zavaTokens"]).Split('|')[3]))">
                    <dimension name="Caller" value="@(context.Request.Headers.GetValueOrDefault("x-zava-caller","unknown"))" />
                    <dimension name="Model" value="@((string)context.Variables["zavaModel"])" />
                    <dimension name="Agent" value="@(context.Request.Headers.GetValueOrDefault("x-zava-agent","none"))" />
                </emit-metric>
                <emit-metric name="Calls" namespace="zava-genai" value="1">
                    <dimension name="Caller" value="@(context.Request.Headers.GetValueOrDefault("x-zava-caller","unknown"))" />
                    <dimension name="Model" value="@((string)context.Variables["zavaModel"])" />
                    <dimension name="Agent" value="@(context.Request.Headers.GetValueOrDefault("x-zava-agent","none"))" />
                </emit-metric>
            </when>
        </choose>
"""


def add_token_metric_policy() -> None:
    """Append our usage-extraction to the API's outbound policy, preserving what is already there."""
    url = f"{ARM}{APIM_ID}/apis/{API}/policies/policy?api-version=2024-05-01"
    r = requests.get(f"{url}&format=rawxml", headers=H, timeout=60)
    if not r.ok:
        print(f"4. policy: nao foi possivel ler ({r.status_code})")
        return
    xml = r.content.decode("utf-8-sig")

    if "zavaTokens" in xml:
        print("4. extracao de usage: ja presente")
        return

    marker = "<outbound>"
    idx = xml.find(marker)
    if idx < 0:
        print("4. policy: <outbound> nao encontrado, pulando")
        return
    patched = xml[:idx + len(marker)] + OUTBOUND_FRAGMENT + xml[idx + len(marker):]

    r = requests.put(url, headers=H, timeout=90, data=json.dumps(
        {"properties": {"value": patched, "format": "rawxml"}}))
    print(f"4. extracao de usage -> metricas zava-genai: "
          f"{'OK' if r.ok else f'{r.status_code} {r.text[:400]}'}")


def token() -> str:
    out = subprocess.run(
        ["az", "account", "get-access-token", "--resource", ARM, "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True)
    if out.returncode != 0:
        sys.exit("az login necessario")
    return out.stdout.strip()


H = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}


def diagnostic_setting_to_log_analytics() -> None:
    """APIM generates LLM logs only if a diagnostic setting ships the category somewhere."""
    url = (f"{ARM}{APIM_ID}/providers/Microsoft.Insights/diagnosticSettings"
           f"/zava-ai-gateway?api-version=2021-05-01-preview")
    body = {"properties": {
        "workspaceId": WORKSPACE_ID,
        # Without this the rows land in the generic AzureDiagnostics table instead of
        # ApiManagementGatewayLlmLog, and both the AI Gateway dashboard and any query written
        # against the documented schema come back empty while logs are in fact flowing.
        "logAnalyticsDestinationType": "Dedicated",
        "logs": [
            {"category": "GatewayLogs", "enabled": True},
            {"category": "GatewayLlmLogs", "enabled": True},
            {"category": "GatewayMCPLogs", "enabled": True},
        ],
        "metrics": [{"category": "AllMetrics", "enabled": True}],
    }}
    r = requests.put(url, headers=H, data=json.dumps(body), timeout=90)
    print(f"1. diagnostic setting -> Log Analytics ({WORKSPACE}): "
          f"{'OK' if r.ok else f'{r.status_code} {r.text[:200]}'}")


def enable_llm_logging() -> None:
    """Turn on prompt/completion/token capture. Null by default, which is why dashboards are empty."""
    llm = {
        "logs": "enabled",
        "requests": {"messages": "all", "maxSizeInBytes": 32768},
        "responses": {"messages": "all", "maxSizeInBytes": 32768},
    }

    base = f"{ARM}{APIM_ID}/diagnostics/azuremonitor?api-version=2024-05-01"
    current = requests.get(base, headers=H, timeout=60).json().get("properties", {})
    current["largeLanguageModel"] = llm
    # `emit-metric` is silently dropped unless this flag is on: the gateway trace says
    # "No diagnostic settings have metric enabled. Metric emission skipped." This is NOT the same
    # as the AllMetrics category on the Azure Monitor diagnostic setting above.
    current["metrics"] = True
    r = requests.put(base, headers=H, data=json.dumps({"properties": current}), timeout=90)
    print(f"2. largeLanguageModel + metrics no servico: {'OK' if r.ok else f'{r.status_code} {r.text[:200]}'}")

    # The service-level diagnostic only sets defaults. Azure Monitor logs are emitted per API, so
    # without an API-level diagnostic entity nothing is written — the tables stay empty even though
    # metrics flow and the diagnostic setting looks correct.
    api_url = f"{ARM}{APIM_ID}/apis/{API}/diagnostics/azuremonitor?api-version=2024-05-01"
    body = {"properties": {
        "loggerId": f"{APIM_ID}/loggers/azuremonitor",
        "alwaysLog": "allErrors",
        "sampling": {"samplingType": "fixed", "percentage": 100.0},
        "logClientIp": True,
        "metrics": True,
        "largeLanguageModel": llm,
    }}
    r = requests.put(api_url, headers=H, data=json.dumps(body), timeout=90)
    print(f"3. diagnostic na API '{API}': {'OK' if r.ok else f'{r.status_code} {r.text[:300]}'}")


def application_insights_logger() -> None:
    """`emit-metric` writes custom metrics through an Application Insights logger.

    With only the azureMonitor logger the gateway trace shows the metric being emitted with
    ``"namespace": null`` and nothing ever reaches Azure Monitor — the custom metric namespace is
    never created. An applicationInsights logger gives those metrics a destination, and they then
    land in the App Insights ``customMetrics`` / Log Analytics ``AppMetrics`` table.
    """
    import subprocess as sp
    out = sp.run(["az", "monitor", "app-insights", "component", "show",
                  "-g", RG, "-a", APPINSIGHTS, "--query", "connectionString", "-o", "tsv"],
                 capture_output=True, text=True, shell=True)
    conn = out.stdout.strip()
    if not conn:
        print(f"5. App Insights '{APPINSIGHTS}' nao encontrado — metricas custom ficarao sem destino")
        return

    nv_url = f"{ARM}{APIM_ID}/namedValues/appinsights-connection?api-version=2024-05-01"
    r = requests.put(nv_url, headers=H, timeout=90, data=json.dumps({"properties": {
        "displayName": "appinsights-connection", "value": conn, "secret": True}}))
    if not r.ok:
        print(f"5. named value: {r.status_code} {r.text[:200]}")
        return

    logger_url = f"{ARM}{APIM_ID}/loggers/appinsights?api-version=2024-05-01"
    r = requests.put(logger_url, headers=H, timeout=90, data=json.dumps({"properties": {
        "loggerType": "applicationInsights",
        "description": "Application Insights logger for GenAI custom metrics",
        "credentials": {"connectionString": "{{appinsights-connection}}"},
        "isBuffered": True,
        "resourceId": (f"/subscriptions/{SUB}/resourceGroups/{RG}"
                       f"/providers/Microsoft.Insights/components/{APPINSIGHTS}"),
    }}))
    print(f"5. logger applicationInsights: {'OK' if r.ok else f'{r.status_code} {r.text[:250]}'}")
    if not r.ok:
        return

    diag_url = f"{ARM}{APIM_ID}/apis/{API}/diagnostics/applicationinsights?api-version=2024-05-01"
    r = requests.put(diag_url, headers=H, timeout=90, data=json.dumps({"properties": {
        "loggerId": f"{APIM_ID}/loggers/appinsights",
        "alwaysLog": "allErrors",
        "sampling": {"samplingType": "fixed", "percentage": 100.0},
        "metrics": True,
        "verbosity": "information",
    }}))
    print(f"6. diagnostic applicationinsights na API: "
          f"{'OK' if r.ok else f'{r.status_code} {r.text[:250]}'}")


def show_endpoint() -> None:
    base = f"https://{APIM}.azure-api.net/{API}/api/projects/" \
           f"{os.getenv('AZURE_AI_PROJECT_NAME', 'zava-project')}/openai/v1"
    print("\nEndpoint para os clientes:")
    print(f"   {base}")
    print("   header de auth: api-key: <subscription key>   (NAO Ocp-Apim-Subscription-Key)")
    print("\nPegue a chave com:")
    print(f"   az rest --method post --url \"{ARM}{APIM_ID}/subscriptions/master/listSecrets"
          f"?api-version=2024-05-01\" --query primaryKey -o tsv")


def main() -> None:
    print(f"AI Gateway: {APIM}  (API {API})\n")
    diagnostic_setting_to_log_analytics()
    enable_llm_logging()
    add_token_metric_policy()
    application_insights_logger()
    show_endpoint()


if __name__ == "__main__":
    main()
