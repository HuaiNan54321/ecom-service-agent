"""冻结文本候选后才做最终测试，展示拒绝、人工采纳与可恢复版本。"""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from examples.ch17.dataset import load_tasks
from examples.ch25.strategy import BASE, digest, evaluate, parse_text, regressions, summary
from examples.ch27.demo import save_search, search


def gate(baseline: dict, candidate: dict, *, max_tool_calls: int = 60) -> dict:
    """固定验收门槛：分数提高、原能力无退化且工具预算未超限。"""
    lost = regressions(baseline, candidate)
    checks = {"成功数提高": candidate["passed"] > baseline["passed"],
              "没有改对为错": not lost,
              "工具调用未超预算": candidate["tool_calls"] <= max_tool_calls}
    return {"eligible": all(checks.values()), "checks": checks,
            "regressed_ids": lost, "max_tool_calls": max_tool_calls}


def activate(directory: Path, candidate: str, review: dict, *, human_confirmed: bool) -> None:
    """只有明确采纳且门槛通过，才替换本地演示策略，并保存旧版本。"""
    parse_text(candidate)
    if human_confirmed is not True or not review["eligible"]:
        raise ValueError("候选尚未通过门槛或未显式确认采纳")
    if digest(candidate) != review["candidate_sha256"]:
        raise ValueError("待采纳文字与已评测版本不一致")
    active = directory / "active.txt"
    if active.read_text(encoding="utf-8") != BASE:
        raise ValueError("当前版本已变化，需重新评估后再替换")
    (directory / "previous.txt").write_text(BASE, encoding="utf-8")
    pending = directory / "active.pending"
    pending.write_text(candidate, encoding="utf-8")
    pending.replace(active)


def rollback(directory: Path) -> None:
    """恢复明确保存的前一版本，不重新生成一份看起来相似的文字。"""
    previous = (directory / "previous.txt").read_text(encoding="utf-8")
    parse_text(previous)
    pending = directory / "active.pending"
    pending.write_text(previous, encoding="utf-8")
    pending.replace(directory / "active.txt")


def activate_reviewed(directory: Path) -> None:
    """读取已经看过的冻结候选与报告，不重新搜索或读取最终测试。"""
    frozen = json.loads((directory / "frozen.json").read_text(encoding="utf-8"))
    report = json.loads((directory / "release.json").read_text(encoding="utf-8"))
    candidate = frozen["text"]
    if frozen["status"] != "frozen_before_test" or digest(candidate) != frozen["candidate_sha256"]:
        raise ValueError("冻结候选内容或状态已变化，拒绝采纳")
    if frozen["candidate_sha256"] != report["验收"]["candidate_sha256"]:
        raise ValueError("冻结候选与审核报告不是同一个版本")
    activate(directory, candidate, report["验收"], human_confirmed=True)


def run_release(directory: Path) -> dict:
    """最终测试成绩只用于最后审核，不再返回候选搜索循环。"""
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("请使用空输出目录，避免覆盖已有实验记录")
    directory.mkdir(parents=True, exist_ok=True)
    result = search(live=False, budget=3)
    save_search(result, directory)
    candidate = result["selected_text"]
    frozen = {"candidate_sha256": digest(candidate), "text": candidate,
              "selection_data_sha256": result["validation_data_sha256"],
              "status": "frozen_before_test"}
    (directory / "frozen.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    # 候选先冻结，再加载最终测试；搜索函数没有测试数据参数。
    test = load_tasks("test")
    base_report, candidate_report = evaluate(BASE, test), evaluate(candidate, test)
    review = gate(base_report, candidate_report)
    review["candidate_sha256"] = frozen["candidate_sha256"]
    (directory / "active.txt").write_text(BASE, encoding="utf-8")
    report = {"性质": "固定策略的有限教学验收，不是模型泛化成绩",
              "最终测试基线": summary(base_report), "最终测试候选": summary(candidate_report),
              "验收": review, "采纳状态": "本报告生成时尚未采纳；当前版本以active.txt为准",
              "final_test_data_sha256": digest(test), "active_sha256": digest((directory / "active.txt").read_text(encoding="utf-8"))}
    # 拒绝示例只复用验证集，不根据最终测试重新生成策略。
    validation = load_tasks("validation")
    current_validation = evaluate(candidate, validation)
    report["无提升候选"] = gate(current_validation, current_validation)
    report["退化候选"] = gate(current_validation, evaluate(BASE, validation))
    (directory / "release.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    """命令行只操作指定的本地演示目录，不连接真实商家系统。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="保存冻结候选与审核报告的空目录")
    parser.add_argument("--activate", type=Path, help="采纳已检查报告目录中的同一冻结候选，不重跑搜索")
    parser.add_argument("--rollback", type=Path, help="恢复指定演示目录保存的前一版本")
    args = parser.parse_args()
    if args.rollback:
        if args.out or args.activate:
            parser.error("回滚与新建验收不能同时使用")
        rollback(args.rollback)
        print("已恢复 previous.txt 中的策略版本")
        return
    if args.activate:
        if args.out:
            parser.error("采纳已有报告与新建验收不能同时使用")
        activate_reviewed(args.activate)
        print("已采纳该目录中通过审核的冻结候选；旧版本保留在previous.txt")
        return
    if args.out:
        report = run_release(args.out)
    else:
        with TemporaryDirectory(prefix="agentbook-ch28-") as temporary:
            report = run_release(Path(temporary))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
