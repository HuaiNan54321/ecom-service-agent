"""核对同源文本的去重、数据隔离，以及可评分的退款变体。"""

import json
import unittest
from unittest.mock import patch

from examples.ch05.demo import fixed_response
from examples.ch17.dataset import load_tasks, public_input
from examples.ch17.prepare import prepare_dataset, refund_variant, seed_records
from examples.ch20.runner import run_task


class PrepareTest(unittest.TestCase):
    def test_cleaning_preserves_frozen_tasks_and_difficult_cases(self):
        rows = seed_records()
        seed = next(row for row in rows if row["source"] == "dev_05")
        rows.append({**seed, "source": "同源改写", "text": "订单 A1002 全额退，我已确认。"})
        rows[0]["text"] += "可发至 second+shop@example.invalid 或 spare@example.invalid。"
        splits, rejected = prepare_dataset(rows)
        self.assertEqual(rejected, {"重复导出": "同一来源夹具已收录", "同源改写": "同一来源夹具已收录",
                                   "开票咨询": "超出本轮业务范围", "缺少原始记录": "缺少可核对的任务夹具"})
        for name, prepared in splits.items():
            frozen = load_tasks(name)
            self.assertEqual([t["id"] for t in prepared], [t["id"] for t in frozen])
            self.assertEqual([t["expected"] for t in prepared], [t["expected"] for t in frozen])
        example = next(t for t in splits["dev"] if t["id"] == "dev_05")
        self.assertNotIn("@", example["input"])
        self.assertEqual(splits["dev"][0]["input"].count("[邮箱]"), 2)
        self.assertNotIn("expected", public_input(example))
        self.assertNotIn("setup", public_input(example))
        with self.assertRaisesRegex(ValueError, "来源编号"):
            prepare_dataset(rows + [rows[-1]])

    def test_variant_keeps_parent_family_and_changes_verified_amount(self):
        base, _ = prepare_dataset(seed_records())
        expanded, _ = prepare_dataset(seed_records(), augment=True)
        for name in ("validation", "test"):
            self.assertEqual(base[name], expanded[name])
        self.assertEqual(len(expanded["dev"]), 11)
        parent, variant = [t for t in expanded["dev"] if t["id"].startswith("dev_05")]
        self.assertEqual(parent["family"], variant["family"])
        self.assertEqual(parent["expected"]["refund_amount"], 5900)
        self.assertEqual(variant["expected"]["refund_amount"], 1200)
        self.assertEqual(variant["parent_id"], parent["id"])
        self.assertEqual(variant["generation"]["来源"], "固定候选（离线）")
        self.assertTrue(run_task(variant, "checked")["passed"])

    def test_generated_candidate_has_no_authority_over_the_oracle(self):
        parent = next(t for t in load_tasks("dev") if t["id"] == "dev_05")
        valid = {"amount_yuan": 7, "utterance": "订单 A1002 只申请退 7 元，我确认提交。"}
        with patch("examples.ch17.prepare.chat_completion") as model:
            model.return_value = fixed_response(json.dumps(valid, ensure_ascii=False))
            case = refund_variant(parent, live=True)
            self.assertEqual(case["expected"]["refund_amount"], 700)
            self.assertEqual(case["generation"]["来源"], "在线模型")
            self.assertTrue(model.call_args.kwargs["live"])
            self.assertIsNone(model.call_args.kwargs["offline_response"])
            for invalid in ({**valid, "expected": "全通过"}, {**valid, "amount_yuan": 59},
                            {**valid, "amount_yuan": True}, {**valid, "amount_yuan": 6},
                            {**valid, "utterance": "订单 A1002 想问一下能退 7 元吗？"}):
                model.return_value = fixed_response(json.dumps(invalid, ensure_ascii=False))
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    refund_variant(parent, live=True)
