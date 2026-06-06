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

import tempfile
import time
from pathlib import Path

from app.config.settings import settings
from app.evaluation.dataset import EvalCase
from app.evaluation.trace import LLMCallRecord, RunTrace, ToolObservation


class Sandbox:
    """Agent 评估沙箱：构建隔离环境、插桩采集、跑用例产出 RunTrace。"""

    def __init__(self, mode: str = "single", tmp_root: str | None = None):
        self.mode = mode  # "single" / "multi"
        self.tmp_root = Path(tmp_root) if tmp_root else Path(tempfile.mkdtemp(prefix="eval_sandbox_"))
        self.tmp_root.mkdir(parents=True, exist_ok=True)

    def session_path_for(self, case_id: str) -> str:
        return str(self.tmp_root / f"{case_id}.json")

    def _build_agent(self, session_path: str):
        """在隔离配置下构建被测 Agent。"""
        # 关闭记忆读写与 MCP，保证可复现（agent.__init__ 直接读全局 settings）
        settings.memory_enabled = False
        settings.mcp_enabled = False

        if self.mode == "multi":
            from app.multi_agent.orchestrator import MultiAgentOrchestrator
            return MultiAgentOrchestrator(session_path=session_path)
        from app.agent.chat import EcomAgent
        return EcomAgent(session_path=session_path)

    def run(self, case: EvalCase) -> RunTrace:
        """跑一条用例，返回采集到的运行轨迹。"""
        trace = RunTrace(case_id=case.id, turns=list(case.turns))
        session_path = self.session_path_for(case.id)

        agent = None
        patches: list[tuple] = []  # (obj, attr, original) 供还原
        try:
            agent = self._build_agent(session_path)
            self._instrument(agent, trace, patches)

            result = None
            for turn in case.turns:
                result = agent.chat(turn)
            trace.final_response = result

        except Exception as e:  # noqa: BLE001 —— 单条用例异常不应中断整轮评估
            trace.error = f"{type(e).__name__}: {e}"
        finally:
            for obj, attr, original in patches:
                setattr(obj, attr, original)
            if agent is not None:
                self._close_tool_managers(agent)
            # 注意：刻意不调用 agent.close()，避免长期记忆巩固写入

        return trace

    # ---------- 插桩 ----------
    def _instrument(self, agent, trace: RunTrace, patches: list[tuple]) -> None:
        """给共享 client、各 ToolManager、（多 Agent）Router 打补丁。"""
        # 1) LLM client：create + beta.parse
        completions = agent.client.chat.completions
        patches.append((completions, "create", completions.create))
        completions.create = self._wrap_create(completions.create, trace)

        beta_completions = agent.client.beta.chat.completions
        patches.append((beta_completions, "parse", beta_completions.parse))
        beta_completions.parse = self._wrap_parse(beta_completions.parse, trace)

        # 2) 工具执行
        for tm in self._tool_managers(agent):
            patches.append((tm, "execute_tool", tm.execute_tool))
            tm.execute_tool = self._wrap_execute_tool(tm.execute_tool, trace)

        # 3) 多 Agent 路由
        if self.mode == "multi" and hasattr(agent, "router"):
            patches.append((agent.router, "route", agent.router.route))
            agent.router.route = self._wrap_route(agent.router.route, trace)

    def _wrap_create(self, original, trace: RunTrace):
        def wrapper(*args, **kwargs):
            start = time.time()
            response = original(*args, **kwargs)
            latency_ms = (time.time() - start) * 1000
            self._record_llm_call(
                trace, response, latency_ms,
                purpose=self._guess_purpose(kwargs),
            )
            return response
        return wrapper

    def _wrap_parse(self, original, trace: RunTrace):
        def wrapper(*args, **kwargs):
            start = time.time()
            response = original(*args, **kwargs)
            latency_ms = (time.time() - start) * 1000
            self._record_llm_call(trace, response, latency_ms, purpose="extract")
            return response
        return wrapper

    def _wrap_execute_tool(self, original, trace: RunTrace):
        def wrapper(name: str, arguments: dict) -> str:
            result_str = original(name, arguments)
            trace.tool_observations.append(
                ToolObservation(name=name, arguments=dict(arguments), result=result_str)
            )
            return result_str
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
    def _record_llm_call(trace: RunTrace, response, latency_ms: float, purpose: str) -> None:
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or 0

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
