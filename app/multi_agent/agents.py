"""子 Agent 定义：每个子 Agent 有专属的 system prompt 和工具子集。

SubAgent 封装了一个轻量级 ReAct 循环，由 Orchestrator 调度执行。
"""

import json

from openai import OpenAI

from app.prompts.agents import COMPLAINT_PROMPT, POSTSALE_PROMPT, PRESALE_PROMPT
from app.agent.tools.manager import ToolManager
from app.agent.session import refund_reply, run_requested_tool
from app.schemas.response import CustomerServiceResponse


AGENT_CONFIGS = {
    "presale": {
        "name": "小夕-售前",
        "prompt": PRESALE_PROMPT,
        "tools": {"query_product", "search_knowledge", "list_user_orders", "load_skill"},
    },
    "postsale": {
        "name": "小夕-售后",
        "prompt": POSTSALE_PROMPT,
        "tools": {
            "query_order", "query_logistics", "apply_refund",
            "list_user_orders", "search_knowledge", "load_skill",
        },
    },
    "complaint": {
        "name": "小夕-投诉",
        "prompt": COMPLAINT_PROMPT,
        "tools": {"query_order", "search_knowledge", "load_skill"},
    },
}


class SubAgent:
    """专业子 Agent：拥有独立的 prompt 和工具子集，执行 ReAct 循环。"""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tool_manager: ToolManager,
        client: OpenAI,
        model: str,
        temperature: float,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tool_manager = tool_manager
        self.client = client
        self.model = model
        self.temperature = temperature

    def handle(
        self, messages: list[dict], max_steps: int = 5,
    ) -> tuple[str | CustomerServiceResponse, list[dict]]:
        """执行 ReAct 循环，返回 (最终文本, 新增消息列表)。"""
        new_messages: list[dict] = []
        working = list(messages)

        for _ in range(max_steps):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=working,
                temperature=self.temperature,
                tools=self.tool_manager.tool_definitions,
            )
            assistant_msg = response.choices[0].message

            # 退款工具回合的文字可能是模型猜测的结果，终端只展示宿主核实后的状态。
            has_refund = any(tc.function.name == "apply_refund" for tc in assistant_msg.tool_calls or [])
            if assistant_msg.content and not has_refund:
                self._print_thought(assistant_msg.content)

            if not assistant_msg.tool_calls:
                content = assistant_msg.content or ""
                msg = {"role": "assistant", "content": content}
                new_messages.append(msg)
                return content, new_messages

            msg_dict: dict = {"role": "assistant", "content": None if has_refund else assistant_msg.content}
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
            new_messages.append(msg_dict)
            working.append(msg_dict)

            refund_records = []
            for tc in assistant_msg.tool_calls:
                func_name = tc.function.name
                result_str = run_requested_tool(self.tool_manager, tc, self._print_action)
                if func_name == "apply_refund":
                    refund_records.append(json.loads(result_str))
                self._print_observation(result_str)

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                }
                new_messages.append(tool_msg)
                working.append(tool_msg)

            if refund_records:
                return refund_reply(refund_records), new_messages

        response = self.client.chat.completions.create(
            model=self.model,
            messages=working,
            temperature=self.temperature,
        )
        content = response.choices[0].message.content or ""
        new_messages.append({"role": "assistant", "content": content})
        return content, new_messages

    def _print_thought(self, text: str) -> None:
        print(f"\n  💭 [{self.name}·思考] {text}")

    def _print_action(self, func_name: str, func_args: dict) -> None:
        args_str = ", ".join(f"{k}={v!r}" for k, v in func_args.items())
        print(f"  🔧 [{self.name}·调用工具] {func_name}({args_str})")

    def _print_observation(self, result: str) -> None:
        display = result if len(result) <= 300 else result[:300] + "..."
        print(f"  📋 [{self.name}·工具结果] {display}")
