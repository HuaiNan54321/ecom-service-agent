"""Multi-Agent 编排器：协调 Router 和子 Agent 完成用户请求。

流程：Router 分类意图 → 选择子 Agent → ReAct 执行 → 结构化提取 → 持久化。
"""

from typing import Optional

from openai import OpenAI

from app.agent.storage import delete_session, load_session, save_session
from app.agent.summarizer import summarize
from app.config.settings import settings
from app.multi_agent.agents import AGENT_CONFIGS, SubAgent
from app.multi_agent.router import Router
from app.schemas.response import CustomerServiceResponse
from app.tools.manager import ToolManager


class MultiAgentOrchestrator:
    """多 Agent 编排器，对外接口与 EcomAgent 一致。"""

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
        self.max_react_steps = settings.max_react_steps

        self.router = Router(self.client, self.model)

        self.agents: dict[str, SubAgent] = {}
        for key, cfg in AGENT_CONFIGS.items():
            tm = ToolManager(
                use_mcp=settings.mcp_enabled,
                mcp_server_url=settings.mcp_server_url,
                allowed_tools=cfg["tools"],
            )
            self.agents[key] = SubAgent(
                name=cfg["name"],
                system_prompt=cfg["prompt"],
                tool_manager=tm,
                client=self.client,
                model=self.model,
                temperature=self.temperature,
            )

        self.raw_messages: list[dict] = []
        self.summary: Optional[str] = None

        loaded = load_session(self.session_path)
        if loaded:
            self.summary = loaded["summary"]
            self.raw_messages = loaded["messages"]

    @property
    def history_size(self) -> int:
        return len(self.raw_messages)

    def chat(self, user_input: str) -> CustomerServiceResponse:
        """路由 → 子 Agent 执行 → 结构化提取 → 返回结果。"""
        self.raw_messages.append({"role": "user", "content": user_input})

        agent_key = self.router.route(user_input, self.raw_messages)
        agent = self.agents[agent_key]
        print(f"\n🔀 [路由] → {agent.name}")

        messages = self._build_messages(agent)
        final_text, new_messages = agent.handle(
            messages, max_steps=self.max_react_steps,
        )
        self.raw_messages.extend(new_messages)

        result = self._extract_structured_response(final_text)
        self.raw_messages.append(
            {"role": "assistant", "content": result.model_dump_json(ensure_ascii=False)}
        )

        if len(self.raw_messages) > self.history_threshold:
            self._compress_history()

        save_session(self.session_path, self.raw_messages, self.summary)
        return result

    def reset(self):
        self.raw_messages = []
        self.summary = None
        delete_session(self.session_path)

    def save(self) -> None:
        save_session(self.session_path, self.raw_messages, self.summary)

    def close(self):
        for agent in self.agents.values():
            agent.tool_manager.close()

    def _build_messages(self, agent: SubAgent) -> list[dict]:
        """用子 Agent 的 system prompt 构建消息列表。"""
        messages: list[dict] = [
            {"role": "system", "content": agent.system_prompt}
        ]
        if self.summary:
            messages.append({
                "role": "system",
                "content": f"以下是此前对话的摘要，用于延续上下文记忆：\n{self.summary}",
            })
        messages.extend(self.raw_messages)
        return messages

    def _extract_structured_response(self, text: str) -> CustomerServiceResponse:
        response = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "基于以下客服回复内容，提取结构化信息。"
                        "reply 字段直接使用原文，不要修改或缩减。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            response_format=CustomerServiceResponse,
        )
        return response.choices[0].message.parsed

    def _compress_history(self) -> None:
        keep = self.history_keep_recent
        split = len(self.raw_messages) - keep
        while split > 0 and self.raw_messages[split].get("role") in ("tool",):
            split -= 1
        if split <= 0:
            return
        old_messages = self.raw_messages[:split]
        recent = self.raw_messages[split:]

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
