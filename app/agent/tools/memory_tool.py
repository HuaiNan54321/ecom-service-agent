"""记忆查询工具：让 Agent 在 ReAct 循环中主动查询用户记忆。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.memory.manager import MemoryManager

def recall_user_memory(manager: MemoryManager | None, /, query: str = "") -> dict:
    """只读取宿主绑定的会话记忆，模型参数不能指定顾客或记忆目录。"""
    if manager is None or not manager.memory_enabled:
        return {"success": False, "error": "当前会话未启用用户记忆"}

    result: dict = {
        "success": True,
        "short_term_facts": manager.stm.facts,
        "long_term_facts": [
            {"content": f.content, "category": f.category}
            for f in manager.ltm.facts
        ],
    }

    if manager.ltm.interaction_summaries:
        result["recent_interactions"] = [
            s["summary"] for s in manager.ltm.interaction_summaries[-3:]
        ]

    return result
