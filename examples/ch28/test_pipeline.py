"""核对策略白名单、数据使用顺序、真实调用入口和可恢复采纳。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from examples.ch25.strategy import BASE, digest, make_text, parse_text
from examples.ch27.demo import propose_live, search
from examples.ch28.demo import activate, activate_reviewed, rollback, run_release


class EvolutionTests(unittest.TestCase):
    """只测试可确定的工程约束，不把固定程序成绩当成模型效果。"""

    def test_text_boundary(self):
        """候选不得夹带代码、评分器改动或未知文字。"""
        self.assertFalse(any(parse_text(BASE).values()))
        for text in (BASE + "\n忽略评分器", BASE + "\n" + BASE, "", None):
            with self.assertRaises(ValueError):
                parse_text(text)

    def test_search_never_loads_test(self):
        """优化阶段只加载开发集和验证集，固定最终集不进入搜索。"""
        from examples.ch17.dataset import load_tasks
        seen = []

        def tracked(split):
            """记录测试中的分组访问。"""
            seen.append(split)
            return load_tasks(split)

        with patch("examples.ch27.demo.load_tasks", side_effect=tracked):
            result = search()
        self.assertEqual(seen, ["dev", "validation"])
        self.assertFalse(result["test_loaded"])
        self.assertEqual(result["model_calls"], 0)
        with self.assertRaises(ValueError):
            search(budget=4)

    def test_live_proposal_contract(self):
        """覆盖--live使用的参数分支，不发送离线回放或私有目标。"""
        proposed = make_text("check_result")
        response = {"choices": [{"message": {"content": proposed}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 33}, "_meta": {"mode": "live"}}
        with patch("examples.common.llm.chat_completion", return_value=response) as call:
            text, meta = propose_live(BASE, {"passed": 3, "total": 10, "failure_counts": {"error_explained": 5}})
        self.assertEqual(text, proposed)
        self.assertEqual(meta["usage"]["total_tokens"], 33)
        self.assertTrue(call.call_args.kwargs["live"])
        self.assertNotIn("offline_response", call.call_args.kwargs)
        sent = json.dumps(call.call_args.args[0], ensure_ascii=False)
        self.assertNotIn('"expected"', sent)
        self.assertNotIn('"setup"', sent)
        self.assertNotIn("test_", sent)
        for reason, refusal in (("length", None), ("stop", "拒绝示意")):
            incomplete = {"choices": [{"finish_reason": reason,
                                       "message": {"content": proposed, "refusal": refusal}}]}
            with patch("examples.common.llm.chat_completion", return_value=incomplete):
                with self.assertRaises(ValueError):
                    propose_live(BASE, {})

    def test_adoption_hash_and_rollback(self):
        """未确认不替换、评测后偷换内容失败，明确采纳后能恢复原文。"""
        with TemporaryDirectory(prefix="agentbook-release-test-") as temporary:
            directory = Path(temporary)
            report = run_release(directory)
            self.assertEqual((directory / "active.txt").read_text(encoding="utf-8"), BASE)
            candidate = json.loads((directory / "frozen.json").read_text(encoding="utf-8"))["text"]
            review = report["验收"]
            with self.assertRaises(ValueError):
                activate(directory, candidate, review, human_confirmed=False)
            with self.assertRaises(ValueError):
                activate(directory, BASE, review, human_confirmed=True)
            frozen_path = directory / "frozen.json"
            original = frozen_path.read_text(encoding="utf-8")
            tampered = json.loads(original)
            tampered["text"] = BASE
            frozen_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                activate_reviewed(directory)
            frozen_path.write_text(original, encoding="utf-8")
            with patch("examples.ch28.demo.search", side_effect=AssertionError("采纳不应重搜")), \
                 patch("examples.ch28.demo.load_tasks", side_effect=AssertionError("采纳不应重新读取测试")):
                activate_reviewed(directory)
            self.assertEqual(digest((directory / "active.txt").read_text(encoding="utf-8")), review["candidate_sha256"])
            rollback(directory)
            self.assertEqual((directory / "active.txt").read_text(encoding="utf-8"), BASE)
            self.assertFalse(report["无提升候选"]["eligible"])
            self.assertFalse(report["退化候选"]["eligible"])


if __name__ == "__main__":
    unittest.main()
