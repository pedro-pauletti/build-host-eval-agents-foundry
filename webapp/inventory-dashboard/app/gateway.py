"""
Route model traffic through the **AI Gateway** (Azure API Management) instead of straight at
Foundry, so every call is logged, attributable and costable.

Two things make the FinOps tab work, and both live here:

* the **base URL** points at APIM rather than the Foundry project;
* the **caller headers** (``x-zava-caller`` / ``x-zava-agent``) are what the gateway policy turns
  into metric dimensions. Traffic without them still costs money but shows up as ``unknown``.

If ``AI_GATEWAY_ENDPOINT`` is unset the helpers fall back to the direct Foundry client, so the
app keeps working without a gateway — it just loses the cost breakdown.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from typing import Any

# APIM presents the Azure OpenAI convention: the subscription key rides on `api-key`,
# not the usual Ocp-Apim-Subscription-Key.
SUBSCRIPTION_HEADER = "api-key"


def gateway_endpoint() -> str:
    """Base URL of the gateway-fronted Foundry project, or '' when not configured."""
    return os.getenv("AI_GATEWAY_ENDPOINT", "").rstrip("/")


def enabled() -> bool:
    return bool(gateway_endpoint() and subscription_key())


@lru_cache(maxsize=1)
def subscription_key() -> str:
    """The APIM subscription key, from env or fetched once via ARM for local development."""
    key = os.getenv("AI_GATEWAY_KEY", "")
    if key:
        return key
    sub = os.getenv("AZURE_SUBSCRIPTION_ID", "")
    rg = os.getenv("AZURE_RESOURCE_GROUP", "")
    apim = os.getenv("AI_GATEWAY_NAME", "")
    if not (sub and rg and apim):
        return ""
    url = (f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
           f"/providers/Microsoft.ApiManagement/service/{apim}"
           f"/subscriptions/master/listSecrets?api-version=2024-05-01")
    out = subprocess.run(["az", "rest", "--method", "post", "--url", url,
                          "--query", "primaryKey", "-o", "tsv"],
                         capture_output=True, text=True, shell=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def headers(caller: str, agent: str = "none") -> dict[str, str]:
    """Auth plus the two dimensions the gateway policy stamps onto every token metric."""
    return {SUBSCRIPTION_HEADER: subscription_key(),
            "x-zava-caller": caller, "x-zava-agent": agent}


def openai_client(project_factory: Any, caller: str, agent: str = "none") -> Any:
    """An OpenAI client pointed at the gateway, falling back to the project client.

    ``project_factory`` is called only in the fallback path so the direct Foundry client is not
    constructed when the gateway is in use.
    """
    if not enabled():
        return project_factory()
    from openai import OpenAI
    return OpenAI(base_url=gateway_endpoint(), api_key=subscription_key(),
                  default_headers=headers(caller, agent))
