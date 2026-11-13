"""开发、验证、冻结、最终核对的最小报告链；只评确定性策略。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from examples.ch17.dataset import load_tasks
from examples.ch20.runner import run_suite, policy_flags


def digest(value):
    """固定编码与排序，让同一配置在报告中得到同一标识。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def main():
    parser = argparse.ArgumentParser(description="生成确定性策略的评测报告")
    parser.add_argument("--output", type=Path, help="可选：将完整报告保存到指定JSON文件")
    args = parser.parse_args()
    dev = {name: run_suite(load_tasks("dev"), name) for name in ("baseline", "checked")}
    validation = {name: run_suite(load_tasks("validation"), name) for name in ("baseline", "checked")}
    baseline, candidate = validation["baseline"], validation["checked"]
    old_pass = {row["task_id"] for row in baseline["rows"] if row["passed"]}
    new_pass = {row["task_id"] for row in candidate["rows"] if row["passed"]}
    regressions = sorted(old_pass - new_pass)
    accepted = candidate["passed"] >= baseline["passed"] and not regressions and candidate["tool_calls"] <= 2 * candidate["total"]
    selected = "checked" if accepted else "baseline"
    frozen = {"policy": selected, "flags": policy_flags(selected), "policy_hash": digest(policy_flags(selected))}
    # 候选选择到此结束，下面才读取最终组；不根据最终成绩重新选择。
    final_tasks = load_tasks("test")
    final = run_suite(final_tasks, selected)
    report = {"mode": "deterministic_policy", "generated_at": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "dataset_version": "teaching-v1",
              "dataset_hash": digest({split: load_tasks(split) for split in ("dev", "validation", "test")}),
              "selection": {**frozen, "accepted": accepted, "regressions": regressions},
              "development": dev, "validation": validation, "final": final,
              "limits": "固定开关流程校验；不是模型效果、真人体验或生产质量证明。"}
    assert candidate["passed"] == 10 and final["passed"] == 10
    assert not regressions
    summary = {"性质": report["limits"], "验证组": {name: {key: row[key] for key in ("passed", "total", "tool_calls")} for name, row in validation.items()},
               "冻结策略": frozen, "最终组": {key: final[key] for key in ("passed", "total", "tool_calls", "model_calls")}}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["报告路径"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
