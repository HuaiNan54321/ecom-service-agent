"""核对路径分支与预算耗尽时的实际停止行为。"""

import unittest
from unittest.mock import patch

from examples.ch09.demo import offline_response, tool_request
from examples.ch10.demo import fixed_workflow, run_loop


class LoopTests(unittest.TestCase):
    """相同输入下核对确定性流程，不以此评估模型质量。"""

    def test_paths(self):
        for order_id, calls in [("A1001", 2), ("A1002", 1)]:
            fixed = fixed_workflow(order_id)
            loop = run_loop(order_id)
            self.assertEqual(len(fixed["工具"]), calls)
            self.assertEqual(loop["工具次数"], calls)
            self.assertEqual(loop["模型调用次数"], calls + 1)
            self.assertEqual(loop["停止原因"], "final_answer")

    def test_limits(self):
        count = 0
        def repeated(*args, **kwargs):
            """每轮都请求同一个只读动作，但使用新的配对标识。"""
            nonlocal count
            count += 1
            return offline_response(tool_request("query_order", "A1001", f"call_{count}"))
        with patch("examples.ch10.demo.chat_completion", repeated):
            result = run_loop(max_model_calls=2)
        self.assertEqual(result["停止原因"], "model_budget")
        self.assertEqual(result["模型调用次数"], 2)
        self.assertEqual(result["工具次数"], 2)
        limited = run_loop(max_tool_calls=0)
        self.assertEqual(limited["停止原因"], "tool_budget")
        self.assertEqual(limited["工具次数"], 0)

    def test_live_usage_is_kept_per_request(self):
        usage = [{"prompt_tokens": 80, "completion_tokens": 15, "total_tokens": 95},
                 None,
                 {"prompt_tokens": 160, "completion_tokens": 20, "total_tokens": 180}]
        replies = [offline_response(tool_request("query_order", "A1001", "live_1")),
                   offline_response(tool_request("query_logistics", "A1001", "live_2")),
                   offline_response({"role": "assistant", "content": "已取得物流记录。"})]
        for response, counts in zip(replies, usage):
            response["usage"] = counts
        def fake_client(messages, **kwargs):
            """模拟服务响应形状，验证未知用量不会被伪填为零。"""
            self.assertTrue(kwargs["live"])
            self.assertIsNone(kwargs.get("offline_response"))
            return replies.pop(0)
        with patch("examples.ch10.demo.chat_completion", fake_client):
            result = run_loop(live=True)
        self.assertEqual(result["usage"], usage)
        self.assertFalse(result["用量是否完整"])
        self.assertEqual(result["模型调用次数"], 3)


if __name__ == "__main__":
    unittest.main()
