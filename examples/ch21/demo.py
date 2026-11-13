"""启动真实 MCP 子进程并发现、调用工具；不需要模型 API。"""

import asyncio
import json
import sys
from importlib.metadata import version
from pathlib import Path

from mcp import Client, StdioServerParameters


async def main() -> None:
    """在有界超时内连接本地服务，核对成功、越权与协议错误。"""
    root = Path(__file__).resolve().parents[2]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "examples.ch21.server"],
        cwd=root,
    )
    async with asyncio.timeout(20):
        async with Client(params, read_timeout_seconds=5) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == ["query_order"]
            good = await client.call_tool("query_order", {"order_id": "A1001"})
            denied = await client.call_tool("query_order", {"order_id": "A1003"})
            bad = await client.call_tool("missing_tool", {})
            policy = await client.read_resource("policy://refund")
            prompt = await client.get_prompt("explain_order", {"order_id": "A1001"})
            assert not good.is_error and good.structured_content["success"]
            assert good.structured_content["order"]["status"] == "shipped"
            assert denied.structured_content["error"]["code"] == "ORDER_NOT_ACCESSIBLE"
            assert bad.is_error
            assert policy.contents and prompt.messages
            print(json.dumps({
                "性质": "真实本地 MCP 调用，虚构业务数据，没有模型调用",
                "SDK版本": version("mcp"),
                "协议版本": client.protocol_version,
                "发现工具": [tool.name for tool in tools.tools],
                "本用户订单": good.structured_content["order"]["status"],
                "其他用户订单": denied.structured_content["error"]["code"],
                "未知工具失败": bad.is_error,
                "资源与模板读取": "通过",
            }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
