"""公共机制的确定性验证；HTTP 服务仅在本机回环地址运行，不调用模型。"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError

from examples.common.sandbox import Sandbox, seed_state
from examples.common.llm import ModelAPIError, chat_completion, stream_completion


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()

    def submit(self, **kwargs):
        return self.box.request_refund("U1001", "A1001", "不再需要", request_id="REQ1", confirmed=True, **kwargs)

    def test_access_and_snapshot_isolation(self):
        before = self.box.snapshot()
        for operation in [self.box.query_order, self.box.query_logistics, self.box.query_refund]:
            self.assertEqual(operation("U1001", "A1003")["error"]["code"], "ORDER_NOT_ACCESSIBLE")
            self.assertFalse(operation("U1001", ["A1001"])["success"])
        self.assertEqual(before, self.box.snapshot())
        result = self.box.query_order("U1001", "A1001")
        result["order"]["status"] = "被外部改动"
        self.assertEqual(self.box.query_order("U1001", "A1001")["order"]["status"], "shipped")
        self.assertFalse(self.box.query_logistics("U1001", "A1002")["success"])

    def test_confirmation_policy_amount_and_no_failed_write(self):
        before = self.box.snapshot()
        for confirmation in [False, "true", 1]:
            self.assertEqual(self.box.request_refund("U1001", "A1001", "不需要", request_id="X", confirmed=confirmation)["error"]["code"], "CONFIRMATION_REQUIRED")
        for amount in [True, 129.0, 0, -1, 12901]:
            self.assertEqual(self.submit(amount_cents=amount)["error"]["code"], "INVALID_AMOUNT")
        self.assertEqual(self.box.request_refund("U1001", "A1004", "不需要", request_id="X", confirmed=True)["error"]["code"], "POLICY_DENIED")
        self.assertEqual(before, self.box.snapshot())

    def test_commit_idempotency_and_conflict(self):
        first = self.submit()
        self.assertTrue(first["success"])
        self.assertFalse(first["replayed"])
        self.assertEqual(first["refund"]["amount_cents"], 12900)
        self.assertEqual(first["refund"]["request_id"], "REQ1")
        self.assertEqual(self.box.query_order("U1001", "A1001")["order"]["status"], "refund_pending")
        self.assertTrue(self.submit()["replayed"])
        self.assertEqual(self.submit(amount_cents=100)["error"]["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(len(self.box.snapshot()["refunds"]), 1)
        self.assertEqual(self.box.request_refund("U1001", "A1001", "不再需要", request_id="REQ2", confirmed=True)["error"]["code"], "REFUND_ALREADY_EXISTS")

    def test_lost_reply_and_recovery(self):
        self.box.inject_failure("request_refund", when="after_commit")
        with self.assertRaises(TimeoutError):
            self.submit()
        self.assertTrue(self.box.query_refund("U1001", "A1001")["success"])
        self.box = Sandbox.from_snapshot(self.box.snapshot())
        self.assertTrue(self.submit()["replayed"])
        self.assertEqual(len(self.box.snapshot()["refunds"]), 1)
        self.box.reset()
        self.assertFalse(self.box.query_refund("U1001", "A1001")["success"])

    def test_failure_before_write_is_once(self):
        before = self.box.snapshot()
        self.box.inject_failure("request_refund")
        with self.assertRaises(TimeoutError):
            self.submit()
        self.assertEqual(before, self.box.snapshot())
        self.assertTrue(self.submit()["success"])

    def test_seed_customization_and_isolation(self):
        state = seed_state()
        state["orders"]["A1001"]["eligible"] = False
        restored = Sandbox.from_snapshot(state)
        self.assertFalse(restored.request_refund("U1001", "A1001", "不需要", request_id="X", confirmed=True)["success"])
        self.assertTrue(self.submit()["success"])
        state["orders"]["A1001"]["amount_cents"] = True
        with self.assertRaises(ValueError):
            Sandbox.from_snapshot(state)


@contextmanager
def local_service(status=200, body=None, raw=None, redirect=None):
    """启动一次局部 HTTP 桩；只记录假的测试凭据与请求，不含用户信息。"""
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            """测试不打印 HTTP 请求日志。"""

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append({"path": self.path, "authorization": self.headers.get("Authorization"), "payload": payload})
            self.send_response(status)
            if redirect:
                self.send_header("Location", redirect)
            self.send_header("Content-Type", "text/event-stream" if raw else "application/json")
            self.end_headers()
            data = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    env = {"AGENTBOOK_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1", "AGENTBOOK_MODEL": "stub-model", "AGENTBOOK_API_KEY": "fake-test-key"}
    try:
        with patch.dict(os.environ, env):
            yield captured
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


class ClientTests(unittest.TestCase):
    messages = [{"role": "user", "content": "解释接口"}]

    def test_offline_never_opens_network(self):
        with patch("examples.common.llm.build_opener", side_effect=AssertionError("离线不应创建网络连接")):
            result = chat_completion(self.messages)
            self.assertIsNone(result["usage"])
            self.assertEqual(result["_meta"]["mode"], "offline")
            self.assertTrue(list(stream_completion(self.messages)))

    def test_http_shape_and_usage(self):
        body = {"choices": [{"message": {"role": "assistant", "content": "桩响应"}, "finish_reason": "stop"}], "usage": {"total_tokens": 7}}
        tools = [{"type": "function", "function": {"name": "query_order", "parameters": {"type": "object"}}}]
        with local_service(body=body) as captured:
            result = chat_completion(self.messages, live=True, tools=tools)
        self.assertEqual(captured[0]["path"], "/v1/chat/completions")
        self.assertEqual(captured[0]["authorization"], "Bearer fake-test-key")
        self.assertEqual(captured[0]["payload"]["tools"], tools)
        self.assertEqual(captured[0]["payload"]["max_completion_tokens"], 256)
        self.assertEqual(result["usage"]["total_tokens"], 7)

    def test_stream_unicode_usage_and_done(self):
        chunks = [{"choices": [{"delta": {"content": "你好"}, "finish_reason": None}]}, {"choices": [], "usage": {"total_tokens": 9}}]
        raw = ("".join("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode("utf-8")
        with local_service(raw=raw) as captured:
            result = list(stream_completion(self.messages, live=True))
        self.assertEqual(result[0]["choices"][0]["delta"]["content"], "你好")
        self.assertEqual(result[1]["choices"], [])
        self.assertEqual(result[1]["usage"]["total_tokens"], 9)
        self.assertTrue(captured[0]["payload"]["stream_options"]["include_usage"])

    def test_incomplete_stream_is_not_success(self):
        with local_service(raw=b'data: {"choices": []}\n\n'):
            with self.assertRaises(ModelAPIError) as caught:
                list(stream_completion(self.messages, live=True))
        self.assertEqual(caught.exception.code, "INCOMPLETE_STREAM")

    def test_malformed_stream_chunks_are_protocol_errors(self):
        for chunk in [{"choices": "错误类型"}, {"choices": [None]},
                      {"choices": [{"delta": "错误类型"}]},
                      {"choices": [{"delta": {"content": 123}}]}]:
            with self.assertRaises(ModelAPIError) as caught:
                list(stream_completion(self.messages, offline_chunks=[chunk]))
            self.assertEqual(caught.exception.code, "PROTOCOL")
        raw = b'data: {"choices": [{"delta": {"content": 123}}]}\n\ndata: [DONE]\n\n'
        with local_service(raw=raw):
            with self.assertRaises(ModelAPIError) as caught:
                list(stream_completion(self.messages, live=True))
            self.assertEqual(caught.exception.code, "PROTOCOL")

    def test_server_error_never_echoes_key(self):
        with local_service(status=401, body={"error": "fake-test-key"}):
            with self.assertRaises(ModelAPIError) as caught:
                chat_completion(self.messages, live=True)
        self.assertEqual(caught.exception.code, "HTTP_401")
        self.assertNotIn("fake-test-key", str(caught.exception))

    def test_redirect_is_not_followed(self):
        with local_service(status=302, body={}, redirect="http://127.0.0.1:1/should-not-run") as captured:
            with self.assertRaises(ModelAPIError) as caught:
                chat_completion(self.messages, live=True)
        self.assertEqual(caught.exception.code, "HTTP_302")
        self.assertEqual(len(captured), 1)

    def test_config_and_invalid_inputs(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ModelAPIError) as caught:
                chat_completion(self.messages, live=True)
        self.assertEqual(caught.exception.code, "CONFIG")
        for limit in [0, True, 4097]:
            with self.assertRaises(ModelAPIError):
                chat_completion(self.messages, max_completion_tokens=limit)
        with self.assertRaises(ModelAPIError):
            chat_completion([])

    def test_live_and_offline_fixture_cannot_mix(self):
        with self.assertRaises(ModelAPIError) as caught:
            chat_completion(self.messages, live=True, offline_response={})
        self.assertEqual(caught.exception.code, "INPUT")
        with self.assertRaises(ModelAPIError) as caught:
            list(stream_completion(self.messages, live=True, offline_chunks=[]))
        self.assertEqual(caught.exception.code, "INPUT")

    def test_transport_errors_are_classified(self):
        env = {"AGENTBOOK_BASE_URL": "https://example.invalid/v1", "AGENTBOOK_MODEL": "test", "AGENTBOOK_API_KEY": "fake-test-key"}
        for error, code in [(TimeoutError(), "TIMEOUT"), (URLError("测试断网"), "NETWORK")]:
            with patch.dict(os.environ, env), patch("examples.common.llm.build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(ModelAPIError) as caught:
                    chat_completion(self.messages, live=True)
                self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
