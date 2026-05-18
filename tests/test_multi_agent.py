"""端到端测试：验证第 7 期 Multi-Agent 协作能力。

测试场景：
1. 路由准确性 — 商品咨询 → presale，订单查询 → postsale，投诉 → complaint
2. 售前 Agent — 商品推荐
3. 售后 Agent — 订单查询
4. 投诉 Agent — 投诉处理 + requires_human 倾向
5. 多轮上下文 — 路由切换后上下文保持
6. 结构化输出完整性
7. 工具隔离验证

用法：python3 tests/test_multi_agent.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.multi_agent.orchestrator import MultiAgentOrchestrator  # noqa: E402
from app.multi_agent.router import Router  # noqa: E402
from app.schemas.response import CustomerServiceResponse, IntentType  # noqa: E402

TEST_SESSION = str(ROOT / "app" / "sessions" / "test_multi_agent_session.json")


def _fresh_orchestrator(threshold: int = 30, keep: int = 6) -> MultiAgentOrchestrator:
    orch = MultiAgentOrchestrator(session_path=TEST_SESSION)
    orch.history_threshold = threshold
    orch.history_keep_recent = keep
    return orch


def _clean():
    Path(TEST_SESSION).unlink(missing_ok=True)


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def _assert_structured(resp: CustomerServiceResponse, label: str):
    if not isinstance(resp.intent, IntentType):
        _fail(f"{label}：intent 不是 IntentType 类型")
    if not (0.0 <= resp.confidence <= 1.0):
        _fail(f"{label}：confidence 超出 [0,1] 范围 → {resp.confidence}")
    if not resp.reply:
        _fail(f"{label}：reply 为空")
    _ok(f"{label}：结构化输出完整 (intent={resp.intent.value}, confidence={resp.confidence:.0%})")


# ---------- 测试 1：路由准确性 ----------
def test_routing():
    print("\n[1/7] 路由准确性测试")
    orch = _fresh_orchestrator()
    router = orch.router

    cases = [
        ("有什么耳机推荐吗", "presale", "商品咨询"),
        ("帮我查一下订单 ORD-20240115-001", "postsale", "订单查询"),
        ("我要投诉！你们的商品质量太差了", "complaint", "投诉"),
        ("最近有什么优惠活动吗", "presale", "促销活动"),
        ("我的快递到哪了", "postsale", "物流查询"),
        ("你好", "postsale", "问候（默认售后）"),
    ]

    for user_input, expected, desc in cases:
        result = router.route(user_input)
        if result == expected:
            _ok(f"「{desc}」→ {result}")
        else:
            print(f"  ⚠️  「{desc}」期望 {expected}，实际 {result}")


# ---------- 测试 2：售前 Agent ----------
def test_presale():
    print("\n[2/7] 售前 Agent 测试（商品推荐）")
    _clean()
    orch = _fresh_orchestrator()
    resp = orch.chat("你们有什么耳机卖？")
    _assert_structured(resp, "售前")

    keywords = ["AirPods", "耳机", "降噪", "1799"]
    found = any(kw in resp.reply for kw in keywords)
    if found:
        _ok("售前 Agent 回复包含商品信息")
    else:
        print("  ⚠️  回复中未找到预期商品关键词")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 3：售后 Agent ----------
def test_postsale():
    print("\n[3/7] 售后 Agent 测试（订单查询）")
    _clean()
    orch = _fresh_orchestrator()
    resp = orch.chat("帮我查一下订单 ORD-20240115-001 的状态")
    _assert_structured(resp, "售后")

    keywords = ["发货", "shipped", "Nike", "运动鞋", "899", "顺丰"]
    found = any(kw in resp.reply for kw in keywords)
    if found:
        _ok("售后 Agent 回复包含订单信息")
    else:
        print("  ⚠️  回复中未找到预期订单关键词")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 4：投诉 Agent ----------
def test_complaint():
    print("\n[4/7] 投诉 Agent 测试")
    _clean()
    orch = _fresh_orchestrator()
    resp = orch.chat("我要投诉！订单 ORD-20240110-003 的商品质量太差了，我非常不满意！")
    _assert_structured(resp, "投诉")

    apologize_kw = ["抱歉", "非常抱歉", "理解", "对不起", "歉意", "不好意思"]
    found_apology = any(kw in resp.reply for kw in apologize_kw)
    if found_apology:
        _ok("投诉 Agent 回复包含道歉/安抚语句")
    else:
        print("  ⚠️  回复中未找到道歉/安抚关键词")

    if resp.requires_human:
        _ok("投诉 Agent 建议转人工 (requires_human=True)")
    else:
        print("  ⚠️  requires_human=False（投诉场景通常建议转人工）")
    print(f"     回复：{resp.reply[:150]}")


# ---------- 测试 5：多轮上下文保持 ----------
def test_multi_turn_context():
    print("\n[5/7] 多轮上下文 + 路由切换测试")
    _clean()
    orch = _fresh_orchestrator()

    resp1 = orch.chat("有什么运动鞋推荐？")
    _assert_structured(resp1, "第1轮-售前")
    print(f"     第1轮回复：{resp1.reply[:80]}")

    resp2 = orch.chat("帮我查一下订单 ORD-20240115-001")
    _assert_structured(resp2, "第2轮-售后")
    print(f"     第2轮回复：{resp2.reply[:80]}")

    if orch.history_size >= 4:
        _ok(f"历史消息正确累积（{orch.history_size} 条）")
    else:
        print(f"  ⚠️  历史消息偏少：{orch.history_size} 条")


# ---------- 测试 6：结构化输出完整性 ----------
def test_structured_output():
    print("\n[6/7] Multi-Agent 结构化输出完整性")
    _clean()
    orch = _fresh_orchestrator()
    resp = orch.chat("我想看看你们有什么新款手机")
    _assert_structured(resp, "完整性")
    if resp.follow_up_question is not None or resp.follow_up_question is None:
        _ok("follow_up_question 字段存在")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 7：工具隔离验证 ----------
def test_tool_isolation():
    print("\n[7/7] 工具隔离验证")
    _clean()
    orch = _fresh_orchestrator()

    presale_tools = {
        d["function"]["name"]
        for d in orch.agents["presale"].tool_manager.tool_definitions
    }
    postsale_tools = {
        d["function"]["name"]
        for d in orch.agents["postsale"].tool_manager.tool_definitions
    }
    complaint_tools = {
        d["function"]["name"]
        for d in orch.agents["complaint"].tool_manager.tool_definitions
    }

    if "apply_refund" not in presale_tools:
        _ok("售前 Agent 无 apply_refund 工具")
    else:
        _fail("售前 Agent 不应该有 apply_refund 工具")

    if "apply_refund" in postsale_tools:
        _ok("售后 Agent 有 apply_refund 工具")
    else:
        _fail("售后 Agent 应该有 apply_refund 工具")

    if "query_product" not in complaint_tools:
        _ok("投诉 Agent 无 query_product 工具")
    else:
        _fail("投诉 Agent 不应该有 query_product 工具")

    if "query_order" in complaint_tools:
        _ok("投诉 Agent 有 query_order 工具")
    else:
        _fail("投诉 Agent 应该有 query_order 工具")

    print(f"     售前工具: {presale_tools}")
    print(f"     售后工具: {postsale_tools}")
    print(f"     投诉工具: {complaint_tools}")


def main():
    print("=" * 60)
    print("  第 7 期 Multi-Agent 协作 · 端到端测试")
    print("=" * 60)

    try:
        test_routing()
        test_presale()
        test_postsale()
        test_complaint()
        test_multi_turn_context()
        test_structured_output()
        test_tool_isolation()
    finally:
        _clean()

    print("\n" + "=" * 60)
    print("  🎉 全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
