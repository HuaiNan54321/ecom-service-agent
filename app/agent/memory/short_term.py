"""短期记忆：会话内事实提取与管理。

从当前对话中提取用户关键信息（身份、偏好、情绪等），
注入 system prompt 增强 Agent 的上下文感知能力。
"""

from __future__ import annotations

from openai import OpenAI

from app.agent.memory.extraction import extract_short_term_facts


class ShortTermMemory:
    """会话内短期记忆：从对话中提取结构化事实，增强上下文感知。"""

    def __init__(self):
        self.facts: list[str] = []

    def update(self, client: OpenAI, model: str, recent_messages: list[dict]) -> None:
        """从最近的对话消息中提取/更新事实。"""
        self.facts = extract_short_term_facts(
            client, model, recent_messages, self.facts,
        )

    def build_prompt_section(self) -> str | None:
        """生成注入 system prompt 的短期记忆片段。"""
        if not self.facts:
            return None
        facts_text = "\n".join(f"- {f}" for f in self.facts)
        return f"以下是本次对话中提取的用户关键信息（短期记忆）：\n{facts_text}"

    def reset(self) -> None:
        self.facts = []

    def to_dict(self) -> dict:
        return {"facts": self.facts}

    @classmethod
    def from_dict(cls, data: dict) -> ShortTermMemory:
        stm = cls()
        stm.facts = data.get("facts", [])
        return stm
