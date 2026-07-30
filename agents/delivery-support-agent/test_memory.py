"""Cross-session recall test for **Foundry Memory** on the DeliverySupport agent.

Runs two *independent* agent instances against an isolated scope:

1. **Session 1** — the customer states who they are and how they want deliveries handled.
   ``FoundryMemoryProvider.after_run`` hands the turn to Foundry, which extracts durable
   memories asynchronously (debounced by ``DELIVERY_MEMORY_UPDATE_DELAY``).
2. **Session 2** — a *brand new* agent object with **no conversation history** asks a
   follow-up. If memory works, ``before_run`` recalls the stored facts and the answer
   uses the customer's name and preferences.

Usage::

    python test_memory.py            # run, then clean the scope
    python test_memory.py --keep     # leave the memories in place for inspection
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent import create_delivery_support_agent  # noqa: E402
from src.memory import ZavaMemory  # noqa: E402

SCOPE = "zava-memory-test"
SESSION_1 = (
    "Hi, I'm Priya Raman. Please always leave my Zava parcels with the building "
    "concierge and text me instead of emailing. Can you check order 23518?"
)
SESSION_2 = "Hi again — how should my next delivery be handled?"
POLL_SECONDS, POLL_TRIES = 5, 24


async def main(keep: bool) -> int:
    memory = ZavaMemory()
    memory.ensure_store()
    memory.clear_scope(scope=SCOPE)

    print("=== session 1 — the customer shares preferences ===")
    answer = (await create_delivery_support_agent(memory_scope=SCOPE).run(SESSION_1)).text
    print(answer[:700])

    print("\nwaiting for Foundry to consolidate memories...")
    items: list[dict] = []
    for _ in range(POLL_TRIES):
        time.sleep(POLL_SECONDS)
        items = memory.list_items(scope=SCOPE)
        if items:
            break
    print(f"memories stored: {len(items)}")
    for item in items:
        print(f"  - [{item['kind']}] {item['content'][:150]}")

    print("\n=== session 2 — fresh agent, zero conversation history ===")
    recalled = (await create_delivery_support_agent(memory_scope=SCOPE).run(SESSION_2)).text
    print(recalled[:700])

    lowered = recalled.lower()
    hits = [word for word in ("priya", "concierge", "text") if word in lowered]
    ok = bool(items) and len(hits) >= 2
    print(f"\n{'PASS' if ok else 'FAIL'} — recalled signals: {hits or 'none'}")

    if not keep:
        memory.clear_scope(scope=SCOPE)
        print(f"cleaned scope '{SCOPE}'")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--keep" in sys.argv)))
