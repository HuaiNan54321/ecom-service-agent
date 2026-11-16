"""核对单次尝试的分母、工具计数和逐题对照。"""

import unittest

from examples.ch17.prepare import prepare_dataset, seed_records
from examples.ch20.runner import paired_changes, run_suite


class TestPairedComparison(unittest.TestCase):
    def test_frozen_test_cases(self):
        splits, _ = prepare_dataset(seed_records())
        tasks = splits["test"]
        baseline = run_suite(tasks, "baseline")
        checked = run_suite(list(reversed(tasks)), "checked")
        self.assertEqual((baseline["passed"], baseline["total"]), (1, 10))
        self.assertEqual((checked["passed"], checked["total"]), (10, 10))
        self.assertEqual((baseline["pass_at_1"], checked["pass_at_1"]), (0.1, 1.0))
        self.assertEqual((baseline["tool_calls"], checked["mean_tool_calls"]), (11, 1.1))
        self.assertEqual(checked["model_calls"], 0)
        self.assertIsNone(checked["input_tokens"])
        self.assertIsNone(checked["output_tokens"])
        changes = paired_changes(baseline, checked)
        self.assertEqual(changes["delta_pp"], 90)
        self.assertEqual(changes["regressions"], [])
        self.assertEqual(changes["improved"], [f"test_{i:02d}" for i in range(2, 11)])
        self.assertEqual(paired_changes(checked, baseline)["regressions"], changes["improved"])

    def test_task_ids_must_be_unique_and_paired(self):
        rows = [{"task_id": "同一题", "passed": True}]
        for unmatched in ([], rows * 2, [{"task_id": "另一题", "passed": True}]):
            with self.subTest(rows=unmatched), self.assertRaises(ValueError):
                paired_changes({"rows": rows}, {"rows": unmatched})


if __name__ == "__main__":
    unittest.main()
