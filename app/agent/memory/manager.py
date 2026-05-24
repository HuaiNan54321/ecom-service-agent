"""记忆管理器：统一管理短期记忆和长期记忆。

EcomAgent 和 MultiAgentOrchestrator 通过此管理器与记忆系统交互。
"""

from __future__ import annotations

from typing import Optional

from openai import OpenAI

from app.agent.memory.long_term import LongTermMemory
from app.agent.memory.short_term import ShortTermMemory


class MemoryManager:
    """记忆管理器：统一管理短期记忆和长期记忆。"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        user_id: str = "default",
        memory_dir: str = "app/sessions/memory",
        memory_enabled: bool = True,
        max_ltm_facts: int = 50,
    ):
        self.client = client
        self.model = model
        self.memory_enabled = memory_enabled

        self.stm = ShortTermMemory()
        self.ltm = LongTermMemory(
            user_id=user_id,
            memory_dir=memory_dir,
            max_facts=max_ltm_facts,
        )

        if self.memory_enabled:
            self.ltm.load()

    def update_short_term(self, recent_messages: list[dict]) -> None:
        """每轮对话后更新短期记忆。"""
        if not self.memory_enabled:
            return
        self.stm.update(self.client, self.model, recent_messages)

    def build_memory_prompt_sections(self) -> list[dict]:
        """生成所有记忆相关的 system prompt 消息列表。"""
        if not self.memory_enabled:
            return []

        sections = []
        ltm_section = self.ltm.build_prompt_section()
        if ltm_section:
            sections.append({"role": "system", "content": ltm_section})
        stm_section = self.stm.build_prompt_section()
        if stm_section:
            sections.append({"role": "system", "content": stm_section})
        return sections

    def consolidate_to_long_term(
        self, messages: list[dict], summary: Optional[str],
    ) -> None:
        """会话结束时，将本次对话的关键事实巩固到长期记忆。"""
        if not self.memory_enabled:
            return
        self.ltm.extract_and_save(
            self.client, self.model, messages, summary,
        )

    def reset_short_term(self) -> None:
        """重置短期记忆（会话内重置时调用）。"""
        self.stm.reset()

    def reset_all(self) -> None:
        """重置所有记忆（短期+长期）。"""
        self.stm.reset()
        self.ltm.reset()

    def stm_to_dict(self) -> dict:
        return self.stm.to_dict()

    def restore_stm(self, data: dict) -> None:
        self.stm = ShortTermMemory.from_dict(data)
