from typing import Optional

from openai import OpenAI

from agent.storage import delete_session, load_session, save_session
from agent.summarizer import summarize
from config.settings import settings
from prompts.customer_service import SYSTEM_PROMPT
from schemas.response import CustomerServiceResponse


class EcomAgent:
    """电商客服 Agent —— 第二期：多轮对话管理（summary 压缩 + JSON 持久化）"""

    def __init__(self, session_path: Optional[str] = None):
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.model_name
        self.temperature = settings.temperature
        self.session_path = session_path or settings.session_path
        self.history_threshold = settings.history_threshold
        self.history_keep_recent = settings.history_keep_recent

        # 原始对话条目（user/assistant），也是落盘的内容
        self.raw_messages: list[dict] = []
        # 累积的摘要文本（超过阈值时触发压缩更新）
        self.summary: Optional[str] = None

        loaded = load_session(self.session_path)
        if loaded:
            self.summary = loaded["summary"]
            self.raw_messages = loaded["messages"]

    @property
    def history_size(self) -> int:
        """原始对话条数（不含 system / summary），供 CLI 打印恢复提示用"""
        return len(self.raw_messages)

    def chat(self, user_input: str) -> CustomerServiceResponse:
        """处理用户输入，返回结构化的客服回复"""
        self.raw_messages.append({"role": "user", "content": user_input})

        response = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=self._build_messages(),
            temperature=self.temperature,
            response_format=CustomerServiceResponse,
        )

        result = response.choices[0].message
        self.raw_messages.append(
            {"role": "assistant", "content": result.content}
        )

        if len(self.raw_messages) > self.history_threshold:
            self._compress_history()

        # 每轮落盘，进程挂了也能接上
        save_session(self.session_path, self.raw_messages, self.summary)

        return result.parsed

    def reset(self):
        """重置对话历史，并删除持久化文件"""
        self.raw_messages = []
        self.summary = None
        delete_session(self.session_path)

    def save(self) -> None:
        """显式保存（退出时兜底调用）"""
        save_session(self.session_path, self.raw_messages, self.summary)

    def _build_messages(self) -> list[dict]:
        """拼装发给 LLM 的完整消息列表：system prompt + (summary system) + 原始历史"""
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        if self.summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"以下是此前对话的摘要，用于延续上下文记忆：\n{self.summary}",
                }
            )
        messages.extend(self.raw_messages)
        return messages

    def _compress_history(self) -> None:
        """把最近 K 条以前的消息压缩成新的累积式 summary，截断 raw_messages"""
        keep = self.history_keep_recent
        old_messages = self.raw_messages[:-keep]
        recent = self.raw_messages[-keep:]

        new_summary = summarize(
            client=self.client,
            model=self.model,
            old_messages=old_messages,
            prev_summary=self.summary,
        )
        self.summary = new_summary
        self.raw_messages = recent
        print(
            f"\n💾 [已压缩 {len(old_messages)} 条老消息 → summary "
            f"({len(new_summary)} 字)]\n"
        )
