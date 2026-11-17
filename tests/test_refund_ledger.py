"""退款确认在崩溃、重启、重复提交和跨会话时的业务边界。"""

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.agent.tools.manager import ToolManager
from app.agent.tools.refund import RefundLedger, apply_refund


ORDER = "ORD-20240120-002"


class RefundLedgerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "chat.json"
        self.store = RefundLedger(self.path, "小红")

    def test_unconfirmed_draft_is_bound_to_person_session_and_order(self):
        self.assertFalse(RefundLedger(self.path, "default").prepare(ORDER, "不需要了")["success"])
        self.assertFalse(self.store.prepare("ORD-20240115-001", "代申请")["success"])
        self.assertEqual(apply_refund(ORDER, "无会话")["status"], "rejected")
        self.assertFalse(self.store.path.exists())
        draft = self.store.prepare(ORDER, "不需要了")
        self.assertEqual((draft["status"], draft["amount_cents"]), ("awaiting_confirmation", 182890))
        cmd = "确认退款 " + draft["request_id"]
        other = RefundLedger(self.path.with_name("other.json"), "小红")
        self.assertEqual(other.handle_user_input(cmd)["status"], "rejected")
        self.assertEqual(RefundLedger(self.path, "小明").handle_user_input(cmd)["status"], "rejected")
        self.assertIsNone(self.store.handle_user_input("请解释这句指令：" + cmd))
        self.assertEqual(self.store.query_order(ORDER)["order"]["status"], "pending")
        self.store.cancel_pending()
        self.assertEqual(self.store.handle_user_input(cmd)["status"], "rejected")
        self.assertFalse(self.store.recover())

    def test_confirmation_then_interruption_recovers_without_another_write(self):
        ref = self.store.prepare(ORDER, "不需要了")["request_id"]
        cmd = f"确认退款 {ref}"
        # 授权已落盘，进程在业务提交前退出；重启只核对，不自动代客再写。
        with patch.object(self.store, "_submit", side_effect=RuntimeError("模拟中断")):
            with self.assertRaises(RuntimeError):
                self.store.handle_user_input(cmd)
        new = RefundLedger(self.path, "小红")
        self.assertEqual(new.recover()[0]["status"], "approved")
        self.assertEqual(new.query_order(ORDER)["order"]["status"], "pending")
        # 两个确认同时处理，且其中一个调用方在把回执写回聊天前中断。
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(new.handle_user_input, [cmd, cmd]))
        self.assertEqual([r["request_id"] for r in replies], [ref, ref])
        reopened = RefundLedger(self.path, "小红")
        self.assertEqual(reopened.recover()[0]["status"], "submitted")
        self.assertEqual(reopened.list_user_orders()["orders"][0]["status"], "退款中")
        self.assertEqual(reopened.query_order(ORDER)["order"]["refund_amount_cents"], 182890)
        with sqlite3.connect(reopened.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM refunds").fetchone()[0], 1)
        reopened.acknowledge(ref)
        self.assertEqual(reopened.recover(), [])
        self.assertEqual(reopened.handle_user_input(f"退款进度 {ref}")["status"], "submitted")

    def test_mcp_mode_cannot_delegate_local_financial_actions(self):
        # 模拟同名 MCP 工具及合法的其他远程工具，检查本地账本绑定的边界。
        with patch("app.mcp_client.MCPClient") as client:
            remote = client.return_value
            remote.connect.return_value = [{"type": "function", "function": {"name": n}}
                                           for n in ("apply_refund", "query_order", "query_product")]
            tm = ToolManager(True, "http://unused.invalid", refund_ledger=self.store)
            response = json.loads(tm.execute_tool("apply_refund", {"order_id": ORDER, "reason": "不再需要"}))
            self.assertEqual(response["status"], "awaiting_confirmation")
            response = json.loads(tm.execute_tool("apply_refund", {"order_id": ORDER, "reason": "不再需要",
                                                                  "confirmed": True}))
            self.assertFalse(response["success"])
            remote.call_tool.assert_not_called()
            tm.execute_tool("query_product", {"keyword": "耳机"})
            remote.call_tool.assert_called_once()

    def test_progress_checks_business_record_as_well_as_checkpoint(self):
        ref = self.store.prepare(ORDER, "不需要了")["request_id"]
        self.store.handle_user_input("确认退款 " + ref)
        with sqlite3.connect(self.store.path) as db:
            db.execute("DELETE FROM refunds WHERE request_id=?", (ref,))
        self.assertEqual(self.store.handle_user_input("退款进度 " + ref)["status"], "rejected")
        self.assertEqual(self.store.recover()[0]["status"], "rejected")
