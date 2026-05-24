"""长期记忆：跨会话持久化用户知识。

将用户在多次会话中表现出的偏好、身份、行为模式等提取并持久化为 JSON，
在新会话启动时加载并注入 prompt，让 Agent 具备"记住老客户"的能力。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import OpenAI

from app.agent.memory.extraction import extract_long_term_facts


@dataclass
class MemoryFact:
    """一条长期记忆事实。"""
    content: str
    category: str  # identity / preference / behavior / issue / other
    created_at: str
    source_session: str = ""


class LongTermMemory:
    """跨会话长期记忆：持久化用户知识。"""

    def __init__(
        self,
        user_id: str = "default",
        memory_dir: str = "app/sessions/memory",
        max_facts: int = 50,
    ):
        self.user_id = user_id
        self.memory_dir = Path(memory_dir)
        self.max_facts = max_facts
        self.facts: list[MemoryFact] = []
        self.interaction_summaries: list[dict] = []

    @property
    def memory_path(self) -> Path:
        return self.memory_dir / f"{self.user_id}.json"

    def load(self) -> None:
        """从 JSON 文件加载用户的长期记忆。"""
        if not self.memory_path.exists():
            return
        try:
            with self.memory_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        for item in data.get("facts", []):
            self.facts.append(MemoryFact(
                content=item["content"],
                category=item.get("category", "other"),
                created_at=item.get("created_at", ""),
                source_session=item.get("source_session", ""),
            ))
        self.interaction_summaries = data.get("interaction_summaries", [])

    def save(self) -> None:
        """持久化到 JSON 文件（原子写入）。"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "version": 1,
            "user_id": self.user_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "facts": [asdict(f) for f in self.facts],
            "interaction_summaries": self.interaction_summaries,
        }

        tmp_path = self.memory_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.memory_path)

    def add_facts(self, new_facts: list[MemoryFact]) -> None:
        """添加新事实，自动去重并裁剪到 max_facts。"""
        existing_contents = {f.content.lower() for f in self.facts}
        for fact in new_facts:
            if fact.content.lower() not in existing_contents:
                self.facts.append(fact)
                existing_contents.add(fact.content.lower())

        if len(self.facts) > self.max_facts:
            self.facts = self.facts[-self.max_facts:]

    def add_interaction_summary(self, summary: str) -> None:
        self.interaction_summaries.append({
            "summary": summary,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

    def extract_and_save(
        self,
        client: OpenAI,
        model: str,
        messages: list[dict],
        summary: Optional[str],
    ) -> None:
        """从会话消息中提取长期记忆事实并保存。"""
        if not messages and not summary:
            return

        new_facts, interaction_summary = extract_long_term_facts(
            client, model, messages, summary, self.facts,
        )

        if new_facts:
            self.add_facts(new_facts)
        if interaction_summary:
            self.add_interaction_summary(interaction_summary)

        self.save()

    def build_prompt_section(self) -> str | None:
        """生成注入 system prompt 的长期记忆片段。"""
        if not self.facts and not self.interaction_summaries:
            return None

        parts = []
        if self.facts:
            facts_text = "\n".join(
                f"- [{f.category}] {f.content}" for f in self.facts
            )
            parts.append(f"该用户的历史记忆（来自过往会话）：\n{facts_text}")

        if self.interaction_summaries:
            recent = self.interaction_summaries[-3:]
            summaries_text = "\n".join(f"- {s['summary']}" for s in recent)
            parts.append(f"最近的交互记录：\n{summaries_text}")

        return "\n\n".join(parts)

    def reset(self) -> None:
        """清空该用户的长期记忆（文件也删除）。"""
        self.facts = []
        self.interaction_summaries = []
        if self.memory_path.exists():
            self.memory_path.unlink()
