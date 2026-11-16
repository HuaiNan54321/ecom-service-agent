"""用本地 HTTP 替身走完模型 SDK、真实客服工具和评测命令，不向供应商发请求。"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.config.settings import settings
from app.evaluation.dataset import EvalCase
from app.evaluation.evaluator import Evaluator, run_comparison
from app.evaluation.trace import RunTrace
from app.scripts.run_eval import main


class LiveComparisonTest(unittest.TestCase):
    def test_missing_answer_is_a_failed_attempt_on_both_sides(self):
        class EmptySandbox:
            def run(self, case):
                return RunTrace(case.id, case.turns, elapsed_ms=1)

        evaluator = Evaluator(EmptySandbox(), None, "local", use_judge=False)
        case = EvalCase("hello", "问候", ["你好"], expected_requires_human=False)
        result = run_comparison([case], evaluator, evaluator)
        for side in ("baseline", "candidate"):
            summary = result[side]["summary"]
            self.assertEqual((summary["passed"], summary["total"], summary["errors"]), (0, 1, 1))
        with self.assertRaises(ValueError):
            run_comparison([EvalCase("empty", "没有验收条件", ["你好"])], evaluator, evaluator)

    def test_same_case_first_attempt_and_incomplete_usage(self):
        requests = []

        def serve(transport, request):
            """基线收到查询后表示不知情，有工具的一侧实际查询模拟订单。"""
            self.assertEqual(request.url.host, "bench.invalid")
            body = json.loads(request.content)
            requests.append(body)
            msg = {"role": "assistant", "content": "查到了 Nike 商品，金额为 899 元。"}
            finish = "stop"
            if body.get("tools") and body["messages"][-1]["role"] == "user":
                msg = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "query-1", "type": "function", "function": {
                        "name": "query_order", "arguments": json.dumps({"order_id": "ORD-20240115-001"})}}]}
                finish = "tool_calls"
            if body.get("response_format"):
                queried = "Nike" in body["messages"][-1]["content"]
                msg["content"] = json.dumps({"intent": "order_query", "confidence": 1.0,
                    "reply": "Nike 商品，899 元" if queried else "我查不到订单记录。",
                    "requires_human": False, "follow_up_question": None})
            data = {"id": "local", "object": "chat.completion", "created": 1, "model": body["model"],
                    "choices": [{"index": 0, "finish_reason": finish, "message": msg}]}
            if not body.get("response_format") or "Nike" in body["messages"][-1]["content"]:
                data["usage"] = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
            return httpx.Response(200, json=data, request=request)

        with tempfile.TemporaryDirectory() as work:
            dataset, output = Path(work) / "cases.json", Path(work) / "report.json"
            case = {"id": "order", "description": "查一笔订单", "turns": ["帮我查订单 ORD-20240115-001"],
                    "expected_intent": "order_query", "expected_keywords": ["Nike", "899"],
                    "expected_requires_human": False, "expected_tools": ["query_order"], "min_tool_calls": 1}
            dataset.write_text(json.dumps({"cases": [case]}))
            argv = ["run_eval", "--compare-bare", "--mode", "single", "--no-judge",
                    "--dataset", str(dataset), "--output", str(output)]
            with patch.object(settings, "openai_base_url", "http://bench.invalid/v1"), \
                 patch.object(settings, "openai_api_key", "test"), \
                 patch.object(settings, "model_name", "local-model"), \
                 patch.object(httpx.HTTPTransport, "handle_request", serve), \
                 patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                main()
            report = json.loads(output.read_text())
        baseline, candidate = (report[k]["summary"] for k in ("baseline", "candidate"))
        self.assertEqual((baseline["total"], candidate["total"]), (1, 1))
        self.assertEqual((baseline["errors"], candidate["errors"]), (0, 0))
        self.assertEqual((baseline["pass_at_1"], candidate["pass_at_1"]), (0, 1))
        self.assertEqual((baseline["avg_tool_calls"], candidate["avg_tool_calls"]), (0, 1))
        self.assertIsNone(baseline["avg_tokens_per_case"])
        self.assertEqual(candidate["avg_tokens_per_case"], 36)
        self.assertEqual(report["rule_case_counts"]["keyword_coverage"], 1)
        self.assertEqual(report["paired"]["improved"], ["order"])
        self.assertEqual({r["model"] for r in requests}, {"local-model"})
