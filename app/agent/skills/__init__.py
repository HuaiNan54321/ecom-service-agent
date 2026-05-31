"""Agent 技能模块（第8期）。

基于 Anthropic Agent Skills 开放标准（agentskills.io/specification），
每个 Skill 是一个 SKILL.md 文件（YAML frontmatter + Markdown 指令），
用于教会 Agent 如何处理特定场景的标准化流程。

启动时只加载 name + description 注入 system prompt（发现），
Agent 按需调用 load_skill 工具加载完整指令到上下文（激活），
然后使用 ReAct 循环和已有工具按指令流程处理（执行）。
"""

from app.agent.skills.loader import SkillManager, SkillMeta

__all__ = ["SkillManager", "SkillMeta"]
