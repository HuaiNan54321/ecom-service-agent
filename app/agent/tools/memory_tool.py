"""记忆查询工具：让 Agent 在 ReAct 循环中主动查询用户记忆。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.memory.manager import MemoryManager

_memory_manager: MemoryManager | None = None


def set_memory_manager(manager: MemoryManager) -> None:
    """由 Agent 初始化时调用，注入 MemoryManager 引用。"""
    global _memory_manager
    _memory_manager = manager


def recall_user_memory(query: str = "") -> dict:
    """查询当前用户的记忆信息（长期记忆和短期记忆）。"""
    if _memory_manager is None or not _memory_manager.memory_enabled:
        return {"success": False, "error": "记忆系统未启用"}

    result: dict = {
        "success": True,
        "short_term_facts": _memory_manager.stm.facts,
        "long_term_facts": [
            {"content": f.content, "category": f.category}
            for f in _memory_manager.ltm.facts
        ],
    }

    if _memory_manager.ltm.interaction_summaries:
        result["recent_interactions"] = [
            s["summary"] for s in _memory_manager.ltm.interaction_summaries[-3:]
        ]

    return result
