"""意图路由器：分析用户消息，决定分发给哪个子 Agent。"""

from typing import List, Optional

from openai import OpenAI

from app.prompts.agents import ROUTER_PROMPT

VALID_AGENTS = {"presale", "postsale", "complaint"}
DEFAULT_AGENT = "postsale"


class Router:
    """使用 LLM 对用户意图分类，路由到对应的子 Agent。"""

    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def route(self, user_input: str, history: Optional[List[dict]] = None) -> str:
        """返回子 Agent 标识: "presale" / "postsale" / "complaint"。"""
        recent_context = ""
        if history:
            recent = [
                m for m in history[-4:]
                if m.get("role") in ("user", "assistant")
            ]
            if recent:
                lines = []
                for m in recent:
                    role = "用户" if m["role"] == "user" else "客服"
                    content = m.get("content", "")
                    if content and len(content) < 200:
                        lines.append(f"{role}: {content}")
                if lines:
                    recent_context = "\n最近对话：\n" + "\n".join(lines) + "\n"

        prompt = ROUTER_PROMPT.format(user_input=user_input)
        if recent_context:
            prompt = recent_context + "\n" + prompt

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )

        raw = (response.choices[0].message.content or "").strip().lower()

        for agent_key in VALID_AGENTS:
            if agent_key in raw:
                return agent_key

        return DEFAULT_AGENT
