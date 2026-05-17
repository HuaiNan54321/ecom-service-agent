"""MCP 工具 schema → OpenAI function calling 格式转换。"""


def mcp_tools_to_openai(mcp_tools: list) -> list[dict]:
    """将 MCP Tool 列表转换为 OpenAI function calling 所需的 tools 格式。

    MCP Tool 的 inputSchema 本身就是 JSON Schema，和 OpenAI parameters 字段格式一致，
    只需要调整外层信封结构。
    """
    result = []
    for tool in mcp_tools:
        result.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            },
        })
    return result
