"""开发、验证、冻结、最终核对的最小报告链；只评确定性策略。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from examples.ch17.prepare import prepare_dataset, seed_records
from examples.ch20.runner import paired_changes, policy_flags, run_suite


def digest(value):
    """固定编码与排序，让同一配置在报告中得到同一标识。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def main():
    parser = argparse.ArgumentParser(description="生成确定性策略的评测报告")
    parser.add_argument("--output", type=Path, help="可选：将完整报告保存到指定JSON文件")
    parser.add_argument("--augment", action="store_true", help="按第 17 章的方法给开发组增加一条部分退款变体")
    args = parser.parse_args()
    seeds = seed_records()
    splits, rejected = prepare_dataset(seeds, augment=args.augment)
    dev = {name: run_suite(splits["dev"], name) for name in ("baseline", "checked")}
    validation = {name: run_suite(splits["validation"], name) for name in ("baseline", "checked")}
    baseline, candidate = validation["baseline"], validation["checked"]
    paired = {"development": paired_changes(dev["baseline"], dev["checked"]),
              "validation": paired_changes(baseline, candidate)}
    regressions = paired["validation"]["regressions"]
    accepted = (candidate["passed"] >= baseline["passed"]
                and not regressions and candidate["mean_tool_calls"] <= 2)
    selected = "checked" if accepted else "baseline"
    frozen = {"policy": selected, "flags": policy_flags(selected), "policy_hash": digest(policy_flags(selected))}
    # 候选选择到此结束，下面才读取最终组；不根据最终成绩重新选择。
    final_tasks = splits["test"]
    final_baseline = run_suite(final_tasks, "baseline")
    final = run_suite(final_tasks, frozen["flags"])
    paired["test"] = paired_changes(final_baseline, final)
    preparation = {"seed_records": len(seeds), "rejected": rejected, "augment": args.augment,
                   "split_counts": {name: len(tasks) for name, tasks in splits.items()}}
    report = {"mode": "deterministic_policy", "generated_at": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "dataset_version": "ch17-prepared-v1",
              "dataset_hash": digest(splits), "dataset_preparation": preparation,
              "selection": {**frozen, "accepted": accepted, "regressions": regressions},
              "development": dev, "validation": validation, "final_baseline": final_baseline,
              "final": final, "paired": paired,
              "limits": "两套确定性程序策略在相同的本地沙箱各做每题一次。模型调用为零，Token 用量不适用。"}
    fields = ("passed", "total", "pass_at_1", "tool_calls", "mean_tool_calls",
              "model_calls", "input_tokens", "output_tokens")
    summary = {"性质": report["limits"], "数据准备": preparation, "冻结策略": frozen, "逐题对照": paired,
               "最终组": {key: final[key] for key in fields}}
    groups = {"开发组": dev, "验证组": validation,
              "最终组对照": {"baseline": final_baseline, "frozen": final}}
    for group, runs in groups.items():
        summary[group] = {name: {key: report[key] for key in fields}
                          for name, report in runs.items()}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["报告路径"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
