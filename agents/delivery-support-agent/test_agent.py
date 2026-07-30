import asyncio
from collections.abc import Awaitable
from typing import Any

from src.agent import create_delivery_support_agent, load_environment


def _text(result: Any) -> str:
    return str(getattr(result, "text", result))


async def main() -> None:
    load_environment()
    agent = create_delivery_support_agent()
    session = agent.create_session()

    prompts = [
        "Hey, what's the status of order 23518?",
        "When will it arrive?",
        "What about order 23590?",
    ]

    for index, prompt in enumerate(prompts, start=1):
        print(f"\nTurn {index} user: {prompt}")
        response = agent.run(prompt, session=session)
        if isinstance(response, Awaitable):
            response = await response
        print(f"Turn {index} DeliverySupport: {_text(response)}")


if __name__ == "__main__":
    asyncio.run(main())
