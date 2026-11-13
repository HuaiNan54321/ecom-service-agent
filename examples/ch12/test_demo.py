"""核对证据保留、整块预算与必需材料缺失的处理。"""

import unittest
from unittest.mock import patch

from examples.ch12.demo import BLOCKS, evidence_report, join_text, pack_context, run


class ContextTests(unittest.TestCase):
    """测试资料筛选算法，不声称验证模型理解。"""

    def test_preserve_conditions(self):
        result = run()
        self.assertEqual(result["保留材料"], ["order", "policy"])
        self.assertEqual(result["对照"]["筛选材料"]["遗漏关键文本"], [])
        self.assertIn("定制商品不适用", result["对照"]["过度压缩摘要"]["遗漏关键文本"])
        self.assertEqual(result["对照"]["保留例外的摘要"]["遗漏关键文本"], [])
        self.assertLessEqual(len(result["筛选后正文"]), 70)

    def test_no_silent_loss(self):
        with self.assertRaises(ValueError):
            pack_context(BLOCKS, {"order", "policy"}, char_budget=10)
        with self.assertRaises(ValueError):
            pack_context(BLOCKS, {"missing"}, char_budget=70)

    def test_live_uses_four_separate_contexts(self):
        sent = []
        def fake_client(messages, **kwargs):
            """仅验证分支与输入，固定响应不表示模型实测。"""
            self.assertTrue(kwargs["live"])
            self.assertIsNone(kwargs.get("offline_response"))
            sent.append(messages[-1]["content"])
            return {"choices": [{"message": {"role": "assistant", "content": "桩响应"},
                                  "finish_reason": "stop"}], "usage": None}
        with patch("examples.ch12.demo.chat_completion", fake_client):
            report = run(live=True)
        self.assertEqual(len(set(sent)), 4)
        self.assertEqual(len(report["模型结果"]), 4)


if __name__ == "__main__":
    unittest.main()
