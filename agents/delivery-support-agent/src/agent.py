from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Annotated, Any

import httpx
from agent_framework import Agent, tool
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from pydantic import Field

try:
    from agent_framework.foundry import FoundryChatClient
except ImportError:  # pragma: no cover - version-dependent fallback
    FoundryChatClient = None  # type: ignore[assignment]

if __package__:
    from .memory import build_memory_provider
else:  # pragma: no cover - direct execution
    from memory import build_memory_provider  # type: ignore[no-redef]


AGENT_NAME = "DeliverySupport"
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"

INSTRUCTIONS = """
You are DeliverySupport, Zava's concise and empathetic order-tracking assistant.
Zava is ZavaCore Field athletic apparel. Customers track orders by numeric order ID
or carrier tracking number.

Rules:
- Never invent order, delivery, delay, or exception data.
- For every new order ID, tracking number, or explicit tracking request, call the
  lookup_order or track_shipment tool before answering.
- Use conversation/session history for follow-ups such as "when will it arrive?" so
  you can answer about the previously discussed order without asking for the order
  number again.
- You have long-term memory across sessions. When KNOWN CUSTOMER CONTEXT is provided,
  treat it as already confirmed: greet the customer by name, honour their stated
  delivery preferences, and never ask them to repeat something you already remember.
- When a customer tells you a durable preference ("always leave it with the concierge",
  "text me instead of emailing"), acknowledge it briefly so they know it is remembered.
- Include the exact current status label, ETA, last location, destination, and whether
  customer action is required when those fields are available.
- Explain weather/customs/volume delays and address exceptions plainly.
- Keep answers brief, warm, and useful.
""".strip()


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _format_date_for_customer(value: str | None) -> str | None:
    if not value:
        return value
    try:
        parsed = date.fromisoformat(value)
        return parsed.strftime("%b %d, %Y")
    except ValueError:
        return value


def _tracking_card(order: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "order_id": order.get("order_id"),
        "recipient": order.get("recipient_name") or order.get("recipient"),
        "status_label": order.get("status_label"),
        "carrier": order.get("carrier"),
        "tracking_number": order.get("tracking_number"),
        "estimated_delivery": order.get("estimated_delivery"),
        "estimated_delivery_display": _format_date_for_customer(order.get("estimated_delivery")),
        "last_location": order.get("last_location"),
        "deliver_city": order.get("deliver_city"),
        "deliver_state": order.get("deliver_state"),
        "deliver_zip": order.get("deliver_zip"),
        "delivering_to": order.get("delivering_to"),
        "delay_reason": order.get("delay_reason"),
        "notes": order.get("notes"),
        "last_updated": order.get("last_updated"),
    }
    return {key: value for key, value in fields.items() if value not in (None, "")}


async def _get_json(path: str) -> dict[str, Any]:
    base_url = _env("ZAVA_API_BASE_URL").rstrip("/")
    async with httpx.AsyncClient(base_url=base_url, timeout=20.0) as client:
        response = await client.get(path)
    if response.status_code == 404:
        return {
            "found": False,
            "message": "I couldn't find that Zava order or tracking number. Please check the number and try again.",
        }
    response.raise_for_status()
    return {"found": True, "tracking_card": _tracking_card(response.json())}


@tool(approval_mode="never_require")
async def lookup_order(
    order_id: Annotated[str, Field(description="The numeric Zava order ID, for example 23518.")],
) -> str:
    """Look up a Zava order by numeric order ID and return its tracking card."""
    clean_order_id = str(order_id).strip()
    print(f"[tool] lookup_order(order_id={clean_order_id})", flush=True)
    result = await _get_json(f"/orders/{clean_order_id}")
    return json.dumps(result, ensure_ascii=False)


@tool(approval_mode="never_require")
async def track_shipment(
    order_id: Annotated[str, Field(description="Optional numeric Zava order ID.")] = "",
    tracking_number: Annotated[str, Field(description="Optional carrier tracking number, for example ZVX-7489201374829.")] = "",
) -> str:
    """Track a shipment by order ID or tracking number."""
    clean_order_id = str(order_id).strip()
    clean_tracking_number = str(tracking_number).strip()
    print(
        f"[tool] track_shipment(order_id={clean_order_id}, tracking_number={clean_tracking_number})",
        flush=True,
    )
    if clean_order_id:
        result = await _get_json(f"/orders/{clean_order_id}")
    elif clean_tracking_number:
        result = await _get_json(f"/track/{clean_tracking_number}")
    else:
        result = {
            "found": False,
            "message": "Please provide either an order ID or a tracking number.",
        }
    return json.dumps(result, ensure_ascii=False)


def _build_client() -> Any:
    project_endpoint = _env("AZURE_AI_PROJECT_ENDPOINT", os.getenv("FOUNDRY_PROJECT_ENDPOINT"))
    model = _env("MODEL_ROUTER_DEPLOYMENT_NAME", os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model-router"))
    credential = DefaultAzureCredential()

    # FoundryChatClient is the preferred Foundry path, but model-router currently
    # rejects the Responses API encrypted-reasoning include it adds for stateless
    # replay. Use the Azure OpenAI chat-completions client with Microsoft Entra
    # auth for this live demo, and retain FoundryChatClient as a version fallback.
    try:
        from agent_framework.openai import OpenAIChatCompletionClient

        account_endpoint = _env("AZURE_AI_ACCOUNT_ENDPOINT").rstrip("/")
        token_provider = get_bearer_token_provider(credential, COGNITIVE_SERVICES_SCOPE)
        return OpenAIChatCompletionClient(
            model=model,
            azure_endpoint=account_endpoint,
            credential=token_provider,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        )
    except Exception:
        if FoundryChatClient is not None:
            return FoundryChatClient(
                project_endpoint=project_endpoint,
                model=model,
                credential=credential,
            )
        raise


def create_delivery_support_agent(memory_scope: str | None = None) -> Agent:
    """Create the MAF chat agent used locally and by Foundry hosting.

    Foundry Memory is attached as a MAF ``ContextProvider``: it recalls the customer's
    durable preferences before every turn and hands the finished turn back to Foundry for
    extraction. Set ``DELIVERY_MEMORY_ENABLED=false`` to run without it.
    """
    context_providers = []
    provider = build_memory_provider(memory_scope)
    if provider is not None:
        context_providers.append(provider)

    return Agent(
        client=_build_client(),
        name=AGENT_NAME,
        instructions=INSTRUCTIONS,
        tools=[lookup_order, track_shipment],
        context_providers=context_providers or None,
    )


# Current Python Agent Framework exposes `Agent` as the chat-agent type.
ChatAgent = Agent


def load_environment() -> None:
    load_dotenv(override=False)
