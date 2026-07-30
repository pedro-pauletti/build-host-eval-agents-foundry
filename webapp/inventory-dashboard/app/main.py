import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
import websockets as wslib
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import voice as voicemod
from . import orchestration_api as orchmod
from . import memory_api as memmod
from . import evals_api as evalmod

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
for candidate_dir in (APP_DIR, *APP_DIR.parents):
    env_file = candidate_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        break
else:
    load_dotenv()

PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
MODEL_DEPLOYMENT = os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
AI_ACCOUNT_ENDPOINT = os.getenv("AZURE_AI_ACCOUNT_ENDPOINT", "")
REALTIME_DEPLOYMENT = os.getenv("REALTIME_DEPLOYMENT_NAME", "gpt-realtime-mini")
ZAVA_API_BASE_URL = os.getenv("ZAVA_API_BASE_URL", "https://zava-api.mangomushroom-5ccaccb7.eastus2.azurecontainerapps.io").rstrip("/")
AGENT_NAME = os.getenv("INVENTORY_AGENT_NAME", "InventoryAgent")
DELIVERY_AGENT_ENDPOINT = os.getenv("DELIVERY_AGENT_ENDPOINT", "").rstrip("/")
DELIVERY_AGENT_NAME = os.getenv("DELIVERY_AGENT_NAME", "DeliverySupport")
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
DASHBOARD_TTL_SECONDS = int(os.getenv("DASHBOARD_CACHE_SECONDS", "45"))
CARD_LIMIT_PER_LINE = int(os.getenv("DASHBOARD_CARD_LIMIT_PER_LINE", "12"))

credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
app = FastAPI(title="Zava Inventory Dashboard")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_dashboard_cache: dict[str, Any] = {"expires": 0.0, "payload": None}


@app.on_event("startup")
async def _warm_memory() -> None:
    """Build the Foundry Memory client up front (Entra token + store lookup is slow once)."""
    if memmod.memory_enabled():
        asyncio.create_task(memmod.list_memories(force=True))


class ChatRequest(BaseModel):
    message: str
    agent: str = "inventory"
    previous_response_id: str | None = None


def _require_config(name: str, value: str) -> None:
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing required configuration: {name}")


async def _get_json(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{ZAVA_API_BASE_URL}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _status_rank(status: str | None) -> int:
    normalized = (status or "").lower()
    return {"critical": 3, "low stock": 2, "in stock": 1}.get(normalized, 0)


def _worst_status(facilities: list[dict[str, Any]]) -> str:
    if not facilities:
        return "in stock"
    return max((facility.get("status", "in stock") for facility in facilities), key=_status_rank)


def _stock_card(product: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    facilities = stock.get("facilities") or []
    totals = stock.get("totals") or {}
    qty = totals.get("on_hand")
    if qty is None:
        qty = sum(int(facility.get("on_hand") or 0) for facility in facilities)
    qty = int(qty or 0)
    return {
        "sku": product.get("sku"),
        "name": product.get("name") or stock.get("name"),
        "qty": qty,
        "status": _worst_status(facilities),
    }


async def _line_cards(client: httpx.AsyncClient, line: dict[str, Any]) -> dict[str, Any]:
    products = await _get_json(client, "/products", line=line["line_code"])
    selected = products[:CARD_LIMIT_PER_LINE]
    stock_results = await asyncio.gather(
        *[_get_json(client, f"/products/{product['sku']}/stock") for product in selected],
        return_exceptions=True,
    )
    cards = []
    for product, stock in zip(selected, stock_results):
        if isinstance(stock, Exception):
            cards.append({"sku": product.get("sku"), "name": product.get("name"), "qty": 0, "status": "critical"})
        else:
            cards.append(_stock_card(product, stock))
    return {
        "line_code": line.get("line_code"),
        "name": line.get("product_line"),
        "channel": line.get("channel", "B2C"),
        "cards": cards,
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/dashboard")
async def dashboard() -> dict[str, Any]:
    now = time.monotonic()
    if _dashboard_cache["payload"] and _dashboard_cache["expires"] > now:
        return _dashboard_cache["payload"]

    async with httpx.AsyncClient(timeout=25.0) as client:
        summary, product_lines = await asyncio.gather(
            _get_json(client, "/inventory/summary"),
            _get_json(client, "/product-lines"),
        )
        product_lines = sorted(product_lines, key=lambda item: item.get("tier_rank", 0), reverse=True)
        lines = await asyncio.gather(*[_line_cards(client, line) for line in product_lines])

    payload = {
        "kpis": {
            "product_lines": summary.get("product_lines", len(lines)),
            "total_skus": summary.get("total_skus"),
            "facilities": summary.get("facilities"),
            "retail_stores": summary.get("retail_stores"),
        },
        "status_counts": summary.get("status_counts", {}),
        "lines": lines,
    }
    _dashboard_cache.update({"expires": now + DASHBOARD_TTL_SECONDS, "payload": payload})
    return payload


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    if hasattr(response, "model_dump_json"):
        return response.model_dump_json(indent=2)
    return str(response)


def _shorten(value: Any, limit: int = 1400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + " …"


def _classify_tool(name: str, server_label: str) -> str:
    lowered = f"{name} {server_label}".lower()
    if "knowledge_base" in lowered or "zava_kb" in lowered:
        return "kb"
    if "dataagent" in lowered or "fabric" in lowered:
        return "fabric"
    return "tool"


def _build_trace(response: Any) -> list[dict[str, Any]]:
    """Turn a Responses payload into UI trace entries (toolbox discovery, tool calls, KB hits...)."""
    data = response if isinstance(response, dict) else response.model_dump()
    trace: list[dict[str, Any]] = []
    agent_ref = data.get("agent_reference") or {}
    started = data.get("created_at")
    finished = data.get("completed_at")

    trace.append({
        "kind": "model",
        "title": data.get("model") or MODEL_DEPLOYMENT,
        "subtitle": f"{agent_ref.get('name') or AGENT_NAME} v{agent_ref.get('version') or '?'}",
        "status": data.get("status") or "completed",
        "detail": None,
    })

    for item in data.get("output") or []:
        item_type = item.get("type")
        if item_type == "mcp_list_tools":
            names = [t.get("name") for t in item.get("tools") or [] if t.get("name")]
            trace.append({
                "kind": "toolbox",
                "title": item.get("server_label") or "mcp",
                "subtitle": f"{len(names)} tool{'s' if len(names) != 1 else ''} discovered",
                "status": "error" if item.get("error") else "completed",
                "detail": "\n".join(f"• {n}" for n in names) or None,
            })
        elif item_type == "mcp_call":
            name = item.get("name") or "tool"
            server = item.get("server_label") or ""
            kind = _classify_tool(name, server)
            output = item.get("output") or ""
            subtitle = server
            if kind == "kb":
                match = re.search(r"Retrieved (\d+) documents", str(output))
                if match:
                    subtitle = f"{server} · {match.group(1)} documents"
            trace.append({
                "kind": kind,
                "title": name.replace("zava_tools___", ""),
                "subtitle": subtitle,
                "status": "error" if item.get("error") else (item.get("status") or "completed"),
                "args": _shorten(item.get("arguments") or "{}", 600),
                "detail": _shorten(item.get("error") or output),
            })
        elif item_type == "function_call":
            trace.append({
                "kind": "tool",
                "title": item.get("name") or "function",
                "subtitle": "function_call",
                "status": item.get("status") or "completed",
                "args": _shorten(item.get("arguments") or "{}", 600),
                "detail": None,
            })
        elif item_type == "message":
            for content in item.get("content") or []:
                cites = [
                    {"title": a.get("title") or a.get("url"), "url": a.get("url")}
                    for a in content.get("annotations") or []
                    if a.get("url")
                ]
                if cites:
                    trace.append({
                        "kind": "citation",
                        "title": f"{len(cites)} citation{'s' if len(cites) != 1 else ''}",
                        "subtitle": "grounding sources",
                        "status": "completed",
                        "detail": "\n".join(f"• {c['title']}" for c in cites),
                    })

    usage = data.get("usage") or {}
    if usage:
        trace.append({
            "kind": "usage",
            "title": f"{usage.get('total_tokens', '?')} tokens",
            "subtitle": f"in {usage.get('input_tokens', '?')} · out {usage.get('output_tokens', '?')}"
            + (f" · {finished - started}s" if isinstance(started, int) and isinstance(finished, int) else ""),
            "status": "completed",
            "detail": None,
        })
    return trace


async def _call_delivery_agent(message: str, previous_response_id: str | None) -> dict[str, Any]:
    if not DELIVERY_AGENT_ENDPOINT:
        raise HTTPException(status_code=500, detail="DELIVERY_AGENT_ENDPOINT is not configured")
    body: dict[str, Any] = {"input": message}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(DELIVERY_AGENT_ENDPOINT, json=body, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    answer_parts: list[str] = []
    order: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = [{
        "kind": "model",
        "title": os.getenv("MODEL_ROUTER_DEPLOYMENT_NAME", "model-router"),
        "subtitle": f"{DELIVERY_AGENT_NAME} · Foundry hosted agent (MAF)",
        "status": data.get("status") or "completed",
        "detail": None,
    }]
    pending: dict[str, dict[str, Any]] = {}
    for item in data.get("output", []) or []:
        if item.get("type") == "message":
            for content in item.get("content", []) or []:
                if content.get("type") == "output_text" and content.get("text"):
                    answer_parts.append(content["text"])
        elif item.get("type") == "function_call":
            entry = {
                "kind": "tool",
                "title": item.get("name") or "function",
                "subtitle": "in-process MAF tool",
                "status": "completed",
                "args": _shorten(item.get("arguments") or "{}", 600),
                "detail": None,
            }
            pending[item.get("call_id") or item.get("id") or ""] = entry
            trace.append(entry)
        elif item.get("type") == "function_call_output":
            raw = item.get("output") or ""
            entry = pending.get(item.get("call_id") or "")
            if entry is not None:
                entry["detail"] = _shorten(raw)
            try:
                parsed = json.loads(raw or "{}")
                if isinstance(parsed, dict) and parsed.get("tracking_card"):
                    order = parsed["tracking_card"]
            except (json.JSONDecodeError, TypeError):
                pass
    usage = data.get("usage") or {}
    if usage:
        trace.append({
            "kind": "usage",
            "title": f"{usage.get('total_tokens', '?')} tokens",
            "subtitle": f"in {usage.get('input_tokens', '?')} · out {usage.get('output_tokens', '?')}",
            "status": "completed",
            "detail": None,
        })

    # Foundry Memory runs *inside* the hosted agent; read the same store so the traces
    # panel and the dashboard can show what the customer profile looks like right now.
    memory = await memmod.list_memories(force=True)
    entry = memmod.memory_trace(memory)
    if entry is not None:
        trace.insert(1, entry)

    return {
        "answer": "\n".join(answer_parts) or "(no answer)",
        "response_id": data.get("id") or data.get("response_id"),
        "order": order,
        "trace": trace,
        "memory": memory,
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    if payload.agent == "delivery":
        try:
            return await _call_delivery_agent(payload.message, payload.previous_response_id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Delivery agent request failed: {exc}") from exc

    _require_config("AZURE_AI_PROJECT_ENDPOINT", PROJECT_ENDPOINT)

    def invoke_agent() -> Any:
        project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
        client = project.get_openai_client()
        kwargs: dict[str, Any] = {
            "model": MODEL_DEPLOYMENT,
            "input": payload.message,
            "extra_body": {"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}},
        }
        if payload.previous_response_id:
            kwargs["previous_response_id"] = payload.previous_response_id
        return client.responses.create(**kwargs)

    try:
        response = await asyncio.to_thread(invoke_agent)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
        message = str(exc)
        if status_code == 429 or "429" in message or "rate limit" in message.lower():
            raise HTTPException(status_code=429, detail="The inventory agent is currently rate limited. Please retry shortly.") from exc
        raise HTTPException(status_code=502, detail=f"Inventory agent request failed: {message}") from exc

    return {
        "answer": _extract_response_text(response),
        "response_id": getattr(response, "id", None),
        "order": None,
        "trace": _build_trace(response),
    }


@app.get("/api/order/{order_id}")
async def get_order(order_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=25.0) as client:
        resp = await client.get(f"{ZAVA_API_BASE_URL}/orders/{order_id.strip()}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    resp.raise_for_status()
    return resp.json()


@app.get("/api/memory")
async def get_memory(scope: str | None = None) -> dict[str, Any]:
    """What Foundry Memory currently holds for a customer scope."""
    return await memmod.list_memories(scope, force=True)


@app.delete("/api/memory")
async def delete_memory(scope: str | None = None) -> dict[str, Any]:
    """Forget everything for a customer scope (demo reset)."""
    return await memmod.clear_memories(scope)


@app.get("/api/evals")
async def list_evals() -> dict[str, Any]:
    """Evaluations registered in the Foundry project, with their latest run summary."""
    return await evalmod.list_evaluations()


@app.get("/api/evals/{eval_id}/runs")
async def list_eval_runs(eval_id: str) -> dict[str, Any]:
    """All runs of one evaluation (pass/fail per testing criterion)."""
    return await evalmod.list_runs(eval_id)


@app.get("/api/evals/{eval_id}/runs/{run_id}/items")
async def list_eval_items(eval_id: str, run_id: str) -> dict[str, Any]:
    """Per-row results: query, agent answer, and each evaluator's score/label/reason."""
    return await evalmod.list_items(eval_id, run_id)


@app.get("/api/orchestration/scenario")
async def orchestration_scenario() -> dict[str, Any]:
    return orchmod.scenario_info()

@app.websocket("/api/orchestration/run")
async def orchestration_run(ws: WebSocket) -> None:
    """Run the incident-response orchestration in-process and stream harness events.

    The browser sends a JSON message ``{"incident": "..."}`` (or ``{}`` for the seeded
    incident). We then run Triage -> Code Fix -> Compliance and forward every event
    (agent_started / harness_step / agent_completed / run_completed) so the page can
    animate the flow diagram and fill the per-agent dashboard in real time.
    """
    await ws.accept()
    try:
        first = await ws.receive_text()
        try:
            payload = json.loads(first) if first else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        incident = (payload.get("incident") or "").strip() or orchmod.default_incident_text()
        async for event in orchmod.stream_incident(incident):
            await ws.send_json(event)
        await ws.send_json({"type": "done", "agent": "orchestrator"})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"type": "error", "agent": "orchestrator", "note": str(exc)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


@app.get("/api/voice/config")
async def voice_config() -> dict[str, Any]:
    return {
        "available": bool(AI_ACCOUNT_ENDPOINT),
        "deployment": REALTIME_DEPLOYMENT,
        "agents": list(voicemod.AGENTS.keys()),
        "sample_rate": 24000,
    }


@app.websocket("/api/voice/{agent}")
async def voice_ws(client_ws: WebSocket, agent: str) -> None:
    """Broker: relay audio/events between the browser and the Voice Live realtime WebSocket.

    The browser cannot set the Authorization header on a native WebSocket, so this endpoint mints an
    Entra token, opens the Voice Live socket bound to gpt-realtime-mini with the agent's tools, and
    relays both directions — executing tool calls against the live Zava API.
    """
    await client_ws.accept()
    if agent not in voicemod.AGENTS:
        await client_ws.send_json({"type": "error", "error": {"message": f"unknown agent '{agent}'"}})
        await client_ws.close()
        return
    if not AI_ACCOUNT_ENDPOINT:
        await client_ws.send_json({"type": "error", "error": {"message": "AZURE_AI_ACCOUNT_ENDPOINT not configured"}})
        await client_ws.close()
        return
    try:
        token = (await asyncio.to_thread(credential.get_token, COGNITIVE_SCOPE)).token
    except Exception as exc:  # noqa: BLE001
        await client_ws.send_json({"type": "error", "error": {"message": f"auth failed: {exc}"}})
        await client_ws.close()
        return

    url = voicemod.voice_live_url()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        try:
            vl = await wslib.connect(url, additional_headers=headers, open_timeout=25, max_size=None)
        except TypeError:
            vl = await wslib.connect(url, extra_headers=headers, open_timeout=25, max_size=None)
    except Exception as exc:  # noqa: BLE001
        await client_ws.send_json({"type": "error", "error": {"message": f"Voice Live connect failed: {exc}"}})
        await client_ws.close()
        return

    async with vl:
        await vl.send(json.dumps(voicemod.session_update(agent)))

        async def browser_to_vl() -> None:
            try:
                while True:
                    await vl.send(await client_ws.receive_text())
            except (WebSocketDisconnect, Exception):  # noqa: BLE001
                pass
            finally:
                await vl.close()

        async def vl_to_browser() -> None:
            try:
                async for raw in vl:
                    try:
                        await client_ws.send_text(raw)
                    except Exception:  # noqa: BLE001
                        break
                    try:
                        evt = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if evt.get("type") == "response.function_call_arguments.done":
                        try:
                            args = json.loads(evt.get("arguments") or "{}")
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        result = await voicemod.execute_tool(agent, evt.get("name"), args)
                        await vl.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {"type": "function_call_output", "call_id": evt.get("call_id"), "output": result},
                        }))
                        await vl.send(json.dumps({"type": "response.create"}))
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    await client_ws.close()
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.gather(browser_to_vl(), vl_to_browser())

