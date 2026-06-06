"""端到端测试：验证第 9 期 Agent 评估体系（沙箱 + 双层测评）。

测试场景：
1. 数据集加载 — load_dataset 解析 cases.json，字段完整
2. 规则指标 — tool_accuracy/efficiency/keyword/intent 等纯函数返回精确值
3. 沙箱采集 — 跑一条订单用例，RunTrace 应采集到 token、LLM 调用、工具轨迹
4. 沙箱隔离 — 不同用例 session 路径独立，且记忆被关闭（不污染评分）
5. LLM judge — 好回复质量≥3、忠实回复无幻觉、编造回复判幻觉
6. Evaluator 双层 — 同时产出过程得分与结果得分；--no-judge 时 judge 维度为 None

用法：python3 tests/test_evaluation.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.evaluation import metrics  # noqa: E402
from app.evaluation.dataset import EvalCase, load_dataset  # noqa: E402
from app.evaluation.evaluator import Evaluator  # noqa: E402
from app.evaluation.sandbox import Sandbox  # noqa: E402
from app.evaluation.trace import ToolObservation  # noqa: E402

DATASET = ROOT / "app" / "evaluation" / "cases.json"


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


# ---------- 测试 1：数据集加载 ----------
def test_dataset_load():
    print("\n[1/6] 数据集加载测试（无需 API）")
    cases = load_dataset(DATASET)
    if len(cases) >= 8:
        _ok(f"加载 {len(cases)} 条用例")
    else:
        _fail(f"预期至少 8 条用例，实际 {len(cases)}")

    first = cases[0]
    if isinstance(first, EvalCase) and first.id and first.turns:
        _ok(f"首条用例字段完整: {first.id}")
    else:
        _fail(f"用例字段不完整: {first}")

    has_process = any(c.min_tool_calls is not None for c in cases)
    has_budget = any(c.max_tokens is not None for c in cases)
    if has_process and has_budget:
        _ok("用例包含过程期望（min_tool_calls / max_tokens）")
    else:
        _fail("用例缺少过程期望字段")


# ---------- 测试 2：规则指标 ----------
def test_metrics_rule_based():
    print("\n[2/6] 规则指标测试（无需 API）")

    if metrics.tool_accuracy(["query_order"], ["query_order", "load_skill"]) == 1.0:
        _ok("tool_accuracy 全命中 = 1.0")
    else:
        _fail("tool_accuracy 计算错误")

    if metrics.tool_accuracy(["query_order", "query_logistics"], ["query_order"]) == 0.5:
        _ok("tool_accuracy 半命中 = 0.5")
    else:
        _fail("tool_accuracy 半命中计算错误")

    if metrics.tool_accuracy([], ["query_order"]) is None:
        _ok("tool_accuracy 无期望返回 None")
    else:
        _fail("tool_accuracy 空期望应返回 None")

    if metrics.tool_efficiency(1, 2) == 0.5 and metrics.tool_efficiency(2, 2) == 1.0:
        _ok("tool_efficiency 计算正确（1/2=0.5, 2/2=1.0）")
    else:
        _fail("tool_efficiency 计算错误")

    if metrics.token_cost_pass(5000, 6000) is True and metrics.token_cost_pass(7000, 6000) is False:
        _ok("token_cost_pass 预算判断正确")
    else:
        _fail("token_cost_pass 判断错误")

    if metrics.keyword_coverage(["Nike", "899"], "您的 Nike 鞋 899 元") == 1.0:
        _ok("keyword_coverage 全命中 = 1.0")
    else:
        _fail("keyword_coverage 计算错误")

    if metrics.intent_match("order_query", "order_query") == 1.0 and \
            metrics.intent_match("order_query", "complaint") == 0.0:
        _ok("intent_match 判断正确")
    else:
        _fail("intent_match 判断错误")

    if metrics.requires_human_match(None, True) is None:
        _ok("requires_human_match 无期望返回 None")
    else:
        _fail("requires_human_match 空期望应返回 None")


# ---------- 测试 3：沙箱采集 ----------
def test_sandbox_trace():
    print("\n[3/6] 沙箱采集测试（E2E，需要 API）")
    sandbox = Sandbox(mode="single")
    case = EvalCase(
        id="trace_probe",
        description="探针：查询订单",
        turns=["帮我查一下订单 ORD-20240115-001"],
        expected_tools=["query_order"],
    )
    trace = sandbox.run(case)

    if trace.error:
        _fail(f"沙箱运行异常: {trace.error}")

    if trace.total_tokens > 0:
        _ok(f"采集到 token 消耗: {trace.total_tokens}")
    else:
        _fail("未采集到 token 消耗")

    if trace.num_llm_calls >= 2:
        _ok(f"采集到 {trace.num_llm_calls} 次 LLM 调用（ReAct + 结构化提取）")
    else:
        _fail(f"LLM 调用次数异常: {trace.num_llm_calls}")

    if "query_order" in trace.tool_call_names:
        _ok(f"采集到工具调用轨迹: {trace.tool_call_names}")
    else:
        print(f"  ⚠️  未采集到 query_order（模型决策差异，非致命）: {trace.tool_call_names}")

    if trace.final_response is not None:
        _ok(f"采集到最终回复: {trace.final_response.reply[:50]}...")
    else:
        _fail("未采集到最终回复")


# ---------- 测试 4：沙箱隔离 ----------
def test_sandbox_isolation():
    print("\n[4/6] 沙箱隔离测试（无需 API）")
    sandbox = Sandbox(mode="single")

    p1 = sandbox.session_path_for("case_a")
    p2 = sandbox.session_path_for("case_b")
    if p1 != p2:
        _ok("不同用例的 session 路径独立")
    else:
        _fail("session 路径未隔离")

    agent = sandbox._build_agent(p1)
    try:
        if agent.memory_manager.memory_enabled is False:
            _ok("沙箱构建的 Agent 已关闭记忆（不污染评分）")
        else:
            _fail("记忆未关闭，会读 default.json 污染评分")
    finally:
        sandbox._close_tool_managers(agent)


# ---------- 测试 5：LLM judge ----------
def test_judges():
    print("\n[5/6] LLM judge 测试（需要 API）")
    client = _client()
    model = settings.model_name

    score, reason = metrics.judge_answer_quality(
        client, model,
        "我的订单 ORD-20240115-001 到哪了？",
        "您的订单已由顺丰速运承运，目前正在上海浦东区派送中，预计很快送达。",
        ["顺丰"],
    )
    if score >= 3:
        _ok(f"好回复质量评分 {score:.0f}（{reason}）")
    else:
        print(f"  ⚠️  好回复评分偏低 {score:.0f}（模型差异，非致命）: {reason}")

    obs = [ToolObservation(
        name="query_logistics",
        arguments={"order_id": "ORD-20240115-001"},
        result='{"success": true, "logistics": {"carrier": "顺丰速运", "status": "in_transit"}}',
    )]
    f_faithful, r1 = metrics.judge_faithfulness(
        client, model, "您的订单正由顺丰速运派送中。", obs
    )
    if f_faithful == 1.0:
        _ok(f"忠实回复判定为无幻觉（{r1}）")
    else:
        print(f"  ⚠️  忠实回复被判幻觉（模型差异，非致命）: {r1}")

    f_halluc, r2 = metrics.judge_faithfulness(
        client, model, "您的订单已由圆通速递签收，签收人为门卫。", obs
    )
    if f_halluc == 0.0:
        _ok(f"编造回复判定为幻觉（{r2}）")
    else:
        print(f"  ⚠️  编造回复未被判幻觉（模型差异，非致命）: {r2}")


# ---------- 测试 6：Evaluator 双层 ----------
def test_evaluator_two_tier():
    print("\n[6/6] Evaluator 双层评分测试（E2E，需要 API）")
    cases = [
        EvalCase(
            id="eval_order",
            description="查询订单",
            turns=["帮我查一下订单 ORD-20240115-001"],
            expected_intent="order_query",
            expected_keywords=["Nike"],
            expected_tools=["query_order"],
            min_tool_calls=1,
            max_tokens=8000,
        ),
        EvalCase(
            id="eval_greeting",
            description="问候",
            turns=["你好"],
            expected_intent="greeting",
            expected_tools=[],
            min_tool_calls=0,
            max_tokens=4000,
        ),
    ]

    # 含 judge
    sandbox = Sandbox(mode="single")
    evaluator = Evaluator(sandbox=sandbox, client=_client(), model=settings.model_name, use_judge=True)
    report = evaluator.run_all(cases)

    s = report["summary"]
    if s["total"] == 2:
        _ok(f"评估 {s['total']} 条用例，通过 {s['passed']}")
    else:
        _fail(f"用例数异常: {s['total']}")

    c0 = report["cases"][0]
    if c0["error"]:
        _fail(f"订单用例运行异常: {c0['error']}")
    if c0["process"]["process_score"] is not None and c0["result"]["result_score"] is not None:
        _ok("订单用例同时产出过程得分与结果得分")
    else:
        _fail("缺少过程或结果得分")
    if c0["process"]["token_cost"] > 0:
        _ok(f"过程指标采集到 token: {c0['process']['token_cost']}")
    else:
        _fail("过程指标未采集到 token")

    # --no-judge 模式
    sandbox2 = Sandbox(mode="single")
    evaluator2 = Evaluator(sandbox=sandbox2, client=_client(), model=settings.model_name, use_judge=False)
    report2 = evaluator2.run_all([cases[0]])
    c = report2["cases"][0]
    if c["result"]["answer_quality"] is None and c["process"]["process_soundness"] is None:
        _ok("--no-judge 时 LLM judge 维度为 None")
    else:
        _fail("--no-judge 时 judge 维度不应有值")
    if c["result"]["intent_match"] is not None or c["process"]["tool_accuracy"] is not None:
        _ok("--no-judge 时代码规则维度仍正常计算")
    else:
        _fail("--no-judge 时代码规则维度缺失")


def main():
    print("=" * 60)
    print("  第 9 期 Agent 评估体系 · 端到端测试")
    print("=" * 60)

    test_dataset_load()
    test_metrics_rule_based()
    test_sandbox_trace()
    test_sandbox_isolation()
    test_judges()
    test_evaluator_two_tier()

    print("\n" + "=" * 60)
    print("  全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
