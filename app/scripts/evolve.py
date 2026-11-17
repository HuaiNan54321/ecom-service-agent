"""从主客服的失败工单中提议一条规则，用独立工单比较后，由维护者决定是否采用。"""

import argparse
import hashlib
import json
import re
import tempfile
import unicodedata
from dataclasses import asdict
from pathlib import Path

from openai import OpenAI

from app.agent.strategies.policy import (
    RULES, current_policy, passes_gate, policy_scope, save_validated, switch_policy,
)
from app.config.settings import settings
from app.evaluation.dataset import load_dataset
from app.evaluation.evaluator import Evaluator, run_comparison
from app.evaluation.sandbox import Sandbox


DEFAULT_HOLDOUT = Path(__file__).resolve().parents[1] / "evaluation" / "evolution_holdout.json"


def propose(rows: list[dict], active: tuple[str, ...], threshold: float) -> tuple[str | None, dict]:
    """一次尝试一条规则。只把失败原因映射为规则编号，不从用户原话中拼接系统指令。"""
    evidence = {key: [] for key in RULES if key not in active}
    for row in rows:
        trace = row.get("trace") or {}
        if (row.get("passed") is not False or row.get("error") or trace.get("error")
                or not trace.get("num_llm_calls")):
            continue
        result, process = row["result"], row["process"]
        reasons = {
            "lookup_first": process.get("tool_accuracy") is not None and process["tool_accuracy"] < threshold,
            "human_handoff": (result.get("requires_human_match") is not None
                              and result["requires_human_match"] < threshold),
            "ground_reply": bool(trace.get("tool_calls")) and (
                (result.get("faithfulness") is not None and result["faithfulness"] < threshold) or
                (result.get("keyword_coverage") is not None and result["keyword_coverage"] < threshold)
            ),
        }
        for key in evidence:
            if reasons[key]:
                evidence[key].append(row["case_id"])
    evidence = {key: ids for key, ids in evidence.items() if ids}
    selected = max(evidence, key=lambda key: len(evidence[key]), default=None)
    return selected, evidence


def split_keys(case_id, turns, source_id=None) -> set[tuple[str, str]]:
    keys = {("case", case_id), ("source", case_id)}
    if source_id:
        keys.add(("source", source_id))
    if not isinstance(turns, list) or not turns or not all(isinstance(t, str) and t.strip() for t in turns):
        raise ValueError(f"{case_id} 缺少用户输入，无法检查留出工单是否独立")
    for turn in turns:
        text = unicodedata.normalize("NFKC", turn).casefold()
        normalized = "".join(char for char in text if char.isalnum())
        if normalized:
            keys.add(("turn", normalized))
        for order_id in re.findall(r"ord-\d+-\d+", text):
            keys.add(("order", order_id))
    return keys


def read_development(path: Path, mode: str, baseline: tuple[int, tuple[str, ...]]) -> list[dict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("protocol"), dict):
        raise ValueError("缺少主客服评测协议，请用 app.scripts.run_eval 重跑开发集")
    protocol = report["protocol"]
    version, rules = baseline
    required = {"producer": "app.scripts.run_eval", "mode": mode, "model": settings.model_name,
                "temperature": settings.temperature, "dimension_threshold": settings.eval_pass_threshold,
                "policy_scope": policy_scope(mode), "policy_version": version, "policy_rules": list(rules)}
    for key, current in required.items():
        if key not in protocol or protocol[key] != current:
            raise ValueError(f"开发报告的 {key} 缺失或与当前配置不符，请用 app.scripts.run_eval 重跑开发集")
    group = report.get("candidate", report)
    rows = group.get("cases") if isinstance(group, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("开发报告应包含真实客服的逐题评测结果，且题号唯一")
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("case_id"), str)
                or not isinstance(row.get("passed"), bool)
                or not all(isinstance(row.get(k), dict) for k in ("process", "result", "trace"))
                or not isinstance(row["trace"].get("num_llm_calls"), int)):
            raise ValueError("开发报告缺少题号、逐题评分或客服轨迹")
    if len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("开发报告存在重复题号")
    return rows


def validate(rows, mode, baseline, selected, evidence, holdout: Path) -> dict:
    version, active = baseline
    checks = load_dataset(holdout)
    development_keys = set()
    for row in rows:
        trace = row["trace"]
        development_keys.update(split_keys(row["case_id"], trace.get("turns"), trace.get("source_id")))
    for case in checks:
        if development_keys.intersection(split_keys(case.id, case.turns, case.source_id)):
            raise ValueError(f"留出题 {case.id} 与开发集共用了题号、来源、原话或订单，请更换独立工单")

    holdout_snapshot = json.dumps([asdict(case) for case in checks], ensure_ascii=False, sort_keys=True)
    candidate_rules = (*active, selected)
    with tempfile.TemporaryDirectory() as root, OpenAI(
        api_key=settings.openai_api_key, base_url=settings.openai_base_url
    ) as client:
        def evaluator(rules):
            sandbox = Sandbox(mode=mode, tmp_root=root, policy_override=rules)
            return Evaluator(sandbox, client, settings.model_name, use_judge=False,
                             pass_threshold=settings.eval_pass_threshold)

        report = run_comparison(checks, evaluator(active), evaluator(candidate_rules), answer_only=False)

    paired = report["paired"]
    errors = sum(report[side]["summary"]["errors"] for side in ("baseline", "candidate"))
    eligible = passes_gate(paired, errors)
    protocol = {
        "mode": mode, "model": settings.model_name, "temperature": settings.temperature,
        "policy_scope": policy_scope(mode), "baseline_version": version, "baseline_rules": list(active), "candidate_rules": list(candidate_rules),
        "holdout_cases_sha256": hashlib.sha256(holdout_snapshot.encode()).hexdigest(),
        "attempts_per_case": 1, "judge": False, "dimension_threshold": settings.eval_pass_threshold,
        "scoring": "按每题指定的过程和结果规则评分，两边使用同一客服模式并各建独立会话",
    }
    audit = {"protocol": protocol, "rule": selected, "development_cases": evidence[selected],
             "paired": paired, "errors": errors, "holdout_cases": [case.id for case in checks]}
    saved = save_validated(mode, version, candidate_rules, audit) if eligible else None
    report.update(protocol=protocol, rule=selected, evidence=evidence, eligible=eligible, version=saved)
    return report


def main():
    parser = argparse.ArgumentParser(description="客服策略的提出、留出验证、采用与回滚")
    commands = parser.add_subparsers(dest="action", required=True)
    for name, title in (("propose", "从客服失败报告中提出一条候选规则"),
                        ("validate", "调用当前客服模型，在独立用例上比较现行和候选策略"),
                        ("adopt", "将一个已验证版本用于客服"), ("rollback", "回到上个已采用版本"),
                        ("status", "查看当前使用的规则")):
        cmd = commands.add_parser(name, help=title)
        cmd.add_argument("--mode", choices=["single", "multi"],
                         default="multi" if settings.multi_agent_enabled else "single")
        if name in ("propose", "validate"):
            cmd.add_argument("--report", type=Path, required=True, help="run_eval 生成的开发集 JSON 报告")
        if name == "validate":
            cmd.add_argument("--holdout", type=Path, default=DEFAULT_HOLDOUT, help="独立验证工单集")
            cmd.add_argument("--output", type=Path, help="写出逐题两侧报告")
        if name == "rollback":
            cmd.add_argument("version", type=int, nargs="?", help="要撤回的当前版本号，避免覆盖他人的操作")
        if name == "adopt":
            cmd.add_argument("version", type=int, help="验证报告中生成的版本号")
    args = parser.parse_args()
    try:
        if args.action == "adopt":
            switch_policy(args.mode, args.version)
        elif args.action == "rollback":
            expected = args.version if args.version is not None else current_policy(args.mode)[0]
            switch_policy(args.mode, None, rollback_from=expected)
        base = current_policy(args.mode)
        info = {"mode": args.mode, "active_version": base[0], "active_rules": list(base[1])}
        if args.action in ("propose", "validate"):
            rows = read_development(args.report, args.mode, base)
            selected, evidence = propose(rows, base[1], settings.eval_pass_threshold)
            info.update(rule=selected, text=RULES.get(selected), evidence=evidence)
            if args.action == "validate":
                if args.output and args.output.resolve() in {args.report.resolve(), args.holdout.resolve()}:
                    raise ValueError("请另选输出路径，保留开发报告和留出工单")
                if selected:
                    info = validate(rows, args.mode, base, selected, evidence, args.holdout)
                else:
                    info.update(eligible=False, version=None, reason="开发报告没有支持新规则的失败记录")
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(info, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
