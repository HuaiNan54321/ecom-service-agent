"""重放电商客服用例。此入口调用已配置的真实模型，免费离线练习用 examples.ch20.demo。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.evaluation.dataset import load_dataset  # noqa: E402
from app.evaluation.evaluator import Evaluator, run_comparison  # noqa: E402
from app.evaluation.sandbox import Sandbox  # noqa: E402


def _fmt(value) -> str:
    """格式化评分单元格：None→"-"，bool→✓/✗，float→百分比。"""
    if value is None:
        return "  - "
    if isinstance(value, bool):
        return "  ✓ " if value else "  ✗ "
    return f"{value * 100:4.0f}%"


def _print_report(report: dict) -> None:
    cases = report["cases"]

    print("\n" + "=" * 78)
    print("  过程指标（工具准确率 / 调用效率 / token达标 / 过程合理性）")
    print("=" * 78)
    print(f"  {'用例':<22}{'工具准确':>8}{'调用效率':>8}{'token':>8}{'token达标':>9}{'过程合理':>8}")
    for c in cases:
        p = c["process"]
        print(
            f"  {c['case_id']:<22}"
            f"{_fmt(p['tool_accuracy']):>8}{_fmt(p['tool_efficiency']):>8}"
            f"{str(p['token_cost'] if p['token_cost'] is not None else '未知'):>8}"
            f"{_fmt(p['token_pass']):>9}{_fmt(p['process_soundness']):>8}"
        )

    print("\n" + "=" * 78)
    print("  结果指标（意图 / 关键信息完整性 / 转人工 / 回答质量 / 忠实度无幻觉）")
    print("=" * 78)
    print(f"  {'用例':<22}{'意图':>8}{'完整性':>8}{'转人工':>8}{'回答质量':>8}{'无幻觉':>8}")
    for c in cases:
        r = c["result"]
        flag = "" if c["passed"] else "  ❌"
        if c["error"]:
            print(f"  {c['case_id']:<22}  运行/评分异常: {c['error']}")
            continue
        if c["judge_review"]:
            flag = "  待复核：" + "、".join(c["judge_review"])
        print(
            f"  {c['case_id']:<22}"
            f"{_fmt(r['intent_match']):>8}{_fmt(r['keyword_coverage']):>8}"
            f"{_fmt(r['requires_human_match']):>8}{_fmt(r['answer_quality']):>8}"
            f"{_fmt(r['faithfulness']):>8}{flag}"
        )

    s = report["summary"]
    print("\n" + "=" * 78)
    print("  汇总")
    print("=" * 78)
    print(f"  通过率        : {s['passed']}/{s['total']}  ({s['pass_rate'] * 100:.0f}%)")
    if s["judge_review_cases"]:
        print(f"  含待复核裁判项: {s['judge_review_cases']} 题（保留在分母）")
    print(f"  平均过程得分  : {_fmt(s['avg_process_score']).strip()}")
    print(f"  平均结果得分  : {_fmt(s['avg_result_score']).strip()}")
    if s["total_tokens"] is None:
        print(f"  聊天模型用量未知，完整记录 {s['token_cases_observed']}/{s['total']} 题")
    else:
        print(f"  聊天模型总 token : {s['total_tokens']}（平均每用例 {s['avg_tokens_per_case']:.0f}）")


def main():
    parser = argparse.ArgumentParser(description="运行 Agent 评估体系")
    parser.add_argument(
        "--dataset", default=settings.eval_dataset_path,
        help=f"测试集 JSON 路径（默认: {settings.eval_dataset_path}）",
    )
    parser.add_argument(
        "--mode", choices=["single", "multi"],
        default="multi" if settings.multi_agent_enabled else "single",
        help="被测 Agent 模式（默认据 multi_agent_enabled）",
    )
    judge = parser.add_mutually_exclusive_group()
    judge.add_argument(
        "--judge", dest="judge", action="store_true", default=None,
        help="启用 LLM-as-judge（默认开）",
    )
    judge.add_argument(
        "--no-judge", dest="judge", action="store_false",
        help="只跑代码规则指标，不调 LLM judge（快、便宜）",
    )
    parser.add_argument("--compare-bare", action="store_true",
                        help="同模型无工具基线与选定 Agent 逐题对照，仅用双方共有的结果规则计算 pass@1")
    parser.add_argument("--output", default=None, help="将完整报告写入 JSON 文件")
    args = parser.parse_args()
    if args.compare_bare and args.judge is True:
        parser.error("配对评测使用预先指定的规则裁判，请移除 --judge")
    use_judge = False if args.compare_bare else (settings.eval_use_judge if args.judge is None else args.judge)

    dataset_path = ROOT / args.dataset if not Path(args.dataset).is_absolute() else Path(args.dataset)

    print("=" * 78)
    print("  并夕夕 · Agent 评估体系")
    print(f"  模式      : {args.mode}")
    print(f"  数据集    : {dataset_path}")
    print(f"  LLM judge : {'开启' if use_judge else '关闭（仅规则）'}")
    print(f"  裁判模型  : {settings.model_name}")
    print("=" * 78)

    print("\n[1/3] 加载测试集...")
    if not dataset_path.exists():
        print(f"❌ 测试集不存在: {dataset_path}")
        sys.exit(1)
    cases = load_dataset(dataset_path)
    if not cases:
        print("❌ 测试集为空")
        sys.exit(1)
    print(f"   共 {len(cases)} 条用例")

    print(f"\n[2/3] 在沙箱中重跑测试集（{args.mode} 模式）...")
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    sandbox = Sandbox(mode=args.mode)
    evaluator = Evaluator(
        sandbox=sandbox,
        client=client,
        model=settings.model_name,
        use_judge=use_judge,
        pass_threshold=settings.eval_pass_threshold,
    )
    if args.compare_bare:
        baseline = Evaluator(Sandbox(mode="bare"), client, settings.model_name,
                             use_judge=False, pass_threshold=settings.eval_pass_threshold)
        report = run_comparison(cases, baseline, evaluator)
        report["protocol"] = {
            "model": settings.model_name, "temperature": settings.temperature,
            "baseline_mode": "bare", "candidate_mode": args.mode,
            "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            "result_rules": ["intent_match", "keyword_coverage", "requires_human_match"],
            "dimension_threshold": settings.eval_pass_threshold, "attempts_per_case": 1,
            "token_scope": "客服对话模型用量，不含检索嵌入；供应商未返回完整用量时汇总为 null",
        }
        print("\n[3/3] 每题首次尝试的答复通过率与过程成本")
        for key, name in [("baseline", "裸模型"), ("candidate", args.mode)]:
            s = report[key]["summary"]
            tokens = s["avg_tokens_per_case"]
            token_text = f"{tokens:.1f}" if tokens is not None else f"未知（完整记录 {s['token_cases_observed']}/{s['total']} 题）"
            print(f"  {name}: {s['passed']}/{s['total']}，pass@1={s['pass_at_1']:.1%}，"
                  f"平均工具调用 {s['avg_tool_calls']:.2f} 次，平均聊天 token {token_text}，"
                  f"平均用时 {s['avg_elapsed_ms']:.0f} ms，异常 {s['errors']} 题")
        print(f"  通过率变化 {report['paired']['delta_pp']:+.1f} 个百分点")
        print(f"  新通过 {report['paired']['improved']}，退步 {report['paired']['regressed']}")
    else:
        report = evaluator.run_all(cases)
        print("\n[3/3] 生成评估报告...")
        _print_report(report)

    if args.output:
        out_path = ROOT / args.output if not Path(args.output).is_absolute() else Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n   报告已写入: {out_path}")

    print("\n🎉 评估完成。")


if __name__ == "__main__":
    main()
