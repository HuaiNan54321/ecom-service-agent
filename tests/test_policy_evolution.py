"""从客服评测命令到普通客服会话，验证策略的生成、验证、采纳和回滚。"""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.agent.chat import EcomAgent
from app.agent.strategies.policy import current_policy, policy_scope, save_validated
from app.config.settings import settings
from app.scripts import evolve, run_eval


RULE_TEXT = "先用可用工具核对业务事实"
DEV_NOTE = "此条工单的备注只用于本次对话"


class PolicyEvolutionTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.requests = []
        config = patch.multiple(
            settings, openai_base_url="http://policy.invalid/v1", openai_api_key="test",
            model_name="policy-test", policy_db_path=str(self.work / "policy.sqlite3"),
            session_path=str(self.work / "session.json"), memory_enabled=False,
            skills_enabled=False, mcp_enabled=False, eval_pass_threshold=0.6,
        )
        config.start()
        self.addCleanup(config.stop)
        transport = patch.object(httpx.HTTPTransport, "handle_request",
                                 lambda transport, request: self.answer(request))
        transport.start()
        self.addCleanup(transport.stop)

    def answer(self, request):
        """模型在看到候选规则时请求查单，回复中的金额只能来自实际工具回包。"""
        self.assertEqual(request.url.host, "policy.invalid")
        body = json.loads(request.content)
        self.requests.append(body)
        messages = body["messages"]
        last = messages[-1]
        message = {"role": "assistant", "content": "还没有查到订单金额。"}
        finish = "stop"
        if body.get("response_format"):
            intent = "greeting" if last["content"].startswith("你好") else "order_query"
            message["content"] = json.dumps({
                "intent": intent, "confidence": 1, "reply": last["content"],
                "requires_human": False, "follow_up_question": None,
            })
        elif last["role"] == "tool":
            order = json.loads(last["content"])["order"]
            message["content"] = f"查到了，订单总额是 {order['total']:g} 元。"
        elif last["content"] == "你好":
            message["content"] = "你好，请问有什么需要帮忙的？"
        elif RULE_TEXT in messages[0]["content"]:
            order_id = re.search(r"ORD-\d{8}-\d{3}", last["content"]).group()
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "query-1", "type": "function", "function": {
                    "name": "query_order", "arguments": json.dumps({"order_id": order_id}),
                },
            }]}
            finish = "tool_calls"
        data = {"id": "local", "object": "chat.completion", "created": 1, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": finish, "message": message}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
        return httpx.Response(200, json=data, request=request)

    def dataset(self, case_id, question, user, amount):
        path = self.work / f"{case_id}.json"
        case = {"id": case_id, "description": "核对订单金额", "turns": [question], "user_id": user,
                "expected_keywords": [amount], "expected_tools": ["query_order"]}
        path.write_text(json.dumps({"cases": [case]}, ensure_ascii=False), encoding="utf-8")
        return path

    def cli(self, module, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", [module.__name__, *map(str, args)]), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            module.main()
        return output.getvalue()

    def failure_report(self):
        dev = self.dataset("dev", f"查订单 ORD-20240115-001 的金额。{DEV_NOTE}", "小明", "899")
        report = self.work / "failure.json"
        self.cli(run_eval, "--mode", "single", "--no-judge", "--dataset", dev, "--output", report)
        failure = json.loads(report.read_text())["cases"][0]
        self.assertIsNone(failure["error"])
        self.assertFalse(failure["passed"])
        self.assertEqual(failure["process"]["tool_accuracy"], 0)
        return dev, report

    def test_development_failure_to_live_chat_and_rollback(self):
        dev, report = self.failure_report()
        holdout = self.dataset("held", "订单 ORD-20240122-005 一共花了多少？", "阿杰", "4697")
        checked = self.work / "validated.json"
        proposal = json.loads(self.cli(evolve, "propose", "--mode", "single", "--report", report))
        self.assertEqual(proposal["rule"], "lookup_first")
        self.assertEqual(proposal["evidence"]["lookup_first"], ["dev"])

        agent = EcomAgent(user_id="阿杰")
        self.addCleanup(agent.client.close)
        self.addCleanup(agent.close)
        original = agent._build_messages()[0]["content"]
        self.assertNotIn(RULE_TEXT, original)

        rewritten = self.dataset("rewritten", "麻烦核实 ORD-20240115-001 实付几元", "小明", "899")
        for duplicate in (dev, rewritten):
            with self.subTest(duplicate=duplicate.stem):
                count = len(self.requests)
                with self.assertRaises(SystemExit) as rejected:
                    self.cli(evolve, "validate", "--mode", "single", "--report", report,
                             "--holdout", duplicate, "--output", checked)
                self.assertEqual(rejected.exception.code, 2)
                self.assertEqual(len(self.requests), count)
                self.assertFalse(checked.exists())

        self.requests.clear()
        self.cli(evolve, "validate", "--mode", "single", "--report", report,
                 "--holdout", holdout, "--output", checked)
        validation = json.loads(checked.read_text())
        self.assertTrue(validation["eligible"])
        self.assertEqual(validation["paired"]["improved"], ["held"])
        self.assertEqual(validation["paired"]["regressed"], [])
        before = validation["baseline"]["cases"][0]["trace"]
        after = validation["candidate"]["cases"][0]["trace"]
        self.assertEqual(before["tool_calls"], [])
        self.assertEqual(after["tool_calls"], ["query_order"])
        self.assertIn("4697", after["reply"])
        # 仅策略改变，两边实际收到的工具定义、模型和用户问题相同。
        first_turns = [r for r in self.requests if r.get("tools") and r["messages"][-1]["role"] == "user"]
        self.assertEqual(len(first_turns), 2)
        for key in ("tools", "model", "temperature"):
            self.assertEqual(first_turns[0][key], first_turns[1][key])
        self.assertEqual(first_turns[0]["messages"][1:], first_turns[1]["messages"][1:])
        self.assertEqual(agent._build_messages()[0]["content"], original)

        version = validation["version"]
        self.assertIsInstance(version, int)
        with self.assertRaises(SystemExit) as rejected:
            self.cli(evolve, "adopt", version, "--mode", "multi")
        self.assertEqual(rejected.exception.code, 2)
        self.cli(evolve, "adopt", version, "--mode", "single")
        active = agent._build_messages()[0]["content"]
        self.assertIn(RULE_TEXT, active)
        self.assertNotIn(DEV_NOTE, active)
        with contextlib.redirect_stdout(io.StringIO()):
            actual = agent.chat("请核查订单 ORD-20240122-005 的总额")
        self.assertIn("4697", actual.reply)
        self.cli(evolve, "rollback", "--mode", "single")
        self.assertEqual(agent._build_messages()[0]["content"], original)

    def test_reports_must_identify_the_current_customer_service(self):
        _, path = self.failure_report()
        report = json.loads(path.read_text())
        protocol = report["protocol"]
        self.assertEqual(protocol["producer"], "app.scripts.run_eval")
        self.assertEqual(protocol["policy_scope"], policy_scope("single"))
        self.assertEqual(protocol["policy_version"], 0)
        self.assertEqual(protocol["dimension_threshold"], settings.eval_pass_threshold)
        for key, value in (("producer", None), ("producer", "example"), ("policy_version", 9),
                           ("policy_scope", "another-model")):
            with self.subTest(key=key, value=value):
                changed = dict(protocol)
                if value is None:
                    del changed[key]
                else:
                    changed[key] = value
                path.write_text(json.dumps({**report, "protocol": changed}), encoding="utf-8")
                with self.assertRaises(SystemExit) as rejected:
                    self.cli(evolve, "propose", "--mode", "single", "--report", path)
                self.assertEqual(rejected.exception.code, 2)

    def test_repeated_rollback_preserves_previous_release(self):
        # 模拟两次先后发布。第二次回滚命令若被重发，第一版仍应在用。
        evidence = {"development_cases": ["dev"], "paired": {"improved": ["held"], "regressed": []},
                    "errors": 0}
        first = save_validated("single", 0, ("lookup_first",), evidence)
        self.cli(evolve, "adopt", first, "--mode", "single")
        second = save_validated("single", first, ("lookup_first", "ground_reply"), evidence)
        self.cli(evolve, "adopt", second, "--mode", "single")
        with self.assertRaises(SystemExit) as stale:
            self.cli(evolve, "rollback", first, "--mode", "single")
        self.assertEqual(stale.exception.code, 2)
        self.assertEqual(current_policy("single")[0], second)
        self.cli(evolve, "rollback", second, "--mode", "single")
        self.assertEqual(current_policy("single")[0], first)
        with self.assertRaises(SystemExit) as replay:
            self.cli(evolve, "rollback", second, "--mode", "single")
        self.assertEqual(replay.exception.code, 2)
        self.assertEqual(current_policy("single")[0], first)

    def test_a_passing_tool_score_does_not_trigger_a_tool_rule(self):
        row = {"case_id": "over_budget", "passed": False, "trace": {"num_llm_calls": 2},
               "process": {"tool_accuracy": 0.8, "token_pass": False}, "result": {}}
        selected, evidence = evolve.propose([row], (), 0.6)
        self.assertIsNone(selected)
        self.assertEqual(evidence, {})

    def test_no_improvement_leaves_no_version_to_adopt(self):
        _, report = self.failure_report()
        holdout = self.work / "greeting.json"
        case = {"id": "greeting", "description": "简单问候", "turns": ["你好"],
                "expected_intent": "greeting", "expected_keywords": ["你好"], "user_id": "阿杰"}
        holdout.write_text(json.dumps({"cases": [case]}, ensure_ascii=False), encoding="utf-8")
        checked = self.work / "no_change.json"
        self.cli(evolve, "validate", "--mode", "single", "--report", report,
                 "--holdout", holdout, "--output", checked)
        validation = json.loads(checked.read_text())
        for side in ("baseline", "candidate"):
            self.assertEqual(validation[side]["summary"]["passed"], 1)
        self.assertFalse(validation["eligible"])
        self.assertIsNone(validation["version"])
        with self.assertRaises(SystemExit) as rejected:
            self.cli(evolve, "adopt", 1, "--mode", "single")
        self.assertEqual(rejected.exception.code, 2)
