"""用本地模拟响应验证裁判入口，不访问网络、不产生模型费用。"""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from examples.ch19 import demo


def mock_response(value, *, finish_reason="stop", refusal=None):
    """构造协议响应；其内容是测试输入，不是实际模型裁判结论。"""
    return {
        "model": "local-mock-judge",
        "choices": [{
            "finish_reason": finish_reason,
            "message": {
                "content": json.dumps(value, ensure_ascii=False),
                "refusal": refusal,
            },
        }],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


class JudgeEntryTests(unittest.TestCase):
    """检验入口行为、位置互换与不合格输出的拒绝边界。"""

    def test_live_calls_swap_positions_and_preserve_usage(self):
        responses = [
            mock_response({"winner": "A", "reason": "A 没有承诺到账。"}),
            mock_response({"winner": "B", "reason": "B 没有承诺到账。"}),
        ]
        output = io.StringIO()
        with patch.object(demo, "chat_completion", side_effect=responses) as client:
            with patch("sys.argv", ["ch19.demo", "--live"]), redirect_stdout(output):
                demo.main()

        self.assertEqual(client.call_count, 2)
        messages = []
        for call in client.call_args_list:
            self.assertIs(call.kwargs["live"], True)
            self.assertEqual(call.kwargs["max_completion_tokens"], 300)
            self.assertNotIn("offline_response", call.kwargs)
            self.assertEqual([row["role"] for row in call.args[0]], ["system", "user"])
            messages.append(call.args[0])
        self.assertEqual(messages[0][0], messages[1][0])
        first, second = [json.loads(rows[1]["content"]) for rows in messages]
        self.assertEqual(first["evidence"], {"amount_cents": 12900, "status": "requested"})
        self.assertEqual(second["evidence"], first["evidence"])
        self.assertEqual(first["A"], second["B"])
        self.assertEqual(first["B"], second["A"])
        self.assertEqual(first["A"], demo.ANSWERS["grounded"])
        self.assertEqual(first["B"], demo.ANSWERS["unsupported"])

        rows = [json.loads(line) for line in output.getvalue().splitlines()
                if line.startswith('{"位置对应"')]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["位置对应"], ["grounded", "unsupported"])
        self.assertEqual(rows[1]["位置对应"], ["unsupported", "grounded"])
        for row, response in zip(rows, responses):
            self.assertEqual(row["model"], response["model"])
            self.assertEqual(row["usage"], response["usage"])
            self.assertEqual(row["裁判结果"], json.loads(response["choices"][0]["message"]["content"]))

    def test_valid_winner_categories(self):
        for winner in ("A", "B", "tie", "uncertain"):
            with self.subTest(winner=winner):
                value = {"winner": winner, "reason": "依据现有证据作出判断。"}
                self.assertEqual(demo.parse_judgment(mock_response(value)), value)

    def test_malformed_judgments_are_rejected(self):
        invalid_values = [
            None, [], "A", 100, {},
            {"winner": "C", "reason": "越出约定枚举。"},
            {"winner": 100, "reason": "本协议不接受数值分数。"},
            {"winner": ["A"], "reason": "类型错误。"},
            {"winner": "A"}, {"reason": "缺少赢家字段。"},
            {"winner": "A", "reason": " "},
            {"winner": "A", "reason": 1},
        ]
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                demo.parse_judgment(mock_response(value))
        invalid_json = mock_response({})
        invalid_json["choices"][0]["message"]["content"] = '{"winner":'
        for response in ({}, {"choices": []}, invalid_json):
            with self.subTest(response=response), self.assertRaises(ValueError):
                demo.parse_judgment(response)

    def test_truncation_and_refusal_are_rejected_even_with_valid_json(self):
        value = {"winner": "A", "reason": "形式合法但响应并未正常完成。"}
        for reason in ("length", "content_filter", "tool_calls", None):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                demo.parse_judgment(mock_response(value, finish_reason=reason))
        with self.assertRaises(ValueError):
            demo.parse_judgment(mock_response(value, refusal="无法评价该内容。"))

    def test_invalid_first_judge_stops_live_run(self):
        response = mock_response({"winner": "C", "reason": "无效枚举。"})
        output = io.StringIO()
        with patch.object(demo, "chat_completion", return_value=response) as client:
            with patch("sys.argv", ["ch19.demo", "--live"]), redirect_stdout(output):
                with self.assertRaises(ValueError):
                    demo.main()
        self.assertEqual(client.call_count, 1)
        self.assertNotIn('"裁判结果"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
