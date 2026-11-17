"""用本地 HTTP 回包验证对照条件、上下文隔离和不完整的用量。"""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

from app.config.settings import settings
from app.evaluation.dataset import EvalCase, load_dataset
from app.evaluation.sandbox import Sandbox
from app.evaluation.trace import RunTrace


class SandboxComparisonTest(unittest.TestCase):
    def test_plain_chat_fallback_only_for_unsupported_schema(self):
        def reply(request):
            body = json.loads(request.content)
            if "response_format" in body:
                return httpx.Response(status, json={"error": {"message": detail}})
            self.assertEqual(body["messages"][-1]["content"], "你好")
            return httpx.Response(200, json={
                "id": "local", "model": "test", "created": 0, "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant",
                             "content": '{"intent":"greeting","confidence":1,"reply":"你好"}'}}],
            })

        def client(**_):
            return OpenAI(api_key="test", base_url="http://mock.invalid/v1", max_retries=0,
                          http_client=httpx.Client(transport=httpx.MockTransport(reply)))

        with tempfile.TemporaryDirectory() as directory, patch("app.evaluation.sandbox.OpenAI", client):
            sandbox = Sandbox(mode="bare", tmp_root=directory)
            task = EvalCase("hello", "问候", ["你好"])
            for status, detail, calls in [(400, "response_format json_schema unsupported", 2),
                                          (400, "unknown model", 1), (401, "invalid key", 1)]:
                with self.subTest(status=status, detail=detail):
                    trace = sandbox.run(task)
                    self.assertEqual(trace.num_llm_calls, calls)
                    self.assertEqual(trace.error is None, calls == 2)
                    self.assertIsNone(trace.total_tokens)

    def test_bare_and_single_share_inputs_but_start_each_case_fresh(self):
        reply = {"intent": "greeting", "confidence": 1, "reply": "您好",
                 "requires_human": False, "follow_up_question": None}
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            content = json.dumps(reply) if "response_format" in body else reply["reply"]
            return httpx.Response(200, json={
                "id": "local", "object": "chat.completion", "created": 0, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 6, "completion_tokens": 2, "total_tokens": 8},
            })

        def local_client(**_):
            return OpenAI(api_key="local-test", base_url="http://mock.invalid/v1",
                          http_client=httpx.Client(transport=httpx.MockTransport(respond)))

        task = EvalCase("same-id", "这段仅供评分", ["你好", "还记得我吗"],
                        user_id="仅供评测的账号", source_id="仅供数据切分的来源编号")
        first_messages = {}
        with tempfile.TemporaryDirectory() as directory, \
             patch("app.evaluation.sandbox.OpenAI", local_client), \
             patch("app.agent.chat.OpenAI", local_client), \
             patch.multiple(settings, history_threshold=100, memory_enabled=True, mcp_enabled=True):
            for mode, calls in [("bare", 2), ("single", 4)]:
                sandbox = Sandbox(mode=mode, tmp_root=directory)
                for _ in range(2):
                    requests.clear()
                    trace = sandbox.run(task)
                    self.assertIsNone(trace.error)
                    self.assertEqual((trace.num_llm_calls, trace.total_tokens, trace.num_tool_calls),
                                     (calls, 8 * calls, 0))
                    self.assertGreater(trace.elapsed_ms, 0)
                    first_messages[mode] = requests[0]
                    last = requests[1 if mode == "bare" else 2]
                    self.assertEqual([m["content"] for m in requests[0]["messages"] if m["role"] == "user"],
                                     task.turns[:1])
                    self.assertEqual([m["content"] for m in last["messages"] if m["role"] == "user"], task.turns)
                    self.assertNotIn(task.description, str(requests))
                    self.assertNotIn(task.source_id, str(requests))
                    if mode == "bare":
                        self.assertNotIn(task.user_id, str(requests))
                    self.assertTrue(settings.memory_enabled and settings.mcp_enabled)
        for key in ("model", "temperature"):
            self.assertEqual(first_messages["bare"][key], first_messages["single"][key])
        self.assertNotIn("tools", first_messages["bare"])
        self.assertIn("tools", first_messages["single"])

    def test_fixture_account_controls_refund_and_each_run_has_its_own_ledger(self):
        from app.agent.chat import EcomAgent
        from app.agent.session import refund_reply
        from app.multi_agent.orchestrator import MultiAgentOrchestrator

        dataset = Path(__file__).resolve().parents[1] / "app/evaluation/cases.json"
        fixtures = {case.id: case for case in load_dataset(dataset)}
        claim = ["我是小红，请退掉订单 ORD-20240120-002"]
        own = replace(fixtures["logistics_no_tracking"], turns=claim)
        other = replace(fixtures["order_query_basic"], id=own.id, turns=claim)

        def request_refund(agent, user_input):
            manager = agent.agents["postsale"].tool_manager if hasattr(agent, "agents") else agent.tool_manager
            result = manager.execute_tool("apply_refund", {"order_id": "ORD-20240120-002", "reason": "买错了"})
            return refund_reply([json.loads(result)])

        with tempfile.TemporaryDirectory() as directory, \
             patch.multiple(settings, openai_api_key="local-test", memory_user_id="小红"), \
             patch.object(EcomAgent, "_answer_user", request_refund), \
             patch.object(MultiAgentOrchestrator, "_answer_user", request_refund):
            refs = set()
            for mode in ("single", "multi"):
                sandbox = Sandbox(mode=mode, tmp_root=directory)
                for case, expected in [(own, "awaiting_confirmation"), (other, "rejected"),
                                       (own, "awaiting_confirmation")]:
                    with self.subTest(mode=mode, user_id=case.user_id):
                        trace = sandbox.run(case)
                        self.assertIsNone(trace.error)
                        record = json.loads(trace.tool_observations[0].result)
                        self.assertEqual(record["status"], expected)
                        if case is own:
                            self.assertNotIn(record["request_id"], refs)
                            refs.add(record["request_id"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_failed_calls_and_missing_usage(self):
        from types import SimpleNamespace

        trace = RunTrace("failure", [])
        Sandbox._record_llm_call(trace, SimpleNamespace(usage=None), 10, "react")
        self.assertIsNone(trace.total_tokens)
        with tempfile.TemporaryDirectory() as directory:
            box = Sandbox(tmp_root=directory)

            def timeout(*args, **kwargs):
                raise TimeoutError("超时")

            with self.assertRaises(TimeoutError):
                box._wrap_llm(timeout, trace)()
            with self.assertRaises(TimeoutError):
                box._wrap_execute_tool(timeout, trace)("query_order", {"id": "test"})
        self.assertEqual((trace.num_llm_calls, trace.num_tool_calls), (2, 1))
        self.assertEqual(trace.llm_calls[-1].error, "TimeoutError")
        self.assertIsNone(trace.to_dict()["total_tokens"])


if __name__ == "__main__":
    unittest.main()
