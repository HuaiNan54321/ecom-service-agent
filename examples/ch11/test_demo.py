"""核对写操作的边界以及恢复后仍然有效的幂等约束。"""

import unittest

from examples.ch11.demo import run


class ReliableWriteTests(unittest.TestCase):
    """以实际申请记录和订单状态判定，而不是只检查回复。"""

    def test_permissions_and_commit_recovery(self):
        result = run()
        self.assertFalse(result["查询他人订单的退款"]["success"])
        self.assertFalse(result["未确认申请"]["success"])
        self.assertFalse(result["提交前申请存在"])
        self.assertTrue(result["收到超时"])
        self.assertTrue(result["超时后查询"]["success"])
        self.assertTrue(result["恢复后原请求重放"]["replayed"])
        self.assertEqual(result["超时后查询"]["refund"],
                         result["恢复后原请求重放"]["refund"])
        self.assertFalse(result["同键改变参数"]["success"])
        self.assertEqual(result["最终订单状态"], "refund_pending")


if __name__ == "__main__":
    unittest.main()
