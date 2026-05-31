"""技能加载工具：让 Agent 在 ReAct 循环中按需加载 Skill 指令。

模式与 memory_tool.py 一致：由 Agent 初始化时注入 SkillManager 引用，
Agent 通过 load_skill 工具调用获取技能的完整指令。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.skills.loader import SkillManager

_skill_manager: SkillManager | None = None


def set_skill_manager(manager: SkillManager) -> None:
    """由 Agent 初始化时调用，注入 SkillManager 引用。"""
    global _skill_manager
    _skill_manager = manager


def load_skill(skill_name: str) -> dict:
    """加载指定技能的完整指令。Agent 调用后按指令处理用户问题。"""
    if _skill_manager is None:
        return {"success": False, "error": "技能系统未启用"}
    return _skill_manager.load_skill(skill_name)
