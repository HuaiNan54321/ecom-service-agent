from openai import OpenAI

from config.settings import settings
from prompts.customer_service import SYSTEM_PROMPT
from schemas.response import CustomerServiceResponse


class EcomAgent:
    """电商客服 Agent —— 第一期：基于纯 Prompt + 结构化输出"""

    def __init__(self):
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.model_name
        self.temperature = settings.temperature
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def chat(self, user_input: str) -> CustomerServiceResponse:
        """处理用户输入，返回结构化的客服回复"""
        self.messages.append({"role": "user", "content": user_input})

        response = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=self.messages,
            temperature=self.temperature,
            response_format=CustomerServiceResponse,
        )

        result = response.choices[0].message

        # 将 assistant 的原始回复存入对话历史，保持上下文连贯
        self.messages.append({"role": "assistant", "content": result.content})

        return result.parsed

    def reset(self):
        """重置对话历史"""
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
