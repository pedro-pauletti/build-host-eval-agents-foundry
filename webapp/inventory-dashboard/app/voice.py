"""
Voice Live broker helpers.

Real Azure AI Foundry **Voice Live** integration: the browser talks to a FastAPI WebSocket
relay (see main.py `/api/voice/{agent}`), which authenticates with a Microsoft Entra token and
opens the Voice Live realtime WebSocket bound to the `gpt-realtime-mini` model. Each "agent"
(inventory | delivery) is configured with instructions + function tools that mirror the Zava
agents; the broker executes tool calls against the live Zava API and feeds results back.

Confirmed handshake: wss://<account>/voice-live/realtime?api-version=2026-06-01-preview&model=<deployment>
Auth: Authorization: Bearer <token>  (scope https://cognitiveservices.azure.com/.default)
"""
from __future__ import annotations

import json
import os

import httpx

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"

# Locales the caller may speak. Drives both speech recognition and the multilingual VAD; the
# reply is spoken back in whichever of these the caller used.
VOICE_LOCALES = [
    loc.strip()
    for loc in os.getenv("VOICE_LIVE_LOCALES", "en-US,pt-BR,es-ES,fr-FR,de-DE,it-IT").split(",")
    if loc.strip()
]

# Must be a *Multilingual* neural voice, otherwise non-English replies are spoken with a heavy
# English accent. The locale prefix is only the voice's home locale, not a language restriction.
VOICE_NAME = os.getenv("VOICE_LIVE_VOICE", "en-US-AvaMultilingualNeural")


def _account_host() -> str:
    return os.getenv("AZURE_AI_ACCOUNT_ENDPOINT", "").rstrip("/").replace("https://", "")


def _zava_api() -> str:
    return os.getenv(
        "ZAVA_API_BASE_URL",
        "https://zava-api.mangomushroom-5ccaccb7.eastus2.azurecontainerapps.io",
    ).rstrip("/")


def voice_live_url() -> str:
    account = _account_host()
    api_version = os.getenv("VOICE_LIVE_API_VERSION", "2026-06-01-preview")
    model = os.getenv("REALTIME_DEPLOYMENT_NAME", "gpt-realtime-mini")
    return f"wss://{account}/voice-live/realtime?api-version={api_version}&model={model}"


# --------------------------------------------------------------------------- #
# Tool schemas (function calling) per agent — mirror the Zava agents' tools
# --------------------------------------------------------------------------- #
_INVENTORY_TOOLS = [
    {"type": "function", "name": "get_inventory_summary",
     "description": "Zava inventory KPIs: product lines, total SKUs, facilities, retail stores, and status counts.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "get_inventory_alerts",
     "description": "Critical / low-stock alerts, most urgent first (facility, SKU, on-hand vs reorder point, days to stock-out).",
     "parameters": {"type": "object", "properties": {
         "facility": {"type": "string", "description": "Optional facility code like FC-CLT."},
         "severity": {"type": "string", "description": "critical or low", "enum": ["critical", "low"]}}}},
    {"type": "function", "name": "get_product_stock",
     "description": "On-hand stock for a SKU across all 7 facilities plus totals.",
     "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}},
    {"type": "function", "name": "get_line_stock",
     "description": "Total on-hand units and status counts for a product line (line_code C, R, P, or E).",
     "parameters": {"type": "object", "properties": {"line_code": {"type": "string"}}, "required": ["line_code"]}},
]

_DELIVERY_TOOLS = [
    {"type": "function", "name": "lookup_order",
     "description": "Look up a Zava order by numeric order id; returns the full tracking card.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}},
    {"type": "function", "name": "track_shipment",
     "description": "Track a shipment by order id or carrier tracking number (ZVX-...).",
     "parameters": {"type": "object", "properties": {
         "order_id": {"type": "string"}, "tracking_number": {"type": "string"}}}},
]

_INVENTORY_INSTRUCTIONS = (
    "You are the Zava InventoryAgent on a live voice call with an operations manager. Zava is a DTC "
    "athletic apparel brand (ZavaCore Field: Core, Pro, Premium, Elite) with inventory across 7 "
    "distribution centers (Memphis, Charlotte, Seattle, Dallas, Newark, Reno, Columbus). Always call a "
    "tool for live numbers — never invent SKUs, quantities, or alerts. Answer briefly and "
    "conversationally (this is spoken): lead with the number, name facilities/SKUs, and for critical "
    "stock call out the most urgent first. Spell SKUs clearly when asked."
)
_DELIVERY_INSTRUCTIONS = (
    "You are Zava DeliverySupport on a live voice call with a customer tracking a ZavaCore Field order. "
    "Always call lookup_order or track_shipment before answering — never invent order, delay, or ETA "
    "data. Be warm, concise, and clear (this is spoken): give the status, estimated delivery, last "
    "location, and whether any action is required. Explain weather/customs/volume delays and address "
    "exceptions plainly."
)

_LANGUAGE_RULE = (
    " Detect the language the customer speaks and reply in THAT language, matching it for the whole "
    "call. Speak it naturally and fluently — do not leave English words in a non-English sentence. "
    "Only SKUs, tracking numbers, order numbers, city names and product line names stay as-is."
)

AGENTS: dict[str, dict] = {
    "inventory": {"instructions": _INVENTORY_INSTRUCTIONS + _LANGUAGE_RULE, "tools": _INVENTORY_TOOLS,
                  "greeting": "Hi, this is the Zava inventory assistant. What would you like to check?"},
    "delivery": {"instructions": _DELIVERY_INSTRUCTIONS + _LANGUAGE_RULE, "tools": _DELIVERY_TOOLS,
                 "greeting": "Hi, this is Zava delivery support. Which order can I help you track?"},
}


def session_update(agent: str) -> dict:
    cfg = AGENTS[agent]
    return {
        "type": "session.update",
        "session": {
            "instructions": cfg["instructions"],
            "modalities": ["text", "audio"],
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            # azure-speech (not whisper-1) is what accepts a multi-locale list.
            "input_audio_transcription": {"model": "azure-speech", "language": ",".join(VOICE_LOCALES)},
            # azure-speech transcription requires an azure_semantic_vad* turn detector.
            "turn_detection": {"type": "azure_semantic_vad_multilingual", "threshold": 0.3,
                               "prefix_padding_ms": 200, "silence_duration_ms": 500,
                               "languages": VOICE_LOCALES},
            "tools": cfg["tools"],
            "tool_choice": "auto",
            "voice": {"name": VOICE_NAME, "type": "azure-standard"},
        },
    }


async def execute_tool(agent: str, name: str, args: dict) -> str:
    """Execute a Voice Live function call against the live Zava API; return a compact JSON string."""
    try:
        async with httpx.AsyncClient(base_url=_zava_api(), timeout=20.0) as c:
            if name == "get_inventory_summary":
                r = await c.get("/inventory/summary")
            elif name == "get_inventory_alerts":
                params = {"severity": args.get("severity") or "critical"}
                if args.get("facility"):
                    params["facility"] = args["facility"]
                r = await c.get("/inventory/alerts", params=params)
            elif name == "get_product_stock":
                r = await c.get(f"/products/{str(args.get('sku', '')).strip()}/stock")
            elif name == "get_line_stock":
                r = await c.get(f"/inventory/by-line/{str(args.get('line_code', '')).strip()}")
            elif name == "lookup_order":
                r = await c.get(f"/orders/{str(args.get('order_id', '')).strip()}")
            elif name == "track_shipment":
                if args.get("order_id"):
                    r = await c.get(f"/orders/{str(args['order_id']).strip()}")
                elif args.get("tracking_number"):
                    r = await c.get(f"/track/{str(args['tracking_number']).strip()}")
                else:
                    return json.dumps({"error": "provide order_id or tracking_number"})
            else:
                return json.dumps({"error": f"unknown tool {name}"})
        if r.status_code == 404:
            return json.dumps({"found": False, "message": "Not found. Please double-check the value."})
        r.raise_for_status()
        data = r.json()
        if name == "get_inventory_alerts" and isinstance(data, list):
            data = data[:8]  # keep spoken answers short
        return json.dumps(data)[:6000]
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)[:300]})
