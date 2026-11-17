"""ToolManager：统一管理本地工具和 MCP 工具。

当 MCP 启用时，通过 Streamable HTTP 连接 MCP Server 获取工具；
当 MCP 未启用或连接失败时，退回本地工具。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

from app.agent.tools.memory_tool import recall_user_memory
from app.agent.tools.refund import RefundLedger
from app.agent.tools.registry import TOOL_DEFINITIONS as LOCAL_TOOL_DEFINITIONS
from app.agent.tools.registry import execute_tool as local_execute_tool
from app.agent.tools.skill_tool import load_skill

if TYPE_CHECKING:
    from app.agent.memory.manager import MemoryManager
    from app.agent.skills.loader import SkillManager


class ToolManager:
    """聚合本地工具和 MCP 工具，提供统一的工具定义和调度接口。"""

    def __init__(
        self,
        use_mcp: bool = False,
        mcp_server_url: str = "",
        allowed_tools: Optional[set] = None,
        refund_ledger: Optional[RefundLedger] = None,
    ):
        self.refund_ledger = refund_ledger
        self._memory_manager: MemoryManager | None = None
        self._skill_manager: SkillManager | None = None
        self._mcp_client = None
        self._tool_source: dict[str, str] = {}
        self._tool_defs: list[dict] = []

        if use_mcp and mcp_server_url:
            self._init_mcp(mcp_server_url)
        else:
            self._init_local()

        # 记忆、技能和订单都依赖宿主提供的会话配置，MCP 同名工具不能接管这些操作。
        managed = {"recall_user_memory": "memory", "load_skill": "skill"}
        if refund_ledger is not None:
            for name in ("apply_refund", "query_order", "query_logistics", "list_user_orders"):
                managed[name] = "ledger"
        definitions = {d["function"]["name"]: d for d in LOCAL_TOOL_DEFINITIONS}
        for i, item in enumerate(self._tool_defs):
            name = item["function"]["name"]
            if name in managed:
                self._tool_source[name] = managed[name]
                self._tool_defs[i] = definitions[name]

        if allowed_tools is not None:
            self._filter_tools(allowed_tools)

    def _init_local(self):
        """只加载本地工具。"""
        self._tool_defs = list(LOCAL_TOOL_DEFINITIONS)
        for td in self._tool_defs:
            self._tool_source[td["function"]["name"]] = "local"

    def _init_mcp(self, server_url: str):
        """连接 MCP Server 加载工具；失败时降级到本地工具。"""
        from app.mcp_client import MCPClient

        try:
            self._mcp_client = MCPClient(server_url)
            mcp_tools = self._mcp_client.connect()
            print(f"🔗 [MCP] 已连接 {server_url}，发现 {len(mcp_tools)} 个工具")

            mcp_names = set()
            for td in mcp_tools:
                name = td["function"]["name"]
                mcp_names.add(name)
                self._tool_source[name] = "mcp"
            self._tool_defs = list(mcp_tools)

            for td in LOCAL_TOOL_DEFINITIONS:
                name = td["function"]["name"]
                if name not in mcp_names:
                    self._tool_defs.append(td)
                    self._tool_source[name] = "local"

        except Exception as e:
            print(f"⚠️  [MCP] 连接失败 ({e})，降级使用本地工具")
            if self._mcp_client:
                self._mcp_client.close()
                self._mcp_client = None
            self._init_local()

    def _filter_tools(self, allowed: set):
        """只保留白名单中的工具，用于子 Agent 工具隔离。"""
        self._tool_defs = [
            d for d in self._tool_defs
            if d["function"]["name"] in allowed
        ]
        self._tool_source = {
            k: v for k, v in self._tool_source.items()
            if k in allowed
        }

    @property
    def tool_definitions(self) -> list[dict]:
        return self._tool_defs

    def bind_memory_manager(self, manager: MemoryManager | None) -> None:
        """把已有的会话记忆接入本实例获准使用的工具。"""
        self._memory_manager = manager

    def bind_skill_manager(self, manager: SkillManager | None) -> None:
        """绑定本客服启用的技能目录，保留各专员的工具权限。"""
        self._skill_manager = manager

    def execute_tool(self, name: str, arguments: dict) -> str:
        """根据工具来源分发调用。"""
        source = self._tool_source.get(name)

        if source in ("memory", "skill"):
            try:
                if source == "memory":
                    result = recall_user_memory(self._memory_manager, **arguments)
                else:
                    result = load_skill(self._skill_manager, **arguments)
            except TypeError:
                result = {"success": False, "error": f"{name} 的参数与工具说明不符。"}
            return json.dumps(result, ensure_ascii=False)

        if source == "ledger":
            handler = self.refund_ledger.prepare if name == "apply_refund" else getattr(self.refund_ledger, name)
            try:
                result = handler(**arguments)
            except TypeError:
                result = {"success": False, "status": "rejected", "error": "工具参数格式不正确，请检查订单号和必填项。"}
            return json.dumps(result, ensure_ascii=False)

        if source == "mcp" and self._mcp_client:
            return self._mcp_client.call_tool(name, arguments)

        if source == "local":
            return local_execute_tool(name, arguments)

        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    def close(self):
        """清理 MCP 连接。"""
        if self._mcp_client:
            self._mcp_client.close()
            self._mcp_client = None
