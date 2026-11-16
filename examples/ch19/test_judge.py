"""复核退款文本的引用、评分和弃判处理，使用固定记录代替外部模型。"""

import json
import unittest
from unittest.mock import patch

from examples.ch19 import judge


def envelope(value):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]}


class RefundTextJudgeTests(unittest.TestCase):
    def test_replay_keeps_evidence_and_business_gate_separate(self):
        report = judge.run()
        rows = {r["id"]: r for r in report["rows"]}
        self.assertEqual(rows["clear"]["evidence"]["E2"]["amount_cents"], 5900)
        self.assertEqual(rows["no_write"]["judgment"]["score"], 2)
        self.assertFalse(rows["no_write"]["quality_gate_passed"])
        self.assertEqual((report["calibration_count"], report["abstained"], report["invalid"]), (6, 1, 0))
        self.assertEqual((report["calibration"]["fp"], report["calibration"]["fn"]), (1, 1))

    def test_rejects_invented_references_wrong_types_and_unfinished_outputs(self):
        response = {"score": 2, "evidence_ids": ["E2"], "quote": "已登记", "reason": "记录显示已登记"}
        evidence = {"E2": {"status": "requested"}}
        for changes in ({"evidence_ids": ["编造"]}, {"evidence_ids": []}, {"quote": "已到账"},
                        {"score": True}, {"score": 3}, {"score": "2"}, {"reason": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                judge.parse_score(envelope({**response, **changes}), "已登记", evidence)
        for invalid in ({"finish_reason": "length"}, {"message": {"refusal": "拒答"}}):
            data = envelope(response)
            data["choices"][0].update(invalid)
            with self.assertRaises(ValueError):
                judge.parse_score(data, "已登记", evidence)

    def test_live_contract_never_sends_reference_or_counts_invalid_as_a_vote(self):
        def answer(messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            self.assertEqual(set(payload), {"reply", "evidence"})
            self.assertIs(kwargs["live"], True)
            return envelope({"score": 2, "evidence_ids": ["不存在"], "quote": payload["reply"],
                             "reason": "伪造引用的输出不应进入校准统计。"})

        with patch.object(judge, "chat_completion", side_effect=answer) as client:
            report = judge.run(live=True)
        self.assertEqual(client.call_count, 7)
        self.assertEqual((report["invalid"], report["calibration_count"], report["calibration"]), (7, 0, None))
