"""技能加载工具：让 Agent 在 ReAct 循环中按需加载 Skill 指令。

由 Agent 初始化时注入 SkillManager 引用，
Agent 通过 load_skill 工具调用获取技能的完整指令。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.skills.loader import SkillManager

def load_skill(manager: SkillManager | None, /, skill_name: str) -> dict:
    """从宿主为当前客服启用的技能目录读取完整指令。"""
    if manager is None:
        return {"success": False, "error": "技能系统未启用"}
    return manager.load_skill(skill_name)
