"""检查恢复失败不会让调用次数回退，防止无限重试。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.ch22.demo import phase
from examples.common import Sandbox


class RecoveryBudgetTests(unittest.TestCase):
    """查询超时、业务失败、意图不匹配和模拟退出都必须记账。"""

    def test_failed_resume_consumes_persisted_budget(self) -> None:
        """两次失败后预算为三，第三次恢复不能再调用查询工具。"""
        for failure in ("timeout", "business_error", "mismatch", "exit"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                self.assertEqual(phase(directory, "start"), 17)
                database = json.loads((directory / "business.json").read_text(encoding="utf-8"))
                refund = next(iter(database["refunds"].values()))
                refund["amount_cents"] += 1
                behavior = {
                    "timeout": {"side_effect": TimeoutError("模拟查询超时")},
                    "business_error": {"return_value": {"success": False}},
                    "mismatch": {"return_value": {"success": True, "refund": refund}},
                    "exit": {"side_effect": SystemExit("模拟查询期间进程退出")},
                }[failure]
                expected_error = {"timeout": TimeoutError, "exit": SystemExit}.get(
                    failure, RuntimeError
                )
                with patch.object(Sandbox, "query_refund", **behavior) as query:
                    for expected_count in (2, 3):
                        with self.assertRaises(expected_error):
                            phase(directory, "resume")
                        state = json.loads(
                            (directory / "checkpoint.json").read_text(encoding="utf-8")
                        )
                        self.assertEqual(state["tool_calls"], expected_count)
                        self.assertEqual(state["phase"], "pending")
                    with self.assertRaisesRegex(RuntimeError, "工具预算耗尽"):
                        phase(directory, "resume")
                    self.assertEqual(query.call_count, 2)


if __name__ == "__main__":
    unittest.main()
