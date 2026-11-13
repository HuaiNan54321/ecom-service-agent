"""用本机 HTTP 服务验证各章真实调用分支；不连接模型供应商，也不计模型质量。"""

from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch

from examples.ch05.demo import fixed_response, read_answer
from examples.ch07.demo import inspect


class InterfaceTests(unittest.TestCase):
    """检查入口确实发出请求、处理流式尾块，并守住文本与字段检查。"""

    def test_live_entry_points(self):
        """覆盖 --live 路径，防止把离线响应与真实调用参数同时传入。"""
        requests = []

        class Handler(BaseHTTPRequestHandler):
            """只服务本次测试的本机接口，响应内容由测试固定编写。"""

            def log_message(self, *args):
                """关闭服务日志，避免记录请求中不必要的信息。"""

            def do_POST(self):
                """根据请求模式返回普通 JSON 或包含用量尾块的 SSE。"""
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                requests.append((self.path, self.headers["Authorization"], body))
                if body.get("stream"):
                    chunks = [
                        {"choices": [{"index": 0, "delta": {"content": "测试文本"}, "finish_reason": None}]},
                        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}},
                    ]
                    content = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                    payload = (content + "data: [DONE]\n\n").encode("utf-8")
                    content_type = "text/event-stream"
                else:
                    answer = '{"intent":"查询物流","order_id":"A1001"}' if body.get("response_format") else "本机接口测试文本。"
                    response = fixed_response(answer)
                    response["model"] = "local-http-test"
                    payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        environment = {
            "AGENTBOOK_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "AGENTBOOK_MODEL": "local-http-test",
            "AGENTBOOK_API_KEY": "local-test-placeholder",
        }
        try:
            with patch.dict(os.environ, environment):
                for chapter, flags in [("ch05", []), ("ch05", ["--stream"]), ("ch06", []), ("ch07", []), ("ch08", [])]:
                    with self.subTest(chapter=chapter, flags=flags):
                        module = importlib.import_module(f"examples.{chapter}.demo")
                        output = io.StringIO()
                        with patch.object(sys, "argv", ["demo", "--live", *flags]), redirect_stdout(output):
                            module.main()
                        self.assertIn("真实", output.getvalue())
            self.assertEqual(len(requests), 9)
            for path, authorization, body in requests:
                self.assertEqual(path, "/v1/chat/completions")
                self.assertEqual(authorization, "Bearer local-test-placeholder")
                self.assertEqual(body["model"], "local-http-test")
                self.assertLessEqual(body["max_completion_tokens"], 256)
                self.assertIsInstance(body["messages"], list)
            stream = next(body for _, _, body in requests if body.get("stream"))
            self.assertTrue(stream["stream_options"]["include_usage"])
            structured = next(body for _, _, body in requests if body.get("response_format"))
            self.assertTrue(structured["response_format"]["json_schema"]["strict"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_incomplete_and_refused_answers(self):
        """回答文本出现了，也不意味着可以直接当完整成功结果。"""
        response = fixed_response("未完成")
        response["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(ValueError):
            read_answer(response)
        response = fixed_response("不使用这段内容")
        response["choices"][0]["message"]["refusal"] = "拒绝示意"
        with self.assertRaises(ValueError):
            read_answer(response)

    def test_business_layer(self):
        """结构正确仍可能提错对象、遗漏编号或越过访问边界。"""
        self.assertEqual(inspect('{"intent":"查询物流","order_id":"A1001"}', "查订单A1001")[0], "通过")
        self.assertEqual(inspect('{"intent":"查询物流","order_id":"A2001"}', "查 A1001")[0], "业务依据")
        self.assertEqual(inspect('{"intent":"查询物流","order_id":"A2001"}', "查 A2001")[0], "业务依据")
        self.assertEqual(inspect('{"intent":"查询物流","order_id":null}', "查 A1001")[0], "业务依据")

    def test_stream_refusal_and_empty_text(self):
        """流式拒绝和空内容都应结束为失败，不能只看 stop 就宣告成功。"""
        module = importlib.import_module("examples.ch05.demo")
        for delta in ({"refusal": "拒绝示意"}, {}):
            chunks = [{"choices": [{"delta": delta, "finish_reason": "stop"}]}]
            with self.subTest(delta=delta):
                with patch.object(module, "stream_completion", return_value=iter(chunks)):
                    with patch.object(sys, "argv", ["demo", "--stream"]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as caught:
                            module.main()
                self.assertEqual(caught.exception.code, 1)

    def test_diagnostics_omit_secret(self):
        """诊断只报告配置是否存在，不打印配置值。"""
        module = importlib.import_module("examples.appendix_c.diagnose")
        output = io.StringIO()
        with patch.dict(os.environ, {"AGENTBOOK_API_KEY": "must-not-appear-in-diagnostics"}), redirect_stdout(output):
            module.main()
        self.assertNotIn("must-not-appear-in-diagnostics", output.getvalue())
        self.assertTrue(json.loads(output.getvalue())["配置是否存在"]["AGENTBOOK_API_KEY"])


if __name__ == "__main__":
    unittest.main()
