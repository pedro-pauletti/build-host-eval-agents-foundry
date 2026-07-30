"""Foundry **Memory** integration for the web app.

The hosted DeliverySupport agent does the real recall/persist work (see
``agents/delivery-support-agent/src/memory.py``). The web app is the *observer*: it reads
the same memory store so the dashboard can show what the agent currently remembers about
the customer, emit a ``memory`` trace entry per turn, and give the presenter a one-click
"forget everything" reset between demo runs.

Reads are cached briefly because Foundry consolidates memories asynchronously — a fresh
read on every keystroke would be wasted work.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
_DELIVERY_SRC = _REPO / "agents" / "delivery-support-agent"

_cache: dict[str, Any] = {"expires": 0.0, "scope": None, "items": []}
_CACHE_SECONDS = float(os.getenv("MEMORY_CACHE_SECONDS", "3"))


def _memory() -> Any:
    path = str(_DELIVERY_SRC)
    if path not in sys.path:
        sys.path.insert(0, path)
    from src.memory import ZavaMemory  # type: ignore

    return ZavaMemory()


def memory_enabled() -> bool:
    return (os.getenv("DELIVERY_MEMORY_ENABLED", "true") or "").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def default_scope() -> str:
    return os.getenv("DELIVERY_MEMORY_SCOPE", "zava-customer-demo")


def store_name() -> str:
    return os.getenv("DELIVERY_MEMORY_STORE_NAME", "zava_delivery_memory")


def _sort_key(item: dict[str, Any]) -> tuple[int, int]:
    order = {"user_profile": 0, "procedural": 1, "chat_summary": 2}
    updated = item.get("updated_at")
    return (order.get(item.get("kind", ""), 3), -int(updated) if isinstance(updated, (int, float)) else 0)


async def list_memories(scope: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Return everything Foundry currently remembers for a customer scope."""
    scope = scope or default_scope()
    if not memory_enabled():
        return {"enabled": False, "scope": scope, "store": store_name(), "items": []}
    now = time.time()
    if not force and _cache["scope"] == scope and _cache["expires"] > now:
        return {"enabled": True, "scope": scope, "store": store_name(), "items": _cache["items"], "cached": True}
    try:
        items = await asyncio.to_thread(lambda: _memory().list_items(scope=scope))
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "scope": scope, "store": store_name(), "items": [], "error": str(exc)}
    items.sort(key=_sort_key)
    _cache.update({"expires": now + _CACHE_SECONDS, "scope": scope, "items": items})
    return {"enabled": True, "scope": scope, "store": store_name(), "items": items}


async def clear_memories(scope: str | None = None) -> dict[str, Any]:
    """Forget everything for one customer — the demo reset button."""
    scope = scope or default_scope()
    if not memory_enabled():
        return {"enabled": False, "scope": scope, "deleted": 0}
    try:
        await asyncio.to_thread(lambda: _memory().clear_scope(scope=scope))
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "scope": scope, "error": str(exc)}
    _cache.update({"expires": 0.0, "scope": None, "items": []})
    return {"enabled": True, "scope": scope, "cleared": True}


def memory_line(item: dict[str, Any]) -> str:
    """Readable one-liner (procedural memories are stored as JSON)."""
    content = (item.get("content") or "").strip()
    if item.get("kind") == "procedural" and content.startswith("{"):
        try:
            content = str(json.loads(content).get("instruction") or content)
        except (json.JSONDecodeError, ValueError):
            pass
    return content


def memory_trace(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Build a traces-panel entry describing the memory available to this turn."""
    if not payload.get("enabled"):
        return None
    items = payload.get("items") or []
    if payload.get("error"):
        return {
            "kind": "memory",
            "title": "Foundry Memory",
            "subtitle": payload.get("scope", ""),
            "status": "error",
            "detail": payload["error"],
        }
    kinds: dict[str, int] = {}
    for item in items:
        kinds[item.get("kind", "memory")] = kinds.get(item.get("kind", "memory"), 0) + 1
    breakdown = " · ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in kinds.items())
    return {
        "kind": "memory",
        "title": f"{len(items)} memor{'y' if len(items) == 1 else 'ies'} in scope",
        "subtitle": f"{payload.get('store')} · {payload.get('scope')}" + (f" · {breakdown}" if breakdown else ""),
        "status": "completed",
        "detail": "\n".join(f"• [{i.get('kind')}] {memory_line(i)}" for i in items) or None,
    }
