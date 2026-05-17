"""端到端测试：验证第 4 期 MCP (Model Context Protocol) 集成。

前提条件：需先在另一个终端启动 MCP Server
  python mcp_server/server.py

测试场景：
1. MCP Client 连接与工具发现
2. Schema 转换正确性（MCP → OpenAI 格式）
3. 通过 MCP 调用单个工具
4. ToolManager 统一调度（MCP 模式）
5. ToolManager 降级（本地模式）
6. 完整 Agent + MCP 端到端（订单查询）
7. 完整 Agent + MCP 端到端（商品搜索）

用法：
  1. 启动 MCP Server: python mcp_server/server.py
  2. 运行测试: python scripts/test_mcp.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_client import MCPClient  # noqa: E402
from tools.manager import ToolManager  # noqa: E402
from agent.chat import EcomAgent  # noqa: E402
from schemas.response import CustomerServiceResponse, IntentType  # noqa: E402

MCP_URL = "http://127.0.0.1:9123/mcp"
TEST_SESSION = str(ROOT / "sessions" / "test_mcp_session.json")

EXPECTED_TOOLS = {"query_order", "query_product", "query_logistics", "apply_refund"}


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def _assert_structured(resp: CustomerServiceResponse, label: str):
    if not isinstance(resp.intent, IntentType):
        _fail(f"{label}：intent 不是 IntentType 类型")
    if not (0.0 <= resp.confidence <= 1.0):
        _fail(f"{label}：confidence 超出 [0,1] 范围 → {resp.confidence}")
    if not resp.reply:
        _fail(f"{label}：reply 为空")
    _ok(f"{label}：结构化输出完整 (intent={resp.intent.value}, confidence={resp.confidence:.0%})")


def _clean():
    Path(TEST_SESSION).unlink(missing_ok=True)


# ---------- 测试 1：MCP Client 连接与工具发现 ----------
def test_mcp_connection():
    print("\n[1/7] MCP Client 连接与工具发现")
    client = MCPClient(MCP_URL)
    try:
        tools = client.connect()
        if len(tools) != 4:
            _fail(f"期望 4 个工具，实际发现 {len(tools)} 个")
        tool_names = {t["function"]["name"] for t in tools}
        if tool_names != EXPECTED_TOOLS:
            _fail(f"工具名称不匹配: {tool_names}")
        _ok(f"成功连接 MCP Server，发现 {len(tools)} 个工具: {tool_names}")
    finally:
        client.close()


# ---------- 测试 2：Schema 转换正确性 ----------
def test_schema_conversion():
    print("\n[2/7] Schema 转换正确性（MCP → OpenAI 格式）")
    client = MCPClient(MCP_URL)
    try:
        tools = client.connect()
        for tool in tools:
            if tool.get("type") != "function":
                _fail(f"工具类型错误: {tool}")
            func = tool.get("function", {})
            if not func.get("name"):
                _fail("缺少 function.name")
            if not func.get("description"):
                _fail(f"工具 {func['name']} 缺少 description")
            params = func.get("parameters", {})
            if params.get("type") != "object":
                _fail(f"工具 {func['name']} parameters.type 不是 object")
            if not params.get("properties"):
                _fail(f"工具 {func['name']} 缺少 parameters.properties")
        _ok("所有工具 schema 符合 OpenAI function calling 格式")
    finally:
        client.close()


# ---------- 测试 3：通过 MCP 调用单个工具 ----------
def test_mcp_tool_call():
    print("\n[3/7] 通过 MCP 调用单个工具")
    client = MCPClient(MCP_URL)
    try:
        client.connect()

        import json
        result = client.call_tool("query_order", {"order_id": "ORD-20240115-001"})
        data = json.loads(result)
        if not data.get("success"):
            _fail(f"查询订单失败: {data}")
        order = data.get("order", {})
        if order.get("status") != "shipped":
            _fail(f"订单状态不正确: {order.get('status')}")
        _ok(f"query_order 调用成功，订单状态: {order['status']}")

        result = client.call_tool("query_product", {"keyword": "耳机"})
        data = json.loads(result)
        if not data.get("success"):
            _fail(f"查询商品失败: {data}")
        _ok(f"query_product 调用成功，找到 {len(data['products'])} 个商品")
    finally:
        client.close()


# ---------- 测试 4：ToolManager 统一调度（MCP 模式）----------
def test_tool_manager_mcp():
    print("\n[4/7] ToolManager 统一调度（MCP 模式）")
    manager = ToolManager(use_mcp=True, mcp_server_url=MCP_URL)
    try:
        defs = manager.tool_definitions
        if len(defs) != 4:
            _fail(f"期望 4 个工具定义，实际 {len(defs)}")
        _ok(f"ToolManager 加载了 {len(defs)} 个工具")

        import json
        result = manager.execute_tool("query_logistics", {"order_id": "ORD-20240115-001"})
        data = json.loads(result)
        if not data.get("success"):
            _fail(f"物流查询失败: {data}")
        _ok(f"通过 ToolManager 调用 MCP 工具成功")
    finally:
        manager.close()


# ---------- 测试 5：ToolManager 降级（本地模式）----------
def test_tool_manager_local():
    print("\n[5/7] ToolManager 降级（本地模式）")
    manager = ToolManager(use_mcp=False)
    try:
        defs = manager.tool_definitions
        if len(defs) != 4:
            _fail(f"期望 4 个工具定义，实际 {len(defs)}")
        _ok("本地模式加载 4 个工具")

        import json
        result = manager.execute_tool("query_order", {"order_id": "ORD-20240115-001"})
        data = json.loads(result)
        if not data.get("success"):
            _fail(f"本地工具调用失败: {data}")
        _ok("本地模式工具调用正常")
    finally:
        manager.close()


# ---------- 测试 6：完整 Agent + MCP（订单查询）----------
def test_agent_mcp_order():
    print("\n[6/7] 完整 Agent + MCP 端到端（订单查询）")
    _clean()
    agent = EcomAgent(session_path=TEST_SESSION)
    agent.tool_manager.close()
    agent.tool_manager = ToolManager(use_mcp=True, mcp_server_url=MCP_URL)
    agent.history_threshold = 30

    try:
        resp = agent.chat("帮我查一下订单 ORD-20240115-001 的状态")
        _assert_structured(resp, "MCP订单查询")

        keywords = ["发货", "shipped", "Nike", "运动鞋", "899", "顺丰"]
        found = any(kw in resp.reply for kw in keywords)
        if found:
            _ok("回复中包含订单相关信息")
        else:
            print(f"  ⚠️  回复中未找到预期关键词（可能模型表述不同）")
        print(f"     回复：{resp.reply[:120]}")
    finally:
        agent.close()


# ---------- 测试 7：完整 Agent + MCP（商品搜索）----------
def test_agent_mcp_product():
    print("\n[7/7] 完整 Agent + MCP 端到端（商品搜索）")
    _clean()
    agent = EcomAgent(session_path=TEST_SESSION)
    agent.tool_manager.close()
    agent.tool_manager = ToolManager(use_mcp=True, mcp_server_url=MCP_URL)
    agent.history_threshold = 30

    try:
        resp = agent.chat("你们有什么耳机卖？")
        _assert_structured(resp, "MCP商品搜索")

        keywords = ["AirPods", "1799", "降噪", "耳机"]
        found = any(kw in resp.reply for kw in keywords)
        if found:
            _ok("回复中包含商品信息")
        else:
            print(f"  ⚠️  回复中未找到预期商品关键词")
        print(f"     回复：{resp.reply[:120]}")
    finally:
        agent.close()


def main():
    print("=" * 60)
    print("  第 4 期 MCP 集成 · 端到端测试")
    print("  确保 MCP Server 已启动: python mcp_server/server.py")
    print("=" * 60)

    try:
        test_mcp_connection()
        test_schema_conversion()
        test_mcp_tool_call()
        test_tool_manager_mcp()
        test_tool_manager_local()
        test_agent_mcp_order()
        test_agent_mcp_product()
    finally:
        _clean()

    print("\n" + "=" * 60)
    print("  🎉 全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
