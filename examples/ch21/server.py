"""本地单用户、只读 MCP 服务；不会联网，也不会操作真实订单。"""

from mcp.server import MCPServer
from typing import Any
from examples.common import Sandbox


mcp = MCPServer("教学订单查询")
box = Sandbox()
USER_ID = "U1001"


@mcp.tool(structured_output=True)
def query_order(order_id: str) -> dict[str, Any]:
    """查询当前教学用户的订单；身份由服务绑定，不由模型提供。"""
    return box.query_order(USER_ID, order_id)


@mcp.resource("policy://refund")
def refund_policy() -> str:
    """提供虚构退款政策文本；读取资料不产生退款动作。"""
    return box.snapshot()["policies"][0]["text"]


@mcp.prompt()
def explain_order(order_id: str) -> str:
    """返回可复用说明模板；模板本身不会调用模型。"""
    return f"先查询订单 {order_id}，仅根据查询结果说明状态。"


if __name__ == "__main__":
    mcp.run(transport="stdio")
