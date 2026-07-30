from __future__ import annotations

import asyncio
import json

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = "http://localhost:8080/mcp"


def print_json(title: str, value: object) -> None:
    print(f"\n{title}")
    print(json.dumps(value, indent=2, default=str))


async def main() -> None:
    async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools/list:", ", ".join(tool.name for tool in tools.tools))
            order = await session.call_tool("lookup_order", {"order_id": "23518"})
            alerts = await session.call_tool("get_inventory_alerts", {"severity": "critical"})
            stock = await session.call_tool("get_product_stock", {"sku": "ZCPTM-SS-S-B0"})
            print_json("lookup_order(23518):", order.model_dump())
            print_json("get_inventory_alerts(severity=critical):", alerts.model_dump())
            print_json("get_product_stock(ZCPTM-SS-S-B0):", stock.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
