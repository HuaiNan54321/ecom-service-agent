"""确认退款后在 CLI 展示回执前中断，下次启动应补发这张回执。"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.agent.tools.refund import RefundLedger


ROOT = Path(__file__).resolve().parents[1]


def stop_before_receipt(*args, **kwargs):
    """只在 CLI 即将显示退款成功回执时模拟进程退出，保留之前已写入的会话和订单。"""
    if any("退款处理中" in str(arg) for arg in args):
        os._exit(73)
    print(*args, **kwargs)


class RefundReceiptIntegrationTest(unittest.TestCase):
    def test_restart_delivers_committed_receipt_once(self):
        for multi in (False, True):
            with self.subTest(multi=multi), tempfile.TemporaryDirectory() as tmp:
                session = Path(tmp) / "session.json"
                ledger = RefundLedger(session, "小红")
                ref = ledger.prepare("ORD-20240120-002", "不需要了")["request_id"]
                env = {
                    **os.environ, "PYTHONPATH": str(ROOT), "SESSION_PATH": str(session),
                    "MEMORY_USER_ID": "小红", "MULTI_AGENT_ENABLED": str(multi),
                    "MCP_ENABLED": "false", "MEMORY_ENABLED": "false", "SKILLS_ENABLED": "false",
                    "OPENAI_BASE_URL": "http://127.0.0.1:1/v1", "OPENAI_API_KEY": "offline",
                }

                def run(args, user_input):
                    return subprocess.run([sys.executable, *args], input=user_input, text=True,
                                          cwd=tmp, env=env, capture_output=True, timeout=20)

                crash = ("import main\n"
                         "from tests.test_runtime_integration import stop_before_receipt\n"
                         "main.print = stop_before_receipt\n"
                         "main.main()")
                first = run(["-c", crash], f"确认退款 {ref}\n")
                self.assertEqual(first.returncode, 73, first.stderr)
                receipt, = ledger.recover()
                self.assertEqual((receipt["status"], receipt["request_id"]), ("submitted", ref))

                second = run([str(ROOT / "main.py")], "exit\n")
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertIn(receipt["message"], second.stdout)
                self.assertFalse(ledger.recover())
                third = run([str(ROOT / "main.py")], "exit\n")
                self.assertEqual(third.returncode, 0, third.stderr)
                self.assertNotIn(receipt["message"], third.stdout)
                with closing(sqlite3.connect(ledger.path)) as db:
                    self.assertEqual(db.execute("SELECT request_id FROM refunds").fetchall(), [(ref,)])
