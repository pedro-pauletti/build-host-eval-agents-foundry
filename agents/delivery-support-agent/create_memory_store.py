"""Create the Foundry **memory store** used by the DeliverySupport agent.

Run once (idempotent):

    python agents/delivery-support-agent/create_memory_store.py

The store is where Foundry keeps the durable, per-customer facts extracted from delivery
conversations. It needs two deployments: a **chat model** (extracts and consolidates
memories from a transcript) and an **embedding model** (semantic retrieval).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

for candidate in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
    env_file = candidate / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
        break

from src.memory import ZavaMemory, default_scope  # noqa: E402


def main() -> None:
    memory = ZavaMemory()
    store = memory.ensure_store(ttl_days=int(os.getenv("DELIVERY_MEMORY_TTL_DAYS", "30")))
    print(f"Memory store ready: {getattr(store, 'name', memory.name)}")
    definition = getattr(store, "definition", None)
    if definition is not None:
        print(f"  chat model      : {getattr(definition, 'chat_model', '?')}")
        print(f"  embedding model : {getattr(definition, 'embedding_model', '?')}")
    print(f"  default scope   : {default_scope()}")

    items = memory.list_items()
    print(f"  memories in scope: {len(items)}")
    for item in items:
        print(f"    - [{item['kind']}] {item['content'][:110]}")


if __name__ == "__main__":
    main()
