"""校验教学检索和 Embedding 响应边界，不发送外部请求。"""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from examples.ch13.demo import cosine, retrieve
from examples.ch13.embeddings import NoRedirect, embed_live, parse_vectors


class RetrievalTests(unittest.TestCase):
    def test_unknown_and_mismatched_vectors(self):
        self.assertEqual(retrieve("营业时间"), [])
        with self.assertRaises(ValueError):
            cosine([1], [1, 2])

    def test_response_order_and_duplicates(self):
        payload = {"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}
        self.assertEqual(parse_vectors(payload, 2), [[1, 0], [0, 1]])
        payload["data"][1]["index"] = 1
        with self.assertRaises(ValueError):
            parse_vectors(payload, 2)

    def test_response_nan_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_vectors({"data": [{"index": 0, "embedding": [float("nan")]}]}, 1)

    def test_live_embedding_request_without_network(self):
        environment = {"AGENTBOOK_BASE_URL": "https://example.invalid/v1", "AGENTBOOK_API_KEY": "教学假密钥", "AGENTBOOK_EMBEDDING_MODEL": "教学模型"}
        response = io.BytesIO(json.dumps({"data": [{"index": 0, "embedding": [1.0, 0.0]}]}).encode())
        with patch.dict("os.environ", environment), patch("examples.ch13.embeddings.build_opener") as opener:
            opener.return_value.open.return_value = response
            vectors, usage = embed_live(["教学文本"])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://example.invalid/v1/embeddings")
            self.assertEqual(json.loads(request.data), {"model": "教学模型", "input": ["教学文本"]})
            self.assertEqual(vectors, [[1.0, 0.0]])
            self.assertEqual(usage, {})
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid"))

    def test_live_generation_passes_no_offline_fixture(self):
        from examples.ch13.demo import main
        with patch("sys.argv", ["demo", "--live"]), patch("examples.common.llm.chat_completion", return_value={"choices": []}) as call, redirect_stdout(io.StringIO()):
            main()
        self.assertEqual(call.call_args.kwargs, {"live": True})
        self.assertIn("[P01]", call.call_args.args[0][1]["content"])


if __name__ == "__main__":
    unittest.main()
