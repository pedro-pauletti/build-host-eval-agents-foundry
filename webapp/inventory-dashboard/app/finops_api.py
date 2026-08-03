"""
FinOps over the **AI Gateway** telemetry.

Every number here exists only because traffic goes through Azure API Management. Calling the
Foundry endpoint directly gives you a ``usage`` object per response and nothing else: nothing
aggregates it, nothing attributes it to a caller, nothing keeps it. The gateway turns those
scattered objects into a queryable ledger, which is what makes a cost breakdown possible at all.

Getting there needed three fixes that are easy to miss (all applied by
``scripts/setup_ai_gateway.py``):

1. A diagnostic entity **on the API**, not just on the service — otherwise no logs are emitted.
2. APIM's built-in LLM parser does not understand the Foundry Responses API, so it reports
   0 tokens. An outbound policy reads ``usage`` out of the response body instead.
3. ``emit-metric`` needs ``metrics: true`` **and** an Application Insights logger. Without both,
   the gateway trace shows the metric emitted with a null namespace and it goes nowhere.

The result lands in Log Analytics ``AppMetrics`` with three dimensions - Caller, Agent, Model -
which is exactly the axis a cost breakdown needs.

Cost is derived, not billed: token counts come from the gateway, prices from ``pricing.json``.

Environment:
    AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP
    LOG_ANALYTICS_WORKSPACE_NAME   default log-zava-cvm43wkpxaiyg
    AI_GATEWAY_NAME                default zava-demos-ai-gateway
"""
from __future__ import annotations

import json
import os
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

_PRICING_PATH = Path(__file__).parent / "pricing.json"
_CACHE: dict[str, Any] = {"key": None, "expires": 0.0, "payload": None}
_CACHE_SECONDS = float(os.getenv("FINOPS_CACHE_SECONDS", "20"))

_credential: Any = None
_client: Any = None
_workspace_id: str | None = None

# The four metrics the outbound policy emits, and how they map onto a bill.
METRICS = ("PromptTokens", "CompletionTokens", "CachedTokens", "Calls")


def pricing() -> dict[str, Any]:
    return json.loads(_PRICING_PATH.read_text(encoding="utf-8"))


def gateway_name() -> str:
    return os.getenv("AI_GATEWAY_NAME", "zava-demos-ai-gateway")


def _cred() -> Any:
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential
        _credential = DefaultAzureCredential(exclude_interactive_browser_credential=True,
                                             process_timeout=30)
    return _credential


def workspace_id() -> str | None:
    """Log Analytics *customer id*, resolved once through ARM."""
    global _workspace_id
    if _workspace_id is not None:
        return _workspace_id or None
    sub = os.getenv("AZURE_SUBSCRIPTION_ID", "")
    rg = os.getenv("AZURE_RESOURCE_GROUP", "")
    name = os.getenv("LOG_ANALYTICS_WORKSPACE_NAME", "log-zava-cvm43wkpxaiyg")
    if not (sub and rg and name):
        _workspace_id = ""
        return None
    import requests
    token = _cred().get_token("https://management.azure.com/.default").token
    url = (f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
           f"/providers/Microsoft.OperationalInsights/workspaces/{name}?api-version=2022-10-01")
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    _workspace_id = r.json().get("properties", {}).get("customerId", "") if r.ok else ""
    return _workspace_id or None


def _query(kql: str, hours: int) -> list[dict[str, Any]]:
    global _client
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
    if _client is None:
        _client = LogsQueryClient(_cred())
    ws = workspace_id()
    if not ws:
        raise RuntimeError("Log Analytics workspace not resolved — check AZURE_* env vars.")
    resp = _client.query_workspace(ws, kql, timespan=timedelta(hours=hours))
    if resp.status == LogsQueryStatus.FAILURE:
        raise RuntimeError(str(resp.partial_error or "query failed")[:300])
    tables = resp.tables if resp.status == LogsQueryStatus.SUCCESS else resp.partial_data
    rows: list[dict[str, Any]] = []
    for table in tables or []:
        cols = list(table.columns)
        rows.extend(dict(zip(cols, row)) for row in table.rows)
    return rows


def _rate(model: str) -> dict[str, float]:
    table = pricing()
    key = (model or "").strip()
    if key in table["models"]:
        return table["models"][key]
    # Deployment names carry suffixes, e.g. gpt-realtime-mini-global-standard.
    for name, rate in table["models"].items():
        if key.startswith(name):
            return rate
    return table["default"]


def cost_of(model: str, prompt: int, completion: int, cached: int = 0) -> float:
    rate = _rate(model)
    per = pricing()["per"]
    fresh_input = max(prompt - cached, 0)
    return (fresh_input * rate["input"]
            + cached * rate.get("cached", rate["input"])
            + completion * rate["output"]) / per


# One pass over AppMetrics, pivoting the four metric names into columns so a row is a
# (caller, agent, model) bucket with everything needed to price it.
_PIVOT = """
AppMetrics
| where Name in ('PromptTokens', 'CompletionTokens', 'CachedTokens', 'Calls')
| extend d = parse_json(Properties)
| extend Caller = tostring(d['Caller']), Agent = tostring(d['Agent']), Model = tostring(d['Model'])
| where isnotempty(Model)
"""


def _bucketed(group_by: str, hours: int) -> list[dict[str, Any]]:
    return _query(_PIVOT + f"""
        | summarize Value = sum(Sum) by Name, {group_by}
        | evaluate pivot(Name, sum(Value))
    """, hours)


def _row(entry: dict[str, Any]) -> dict[str, int]:
    return {
        "prompt": int(entry.get("PromptTokens") or 0),
        "completion": int(entry.get("CompletionTokens") or 0),
        "cached": int(entry.get("CachedTokens") or 0),
        "calls": int(entry.get("Calls") or 0),
    }


def _grouped(dimension: str, label: str, hours: int) -> list[dict[str, Any]]:
    """Group by one dimension, keeping Model so each bucket can be priced correctly."""
    try:
        rows = _bucketed(f"{dimension}, Model", hours)
    except Exception:
        return []
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get(dimension) or "unknown")
        v = _row(r)
        e = agg.setdefault(key, {label: key, "prompt": 0, "completion": 0, "cached": 0,
                                 "calls": 0, "cost": 0.0, "models": []})
        for k in ("prompt", "completion", "cached", "calls"):
            e[k] += v[k]
        e["cost"] = round(e["cost"] + cost_of(r.get("Model") or "", v["prompt"],
                                              v["completion"], v["cached"]), 6)
        model = r.get("Model")
        if model and model not in e["models"]:
            e["models"].append(model)
    for e in agg.values():
        e["total"] = e["prompt"] + e["completion"]
    return sorted(agg.values(), key=lambda x: -x["cost"])


def summary(hours: int = 24) -> dict[str, Any]:
    key = f"summary:{hours}"
    now = time.time()
    if _CACHE["key"] == key and _CACHE["expires"] > now:
        return _CACHE["payload"]

    out: dict[str, Any] = {
        "gateway": gateway_name(),
        "hours": hours,
        "currency": pricing()["currency"],
        "enabled": True,
        "totals": {"calls": 0, "prompt": 0, "completion": 0, "cached": 0, "total": 0, "cost": 0.0},
        "by_model": [], "by_agent": [], "by_caller": [], "timeline": [],
    }

    try:
        rows = _bucketed("Model", hours)
    except Exception as exc:
        out["enabled"] = False
        out["error"] = str(exc)[:300]
        return out

    for r in rows:
        model = r.get("Model") or "unknown"
        v = _row(r)
        cost = cost_of(model, v["prompt"], v["completion"], v["cached"])
        rate = _rate(model)
        out["by_model"].append({
            "model": model, **v, "total": v["prompt"] + v["completion"],
            "cost": round(cost, 6), "rate_in": rate["input"], "rate_out": rate["output"],
        })
        t = out["totals"]
        for k in ("prompt", "completion", "cached", "calls"):
            t[k] += v[k]
        t["cost"] = round(t["cost"] + cost, 6)

    t = out["totals"]
    t["total"] = t["prompt"] + t["completion"]
    t["cost_per_call"] = round(t["cost"] / t["calls"], 6) if t["calls"] else 0.0
    t["cached_pct"] = round(100 * t["cached"] / t["prompt"], 1) if t["prompt"] else 0.0
    out["by_model"].sort(key=lambda x: -x["cost"])

    out["by_agent"] = _grouped("Agent", "agent", hours)
    out["by_caller"] = _grouped("Caller", "caller", hours)

    try:
        bucket = "5m" if hours <= 6 else ("1h" if hours <= 48 else "1d")
        rows = _query(_PIVOT + f"""
            | summarize Value = sum(Sum) by Name, Model, bin(TimeGenerated, {bucket})
            | evaluate pivot(Name, sum(Value))
            | order by TimeGenerated asc
        """, hours)
        buckets: dict[str, dict[str, Any]] = {}
        for r in rows:
            ts = str(r.get("TimeGenerated"))
            v = _row(r)
            e = buckets.setdefault(ts, {"t": ts, "prompt": 0, "completion": 0,
                                        "calls": 0, "cost": 0.0})
            for k in ("prompt", "completion", "calls"):
                e[k] += v[k]
            e["cost"] = round(e["cost"] + cost_of(r.get("Model") or "", v["prompt"],
                                                  v["completion"], v["cached"]), 6)
        out["timeline"] = list(buckets.values())
    except Exception:
        out["timeline"] = []

    # A month of the current run rate — the number a demo audience actually reacts to.
    if hours and t["cost"]:
        out["projection"] = {
            "per_day": round(t["cost"] * 24 / hours, 4),
            "per_month": round(t["cost"] * 24 * 30 / hours, 2),
        }

    _CACHE.update({"key": key, "expires": now + _CACHE_SECONDS, "payload": out})
    return out
