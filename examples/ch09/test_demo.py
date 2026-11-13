"""核对工具白名单、参数边界、身份隔离和调用标识。"""

import json
import unittest
from unittest.mock import patch

from examples.common import Sandbox
from examples.ch09.demo import execute_tool_call, offline_response, run, tool_request


class ToolCallTests(unittest.TestCase):
    """每个请求都经应用边界检查，再进入模拟环境。"""

    def test_pair_and_state(self):
        result = run()
        call = result["工具请求"]["tool_calls"][0]
        reply = result["工具回包"]
        self.assertEqual(call["id"], reply["tool_call_id"])
        self.assertEqual(json.loads(reply["content"])["order"]["status"], "shipped")

    def test_invalid_and_foreign(self):
        box = Sandbox()
        for arguments in ['[]', '{"order_id":1}', '{bad',
                          '{"order_id":"A1001","user_id":"U1002"}']:
            call = tool_request("query_order", "A1001", "call_test")["tool_calls"][0]
            call["function"]["arguments"] = arguments
            result = json.loads(execute_tool_call(box, "U1001", call)["content"])
            self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")
        call = tool_request("query_order", "A1003", "call_foreign")["tool_calls"][0]
        self.assertFalse(json.loads(execute_tool_call(box, "U1001", call)["content"])["success"])

    def test_unknown_and_missing_id(self):
        call = tool_request("delete_all", "A1001", "call_unknown")["tool_calls"][0]
        result = json.loads(execute_tool_call(Sandbox(), "U1001", call)["content"])
        self.assertEqual(result["error"]["code"], "UNKNOWN_TOOL")
        del call["id"]
        with self.assertRaises(ValueError):
            execute_tool_call(Sandbox(), "U1001", call)

    def test_live_branch_does_not_supply_offline_reply(self):
        replies = [offline_response(tool_request("query_order", "A1001", "live_01")),
                   offline_response({"role": "assistant", "content": "已取得订单记录。"})]
        def fake_client(messages, **kwargs):
            """代替网络，仅核对真实分支提交的参数，不冒充真实服务测试。"""
            self.assertTrue(kwargs["live"])
            self.assertIsNone(kwargs.get("offline_response"))
            return replies.pop(0)
        with patch("examples.ch09.demo.chat_completion", fake_client):
            self.assertEqual(run(live=True)["工具执行次数"], 1)


if __name__ == "__main__":
    unittest.main()
