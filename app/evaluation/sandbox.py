"""评估沙箱：隔离、可复现地重跑测试集，并采集运行全过程（第9期）。

沙箱做三件事：
1. 隔离：每条用例独立的临时 session 文件；关闭记忆读写（否则 default.json 会注入
   prompt 污染评分）；关闭 MCP 只用本地 mock 工具（保证可复现，且让幻觉检测有确定
   的 ground truth）。
2. 插桩：单/多 Agent 都只共享一个 OpenAI client 实例，给它的
   chat.completions.create / beta.chat.completions.parse 打补丁，即可捕获整个会话
   所有 LLM 调用的 token、被请求的工具、延迟——无需改动 chat.py / orchestrator.py。
   工具返回值则通过包裹 ToolManager.execute_tool 采集。
3. 执行：顺序跑完用例的多轮输入，把过程与结果填进 RunTrace 返回。

关键：绝不调用 agent.close()（会触发长期记忆巩固的 LLM 写入，污染且烧钱）；
所有补丁在 finally 中还原。
"""

from __future__ import annotations

import json
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from openai import BadRequestError, OpenAI, UnprocessableEntityError

from app.config.settings import settings
from app.evaluation.dataset import EvalCase
from app.evaluation.trace import LLMCallRecord, RunTrace, ToolObservation
from app.schemas.response import CustomerServiceResponse


class _BareCustomerService:
    """同一模型直接按客服回复格式作答；每条用例从空的对话历史开始。"""

    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        self.history = [{
            "role": "system",
            "content": "你是并夕夕电商客服小夕。根据当前对话回答顾客。对话没有提供的订单、商品和政策事实，不能编造。",
        }]

    def chat(self, user_input: str) -> CustomerServiceResponse:
        self.history.append({"role": "user", "content": user_input})
        params = {"model": settings.model_name, "temperature": settings.temperature}
        try:
            response = self.client.beta.chat.completions.parse(
                **params, messages=self.history, response_format=CustomerServiceResponse,
            )
            answer = response.choices[0].message.parsed
        except (BadRequestError, UnprocessableEntityError) as exc:
            # 部分兼容接口只支持普通聊天，仅在明确拒绝结构化参数时切换格式。
            detail = str(exc).lower()
            if not any(key in detail for key in ("response_format", "json_schema", "json schema")):
                raise
            schema = json.dumps(CustomerServiceResponse.model_json_schema(), ensure_ascii=False)
            instruction = {"role": "system", "content": "仅返回符合以下结构的 JSON，不加代码围栏。\n" + schema}
            response = self.client.chat.completions.create(
                **params, messages=[self.history[0], instruction, *self.history[1:]],
            )
            answer = CustomerServiceResponse.model_validate_json(response.choices[0].message.content)
        if answer is None:
            raise ValueError("模型未返回结构化客服回复")
        self.history.append({"role": "assistant", "content": answer.reply})
        return answer


class Sandbox:
    """Agent 评估沙箱：构建隔离环境、插桩采集、跑用例产出 RunTrace。"""

    def __init__(self, mode: str = "single", tmp_root: str | None = None, *,
                 policy_override: tuple[str, ...] | None = None):
        if mode not in {"bare", "single", "multi"}:
            raise ValueError("沙箱模式只支持 bare、single 或 multi")
        self.mode = mode
        self.policy_override = policy_override
        self.tmp_root = Path(tmp_root) if tmp_root else Path(tempfile.mkdtemp(prefix="eval_sandbox_"))
        self.tmp_root.mkdir(parents=True, exist_ok=True)

    def session_path_for(self, case_id: str) -> str:
        return str(self.tmp_root / f"{case_id}.json")

    def _build_agent(self, session_path: str, user_id: str = "default"):
        """在隔离配置下构建被测 Agent。"""
        if self.mode == "bare":
            return _BareCustomerService()
        # 构造函数读取全局配置并存进实例，构造完成后立即恢复配置。
        with patch.multiple(settings, memory_enabled=False, mcp_enabled=False):
            if self.mode == "multi":
                from app.multi_agent.orchestrator import MultiAgentOrchestrator
                return MultiAgentOrchestrator(session_path=session_path, user_id=user_id)
            from app.agent.chat import EcomAgent
            return EcomAgent(session_path=session_path, user_id=user_id)

    def run(self, case: EvalCase) -> RunTrace:
        """跑一条用例，返回采集到的运行轨迹。"""
        trace = RunTrace(case_id=case.id, turns=list(case.turns))
        patches: list[tuple] = []  # (obj, attr, original) 供还原
        start = time.perf_counter()
        with ExitStack() as stack:
            try:
                # 复跑相同编号也建立全新会话，编号中的路径字符不会参与写盘。
                run_dir = stack.enter_context(tempfile.TemporaryDirectory(dir=self.tmp_root))
                agent = self._build_agent(str(Path(run_dir) / "session.json"), case.user_id)
                if self.policy_override is not None:
                    agent.policy_override = self.policy_override
                stack.callback(self._close_tool_managers, agent)
                stack.callback(agent.client.close)
                self._instrument(agent, trace, patches)
                for turn in case.turns:
                    trace.final_response = agent.chat(turn)
            except Exception as e:  # noqa: BLE001 —— 单条异常仍保留本次已发生的调用
                trace.error = f"{type(e).__name__}: {e}"
            finally:
                trace.elapsed_ms = (time.perf_counter() - start) * 1000
                for obj, attr, original in reversed(patches):
                    setattr(obj, attr, original)
        return trace

    # ---------- 插桩 ----------
    def _instrument(self, agent, trace: RunTrace, patches: list[tuple]) -> None:
        """给共享 client、各 ToolManager、（多 Agent）Router 打补丁。"""
        # 1) LLM client：create + beta.parse
        completions = agent.client.chat.completions
        patches.append((completions, "create", completions.create))
        completions.create = self._wrap_llm(
            completions.create, trace, purpose="bare" if self.mode == "bare" else None
        )

        beta_completions = agent.client.beta.chat.completions
        patches.append((beta_completions, "parse", beta_completions.parse))
        beta_completions.parse = self._wrap_llm(
            beta_completions.parse, trace, purpose="bare" if self.mode == "bare" else "extract"
        )

        # 2) 工具执行
        for tm in self._tool_managers(agent):
            patches.append((tm, "execute_tool", tm.execute_tool))
            tm.execute_tool = self._wrap_execute_tool(tm.execute_tool, trace)

        # 3) 多 Agent 路由
        if self.mode == "multi" and hasattr(agent, "router"):
            patches.append((agent.router, "route", agent.router.route))
            agent.router.route = self._wrap_route(agent.router.route, trace)

    def _wrap_llm(self, original, trace: RunTrace, purpose: str | None = None):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            response = None
            error = None
            try:
                response = original(*args, **kwargs)
                return response
            except Exception as exc:
                error = type(exc).__name__
                raise
            finally:
                self._record_llm_call(trace, response, (time.perf_counter() - start) * 1000,
                                      purpose or self._guess_purpose(kwargs), error)
        return wrapper

    def _wrap_execute_tool(self, original, trace: RunTrace):
        def wrapper(name: str, arguments: dict) -> str:
            observation = ToolObservation(name=name, arguments=dict(arguments), result="")
            trace.tool_observations.append(observation)
            try:
                observation.result = original(name, arguments)
                return observation.result
            except Exception as exc:
                observation.result = f"工具调用失败：{type(exc).__name__}"
                raise
        return wrapper

    def _wrap_route(self, original, trace: RunTrace):
        def wrapper(*args, **kwargs):
            agent_key = original(*args, **kwargs)
            trace.route = agent_key
            return agent_key
        return wrapper

    # ---------- 辅助 ----------
    @staticmethod
    def _guess_purpose(kwargs: dict) -> str:
        """启发式标注 LLM 调用用途，仅供报告可读，不作硬断言。"""
        if kwargs.get("max_tokens") == 10:
            return "router"
        if kwargs.get("tools"):
            return "react"
        return "react"

    @staticmethod
    def _record_llm_call(trace: RunTrace, response, latency_ms: float, purpose: str,
                         error: str | None = None) -> None:
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)

        tool_calls: list[dict] = []
        try:
            message = response.choices[0].message
            for tc in (getattr(message, "tool_calls", None) or []):
                tool_calls.append({
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })
        except (AttributeError, IndexError):
            pass

        model = getattr(response, "model", "") or ""
        trace.llm_calls.append(LLMCallRecord(
            purpose=purpose,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            error=error,
        ))

    def _tool_managers(self, agent) -> list:
        if self.mode == "multi" and hasattr(agent, "agents"):
            return [a.tool_manager for a in agent.agents.values()]
        if hasattr(agent, "tool_manager"):
            return [agent.tool_manager]
        return []

    def _close_tool_managers(self, agent) -> None:
        for tm in self._tool_managers(agent):
            try:
                tm.close()
            except Exception:  # noqa: BLE001
                pass
