"""**Foundry Memory** for the DeliverySupport agent.

Order tracking is the one Zava conversation that is genuinely *personal* and *recurring*:
the same customer comes back days later, from a different device, about a different
parcel. Foundry Memory (preview) gives that continuity — the agent remembers the
customer's name, their delivery preferences ("leave it with the concierge"), their
notification habits and the orders they already asked about, without the app having to
build its own profile database.

Two pieces live here:

* :class:`ZavaMemory` — a thin wrapper over the Foundry **Memory Store API**
  (``project_client.beta.memory_stores``): create the store, ``recall`` relevant memories
  for the current turn, ``remember`` the turn afterwards, plus list/clear helpers used by
  the web app and the notebook.
* :class:`FoundryMemoryProvider` — a Microsoft Agent Framework
  :class:`~agent_framework.ContextProvider` that plugs :class:`ZavaMemory` into the agent
  run loop: ``before_run`` injects the recalled memories as extra instructions, and
  ``after_run`` hands the completed turn back to Foundry for extraction.

Why a context provider instead of the ``memory_search_preview`` tool? That hosted tool is
attached to a **Foundry prompt agent** (see notebook 01 for that pattern). DeliverySupport
is a **hosted MAF agent** that runs our own Python, so it uses the memory *APIs* directly —
the pattern the docs call the "proxy / backend" scenario. The result is identical: durable,
per-customer memory managed by Foundry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from agent_framework import ContextProvider

logger = logging.getLogger(__name__)

DEFAULT_STORE_NAME = "zava_delivery_memory"
DEFAULT_SCOPE = "zava-customer-demo"

# What Foundry should (and should not) extract from a delivery conversation.
USER_PROFILE_DETAILS = (
    "Remember the customer's preferred name, delivery preferences (safe place, concierge, "
    "signature requirements, preferred delivery window), preferred carrier, notification "
    "channel, accessibility needs, and the Zava orders or tracking numbers they follow. "
    "Do not store payment details, full street addresses, credentials, government IDs, "
    "precise geolocation, age or any other sensitive personal data."
)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def memory_enabled() -> bool:
    """``DELIVERY_MEMORY_ENABLED=false`` turns the whole feature off (demo kill-switch)."""
    return _env_flag("DELIVERY_MEMORY_ENABLED", True)


def store_name() -> str:
    return os.getenv("DELIVERY_MEMORY_STORE_NAME", DEFAULT_STORE_NAME)


def default_scope() -> str:
    """Scope = the memory partition. One scope per customer keeps memories isolated."""
    return os.getenv("DELIVERY_MEMORY_SCOPE", DEFAULT_SCOPE)


def update_delay() -> int:
    """Seconds of inactivity Foundry waits before consolidating a turn into memory."""
    return int(os.getenv("DELIVERY_MEMORY_UPDATE_DELAY", "5"))


class ZavaMemory:
    """Thin, synchronous wrapper over the Foundry Memory Store API."""

    def __init__(self, project_client: Any | None = None, name: str | None = None) -> None:
        self._client = project_client
        self.name = name or store_name()

    # -- client ------------------------------------------------------------
    @property
    def client(self) -> Any:
        if self._client is None:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ["FOUNDRY_PROJECT_ENDPOINT"]
            self._client = AIProjectClient(
                endpoint=endpoint,
                credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
            )
        return self._client

    @property
    def stores(self) -> Any:
        return self.client.beta.memory_stores

    # -- store lifecycle ---------------------------------------------------
    def ensure_store(self, *, ttl_days: int = 30, description: str | None = None) -> Any:
        """Create the memory store if it does not exist yet; return its details.

        ``chat_model`` powers memory *extraction* (turning a transcript into durable facts)
        and ``embedding_model`` powers semantic *retrieval*.
        """
        from azure.ai.projects.models import MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions

        try:
            existing = self.stores.get(self.name)
            logger.info("Memory store '%s' already exists", self.name)
            return existing
        except Exception:  # noqa: BLE001 - ResourceNotFound and friends
            pass

        definition = MemoryStoreDefaultDefinition(
            chat_model=os.getenv("MEMORY_STORE_CHAT_MODEL_DEPLOYMENT_NAME")
            or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1"),
            embedding_model=os.getenv("MEMORY_STORE_EMBEDDING_MODEL_DEPLOYMENT_NAME")
            or os.getenv("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large"),
            options=MemoryStoreDefaultOptions(
                chat_summary_enabled=True,
                user_profile_enabled=True,
                default_ttl_seconds=ttl_days * 24 * 60 * 60,
                user_profile_details=USER_PROFILE_DETAILS,
            ),
        )
        return self.stores.create(
            name=self.name,
            definition=definition,
            description=description or "Per-customer memory for Zava's DeliverySupport agent",
        )

    # -- read / write ------------------------------------------------------
    def recall(self, query: str, *, scope: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        """Return memories relevant to ``query`` for ``scope`` (semantic search)."""
        result = self.stores.search_memories(
            self.name,
            scope=scope or default_scope(),
            items=query,
        )
        memories = getattr(result, "memories", None) or getattr(result, "results", None) or []
        return [_memory_dict(item) for item in list(memories)[:limit]]

    def remember(self, items: list[dict[str, Any]], *, scope: str | None = None) -> Any:
        """Hand a finished turn to Foundry so it can extract durable memories.

        The write is *debounced* by ``update_delay``: Foundry waits for the conversation to
        go quiet before consolidating, so a chatty turn does not produce noisy memories.
        """
        return self.stores.begin_update_memories(
            self.name,
            scope=scope or default_scope(),
            items=items,
            update_delay=update_delay(),
        )

    def list_items(self, *, scope: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List everything currently held for a scope (used by the dashboard)."""
        pages = self.stores.list_memories(self.name, scope=scope or default_scope(), limit=limit)
        return [_memory_dict(item) for item in pages]

    def clear_scope(self, *, scope: str | None = None) -> Any:
        """Forget everything for one customer — the demo reset button."""
        return self.stores.delete_scope(self.name, scope=scope or default_scope())


def _memory_dict(item: Any) -> dict[str, Any]:
    """Normalise a memory item / search hit into a plain dict for JSON transport.

    ``list_memories`` returns ``MemoryItem`` directly, while ``search_memories`` returns
    ``MemorySearchItem`` objects that wrap the record in a ``memory_item`` field — both
    shapes (and raw dicts, from the REST surface) are flattened here.
    """
    data: dict[str, Any] = dict(item) if isinstance(item, dict) else {}
    if not data:
        for attr in (
            "id",
            "memory_id",
            "content",
            "kind",
            "scope",
            "score",
            "created_at",
            "updated_at",
            "expires_at",
        ):
            value = getattr(item, attr, None)
            if value is not None:
                data[attr] = value

    inner = data.get("memory_item") or getattr(item, "memory_item", None)
    if inner is not None:
        merged = _memory_dict(inner)
        score = data.get("score") or getattr(item, "score", None)
        if score is not None:
            merged["score"] = score
        return merged

    kind = data.get("kind")
    return {
        "id": str(data.get("memory_id") or data.get("id") or ""),
        "content": str(data.get("content") or ""),
        "kind": str(getattr(kind, "value", kind) or "memory"),
        "score": data.get("score"),
        "updated_at": _epoch(data.get("updated_at") or data.get("created_at")),
    }


def _epoch(value: Any) -> int | None:
    """Normalise a timestamp (datetime or epoch int) to an int for JSON transport."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    timestamp = getattr(value, "timestamp", None)
    return int(timestamp()) if callable(timestamp) else None


_KIND_LABEL = {
    "user_profile": "Profile",
    "chat_summary": "Past conversation",
    "procedural": "Learned habit",
}


def memory_line(item: dict[str, Any]) -> str:
    """One readable line for a memory item (procedural memories arrive as JSON)."""
    content = (item.get("content") or "").strip()
    if item.get("kind") == "procedural" and content.startswith("{"):
        try:
            parsed = json.loads(content)
            content = str(parsed.get("instruction") or content)
        except (json.JSONDecodeError, ValueError):
            pass
    return content


def format_recall(memories: list[dict[str, Any]]) -> str:
    """Render recalled memories as an instruction block for the model."""
    lines = []
    for item in memories:
        text = memory_line(item)
        if text:
            lines.append(f"- ({_KIND_LABEL.get(item.get('kind', ''), 'Memory')}) {text}")
    if not lines:
        return ""
    return (
        "KNOWN CUSTOMER CONTEXT (recalled from Zava's long-term memory — treat as already "
        "confirmed, use it proactively, never ask the customer to repeat it, and never "
        "invent additions):\n" + "\n".join(lines)
    )


class FoundryMemoryProvider(ContextProvider):
    """MAF ``ContextProvider`` that gives DeliverySupport durable, per-customer memory.

    ``before_run`` recalls relevant memories and injects them as extra instructions;
    ``after_run`` hands the finished turn back to Foundry for extraction. Both steps are
    best-effort: a memory outage degrades personalisation, it never breaks a reply.
    """

    def __init__(self, memory: ZavaMemory | None = None, *, scope: str | None = None) -> None:
        super().__init__(source_id="foundry-memory")
        self.memory = memory or ZavaMemory()
        self.scope = scope or default_scope()
        self.last_recall: list[dict[str, Any]] = []

    async def before_run(self, *, agent: Any, session: Any, context: Any, state: dict[str, Any]) -> None:
        query = _latest_user_text(context.input_messages)
        if not query:
            return
        try:
            memories = await asyncio.to_thread(self.memory.recall, query, scope=self.scope)
        except Exception as exc:  # noqa: BLE001 - memory must never break a reply
            logger.warning("Memory recall failed: %s", exc)
            return
        self.last_recall = memories
        context.metadata["memory_recall"] = memories
        block = format_recall(memories)
        if block:
            context.instructions.append(block)
            print(f"[memory] recalled {len(memories)} item(s) for scope={self.scope}", flush=True)

    async def after_run(self, *, agent: Any, session: Any, context: Any, state: dict[str, Any]) -> None:
        user_text = _latest_user_text(context.input_messages)
        answer = ""
        response = context.response
        if response is not None:
            answer = getattr(response, "text", "") or ""
        if not user_text or not answer:
            return
        items = [
            {"type": "message", "role": "user", "content": user_text},
            {"type": "message", "role": "assistant", "content": answer},
        ]
        try:
            await asyncio.to_thread(self.memory.remember, items, scope=self.scope)
            print(f"[memory] queued update for scope={self.scope}", flush=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory update failed: %s", exc)


def _latest_user_text(messages: Any) -> str:
    for message in reversed(list(messages or [])):
        role = getattr(message, "role", None)
        role_value = str(getattr(role, "value", role) or "").lower()
        text = getattr(message, "text", None) or ""
        if text and role_value in ("user", ""):
            return text
    return ""


def build_memory_provider(scope: str | None = None) -> ContextProvider | None:
    """Return a configured provider, or ``None`` when memory is disabled/unavailable."""
    if not memory_enabled():
        logger.info("Foundry Memory disabled via DELIVERY_MEMORY_ENABLED")
        return None
    try:
        return FoundryMemoryProvider(scope=scope)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Foundry Memory disabled: %s", exc)
        return None
