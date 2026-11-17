"""评估执行器：编排 沙箱跑用例 → 双层评分 → 聚合报告（第9期）。

Evaluator 自己不碰 Agent，只负责：让 Sandbox 跑出 RunTrace，再用 metrics 对轨迹
打分（过程层 + 结果层，代码规则恒算、LLM judge 受 use_judge 控制），最后聚合。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openai import OpenAI

from app.evaluation import metrics
from app.evaluation.dataset import EvalCase
from app.evaluation.sandbox import Sandbox


@dataclass
class EvalResult:
    """单条用例的评估结果。所有评分维度 None 表示该用例未指定（不计入聚合）。"""

    case_id: str
    description: str

    # ---------- 过程指标 ----------
    tool_accuracy: float | None = None
    tool_efficiency: float | None = None
    token_cost: int | None = None
    token_pass: bool | None = None
    process_soundness: float | None = None  # judge 1-5 归一化到 0-1
    route_match: float | None = None

    # ---------- 结果指标 ----------
    intent_match: float | None = None
    keyword_coverage: float | None = None
    requires_human_match: float | None = None
    answer_quality: float | None = None  # judge 1-5 归一化到 0-1
    faithfulness: float | None = None  # 1.0 忠实 / 0.0 幻觉

    # ---------- 汇总 ----------
    process_score: float | None = None
    result_score: float | None = None
    passed: bool = False

    trace: dict = field(default_factory=dict)  # RunTrace 精简快照
    judge_reasons: dict = field(default_factory=dict)  # judge 文字理由
    judge_review: list[str] = field(default_factory=list)  # 需要人工复核的已启用裁判项
    judge_not_applicable: list[str] = field(default_factory=list)  # 该题没有可评分对象的裁判项
    error: str | None = None


def _avg(values: list[float | None]) -> float | None:
    """对非 None 项求均值；全为 None 返回 None。"""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


class Evaluator:
    """评估器：对一批用例执行沙箱运行 + 双层评分 + 聚合。"""

    def __init__(
        self,
        sandbox: Sandbox,
        client: OpenAI,
        model: str,
        use_judge: bool = True,
        pass_threshold: float = 0.6,
    ):
        self.sandbox = sandbox
        self.client = client
        self.model = model
        self.use_judge = use_judge
        self.pass_threshold = pass_threshold

    def run_case(self, case: EvalCase) -> EvalResult:
        trace = self.sandbox.run(case)
        res = EvalResult(case_id=case.id, description=case.description,
                         trace=trace.to_dict(), token_cost=trace.total_tokens)

        if case.source_id:
            res.trace["source_id"] = case.source_id

        if trace.error or trace.final_response is None:
            res.error = trace.error or "运行结束后没有得到客服答复"
            return res

        try:
            resp = trace.final_response
            reply = resp.reply if resp else ""
            actual_intent = resp.intent.value if resp else ""
            actual_human = resp.requires_human if resp else False
            called = trace.tool_call_names

            # ---------- 过程指标（代码规则）----------
            res.tool_accuracy = metrics.tool_accuracy(case.expected_tools, called)
            res.tool_efficiency = metrics.tool_efficiency(case.min_tool_calls, trace.num_tool_calls)
            res.token_pass = metrics.token_cost_pass(trace.total_tokens, case.max_tokens)
            res.route_match = metrics.route_match(case.expected_route, trace.route)

            # ---------- 结果指标（代码规则）----------
            res.intent_match = metrics.intent_match(case.expected_intent, actual_intent)
            res.keyword_coverage = metrics.keyword_coverage(case.expected_keywords, reply)
            res.requires_human_match = metrics.requires_human_match(
                case.expected_requires_human, actual_human
            )

            # ---------- LLM judge ----------
            if self.use_judge:
                user_input = "\n".join(case.turns)
                q_score, q_reason = metrics.judge_answer_quality(
                    self.client, self.model, user_input, reply, case.expected_keywords
                )
                res.answer_quality = q_score / 5.0 if q_score is not None else None
                res.judge_reasons["answer_quality"] = q_reason

                if case.expected_intent == "greeting" and not case.expected_tools and not called:
                    claim, why = metrics.judge_greeting_claim(self.client, self.model, reply)
                    f_score = None
                    if claim == 0.0:
                        res.judge_not_applicable.append("faithfulness")
                        f_reason = f"不适用：回复仅为问候，没有业务断言。{why}"
                    elif claim == 1.0:
                        f_reason = f"待复核：回复含有业务断言，但没有工具证据。{why}"
                    else:
                        f_reason = why
                else:
                    f_score, f_reason = metrics.judge_faithfulness(
                        self.client, self.model, reply, trace.tool_observations
                    )
                res.faithfulness = f_score
                res.judge_reasons["faithfulness"] = f_reason

                p_score, p_reason = metrics.judge_process_soundness(
                    self.client, self.model, user_input, called
                )
                res.process_soundness = p_score / 5.0 if p_score is not None else None
                res.judge_reasons["process_soundness"] = p_reason
                res.judge_review = [name for name in res.judge_reasons
                                    if getattr(res, name) is None and name not in res.judge_not_applicable]

            # ---------- 汇总 ----------
            res.process_score = _avg([
                res.tool_accuracy, res.tool_efficiency,
                res.process_soundness, res.route_match,
            ])
            res.result_score = _avg([
                res.intent_match, res.keyword_coverage,
                res.requires_human_match, res.answer_quality, res.faithfulness,
            ])
            res.passed = self._decide_pass(res) and (case.max_tokens is None or res.token_pass is True)

        except Exception as e:  # noqa: BLE001 —— 评分异常隔离到单条用例
            res.error = f"评分异常 {type(e).__name__}: {e}"

        return res

    def run_all(self, cases: list[EvalCase]) -> dict:
        results = [self.run_case(c) for c in cases]
        return self._aggregate(results)

    def _decide_pass(self, res: EvalResult) -> bool:
        """所有被指定的评分维度都 ≥ 阈值，且 token 不超预算，才算通过。"""
        if res.error or res.judge_review:
            return False
        if res.token_pass is False:
            return False
        dims = [
            res.tool_accuracy, res.tool_efficiency, res.process_soundness, res.route_match,
            res.intent_match, res.keyword_coverage, res.requires_human_match,
            res.answer_quality, res.faithfulness,
        ]
        present = [d for d in dims if d is not None]
        return all(d >= self.pass_threshold for d in present) if present else True

    def _aggregate(self, results: list[EvalResult]) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        tokens = [r.token_cost for r in results if r.token_cost is not None]
        total_tokens = sum(tokens) if len(tokens) == total else None
        summary = {
            "total": total,
            "passed": passed,
            "pass_rate": passed / total if total else 0.0,
            "avg_process_score": _avg([r.process_score for r in results]),
            "avg_result_score": _avg([r.result_score for r in results]),
            "total_tokens": total_tokens,
            "avg_tokens_per_case": total_tokens / total if total and total_tokens is not None else None,
            "token_cases_observed": len(tokens),
            "judge_review_cases": sum(bool(r.judge_review) for r in results),
        }
        return {
            "summary": summary,
            "cases": [self._result_to_dict(r) for r in results],
        }

    @staticmethod
    def _result_to_dict(r: EvalResult) -> dict:
        return {
            "case_id": r.case_id,
            "description": r.description,
            "passed": r.passed,
            "process": {
                "tool_accuracy": r.tool_accuracy,
                "tool_efficiency": r.tool_efficiency,
                "token_cost": r.token_cost,
                "token_pass": r.token_pass,
                "process_soundness": r.process_soundness,
                "route_match": r.route_match,
                "process_score": r.process_score,
            },
            "result": {
                "intent_match": r.intent_match,
                "keyword_coverage": r.keyword_coverage,
                "requires_human_match": r.requires_human_match,
                "answer_quality": r.answer_quality,
                "faithfulness": r.faithfulness,
                "result_score": r.result_score,
            },
            "judge_reasons": r.judge_reasons,
            "judge_review": r.judge_review,
            "judge_not_applicable": r.judge_not_applicable,
            "trace": r.trace,
            "error": r.error,
        }


def run_comparison(cases: list[EvalCase], baseline: Evaluator, candidate: Evaluator, *,
                   answer_only: bool = True) -> dict:
    """同题交替运行。无工具基线比较共用答复目标；客服策略对照保留所有已指定的规则。"""
    if baseline.use_judge or candidate.use_judge or baseline.pass_threshold != candidate.pass_threshold:
        raise ValueError("配对比较需要共用规则阈值，关闭额外模型裁判")
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("对照数据集应非空，且每道题的编号唯一")
    for case in cases:
        has_answer_check = bool(case.expected_intent or case.expected_keywords
                                or case.expected_requires_human is not None)
        has_process_check = bool(case.expected_tools or case.max_tokens is not None
                                 or case.min_tool_calls == 0
                                 or (case.expected_route and baseline.sandbox.mode == "multi"))
        if not case.turns or not (has_answer_check or (not answer_only and has_process_check)):
            raise ValueError(f"{case.id} 需要用户输入，并预先指定双方都可评分的验收条件")

    results = {"baseline": [], "candidate": []}
    sides = [("baseline", baseline), ("candidate", candidate)]
    for index, case in enumerate(cases):
        # 交替谁先运行，减少服务负载随时间变化带来的固定顺序偏差。
        for side, evaluator in (sides if index % 2 == 0 else reversed(sides)):
            row = evaluator.run_case(case)
            if answer_only:
                scores = [score for score, required in (
                    (row.intent_match, case.expected_intent is not None),
                    (row.keyword_coverage, bool(case.expected_keywords)),
                    (row.requires_human_match, case.expected_requires_human is not None),
                ) if required]
                row.passed = row.error is None and all(
                    score is not None and score >= evaluator.pass_threshold for score in scores
                )
            results[side].append(row)

    report = {"result_targets": {
        case.id: {key: value for key, value in (
            ("intent_match", case.expected_intent),
            ("keyword_coverage", case.expected_keywords or None),
            ("requires_human_match", case.expected_requires_human),
        ) if value is not None}
        for case in cases
    }}
    report["rule_case_counts"] = {
        rule: sum(rule in targets for targets in report["result_targets"].values())
        for rule in ("intent_match", "keyword_coverage", "requires_human_match")
    }
    for side, evaluator in sides:
        rows = results[side]
        group = evaluator._aggregate(rows)
        summary = group["summary"]
        summary.update({
            "pass_at_1": summary["pass_rate"],
            "errors": sum(row.error is not None for row in rows),
            "avg_tool_calls": _avg([row.trace["num_tool_calls"] for row in rows]),
            "avg_elapsed_ms": _avg([row.trace["elapsed_ms"] for row in rows]),
        })
        report[side] = group
    report["paired"] = {
        "improved": [a.case_id for a, b in zip(results["baseline"], results["candidate"])
                     if not a.passed and b.passed],
        "regressed": [a.case_id for a, b in zip(results["baseline"], results["candidate"])
                      if a.passed and not b.passed],
        "delta_pp": 100 * (report["candidate"]["summary"]["pass_at_1"]
                           - report["baseline"]["summary"]["pass_at_1"]),
    }
    return report
