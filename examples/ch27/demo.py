"""有限候选的文本策略优化：演示反馈、验证选择与预算，不复现完整GEPA。"""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from examples.ch17.dataset import load_tasks
from examples.ch25.strategy import (
    BASE, RULES, development_feedback, digest, evaluate,
    make_text, parse_text, regressions, summary,
)


def pareto_frontier(scores: dict) -> list:
    """在逐任务成绩上保留不被严格支配的候选，演示互补能力。"""
    sizes = {len(values) for values in scores.values()}
    if len(sizes) != 1 or not sizes or 0 in sizes:
        raise ValueError("候选必须有相同且非空的逐任务成绩")
    return [name for name, values in scores.items()
            if not any(other != name and all(a >= b for a, b in zip(rival, values))
                       and any(a > b for a, b in zip(rival, values))
                       for other, rival in scores.items())]


def propose_live(previous: str, feedback: dict) -> tuple:
    """只向模型提供开发反馈及允许的文字，不发送验证或测试判据。"""
    from examples.ch05.demo import read_answer
    from examples.common.llm import chat_completion
    request = {
        "当前策略": previous,
        "开发反馈": feedback,
        "允许逐字使用的句子": [BASE, *RULES.values()],
        "输出要求": "仅输出策略原文，必须保留第一句；其他句子可选，不写代码围栏，不写额外说明。",
    }
    response = chat_completion(
        [{"role": "system", "content": "你只提出教学策略文本候选，无权修改工具、权限、评分器或数据。"},
         {"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
        live=True, max_completion_tokens=256, timeout=30.0,
    )
    text = read_answer(response)
    parse_text(text)
    return text, {"usage": response.get("usage"), "meta": response.get("_meta")}


def search(*, live: bool = False, budget: int = 3) -> dict:
    """每个候选独立重置环境，最终测试集在这里完全不读取。"""
    if type(budget) is not int or not 1 <= budget <= 3:
        raise ValueError("本教学搜索最多允许1至3个候选")
    dev, validation = load_tasks("dev"), load_tasks("validation")
    baseline = evaluate(BASE, validation)
    current, best = BASE, baseline
    plans = [make_text("check_result"),
             make_text("check_result", "clarify_missing"),
             make_text("check_result", "clarify_missing", "recover_timeout")]
    history = []
    live_calls = 0
    for index in range(budget):
        feedback = development_feedback(evaluate(current, dev))
        call_info = None
        if live:
            live_calls += 1
            candidate, call_info = propose_live(current, feedback)
        else:
            candidate = plans[index]
        candidate_report = evaluate(candidate, validation)
        accepted = (candidate_report["passed"] > best["passed"]
                    and not regressions(best, candidate_report))
        history.append({"version": f"v{index + 1}", "text": candidate,
                        "text_sha256": digest(candidate), "development_feedback": feedback,
                        "validation": summary(candidate_report),
                        "regressions": regressions(best, candidate_report),
                        "selected_this_round": accepted, "model_call": call_info})
        if accepted:
            current, best = candidate, candidate_report
    assert live_calls <= budget
    return {"mode": "真实模型提议文本+确定性执行器" if live else "预设候选+确定性执行器",
            "baseline_text": BASE, "selected_text": current,
            "selected_sha256": digest(current), "baseline_validation": summary(baseline),
            "selected_validation": summary(best), "history": history,
            "candidate_budget": budget, "model_calls": live_calls,
            "validation_ids": [task["id"] for task in validation],
            "validation_data_sha256": digest(validation),
            "test_loaded": False}


def save_search(result: dict, directory: Path) -> None:
    """保存版本和比较记录，不修改任何运行中的策略。"""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "v0.txt").write_text(BASE, encoding="utf-8")
    for candidate in result["history"]:
        (directory / f'{candidate["version"]}.txt').write_text(candidate["text"], encoding="utf-8")
    (directory / "search.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """默认离线；显式--live才调用已配置的模型服务。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="显式调用模型提出候选，可能产生API费用")
    parser.add_argument("--budget", type=int, default=3, help="候选次数，范围1至3")
    parser.add_argument("--out", type=Path, help="保存候选和报告的目录；不指定则运行后清理")
    args = parser.parse_args()
    toy = {"A": [1, 1, 0], "B": [0, 1, 1], "C": [0, 1, 0]}
    assert pareto_frontier(toy) == ["A", "B"]
    result = search(live=args.live, budget=args.budget)
    if args.out:
        save_search(result, args.out)
    else:
        with TemporaryDirectory(prefix="agentbook-ch27-") as temporary:
            save_search(result, Path(temporary))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
