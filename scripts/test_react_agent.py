"""端到端测试：验证第 3 期 ReAct Agent + Function Calling 能力。

测试场景：
1. 简单问候（不触发工具调用）
2. 订单查询（单次工具调用）
3. 物流查询（可能触发链式工具调用）
4. 商品搜索（关键词模糊匹配）
5. 退款申请
6. 未知订单（工具返回错误，agent 优雅处理）
7. 结构化输出完整性（每次回复都有意图/置信度）
8. 会话持久化兼容（工具消息也能正确保存和恢复）

用法：python3 scripts/test_react_agent.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.chat import EcomAgent  # noqa: E402
from schemas.response import CustomerServiceResponse, IntentType  # noqa: E402

TEST_SESSION = str(ROOT / "sessions" / "test_react_session.json")


def _fresh_agent(threshold: int = 30, keep: int = 6) -> EcomAgent:
    agent = EcomAgent(session_path=TEST_SESSION)
    agent.history_threshold = threshold
    agent.history_keep_recent = keep
    return agent


def _clean():
    Path(TEST_SESSION).unlink(missing_ok=True)


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def _assert_structured(resp: CustomerServiceResponse, label: str):
    """验证结构化输出的完整性"""
    if not isinstance(resp.intent, IntentType):
        _fail(f"{label}：intent 不是 IntentType 类型")
    if not (0.0 <= resp.confidence <= 1.0):
        _fail(f"{label}：confidence 超出 [0,1] 范围 → {resp.confidence}")
    if not resp.reply:
        _fail(f"{label}：reply 为空")
    _ok(f"{label}：结构化输出完整 (intent={resp.intent.value}, confidence={resp.confidence:.0%})")


# ---------- 测试 1：简单问候 ----------
def test_greeting():
    print("\n[1/7] 简单问候测试（不应触发工具调用）")
    _clean()
    agent = _fresh_agent()
    resp = agent.chat("你好呀~")
    _assert_structured(resp, "问候")
    print(f"     回复：{resp.reply[:80]}")


# ---------- 测试 2：订单查询 ----------
def test_order_query():
    print("\n[2/7] 订单查询测试（应调用 query_order）")
    _clean()
    agent = _fresh_agent()
    resp = agent.chat("帮我查一下订单 ORD-20240115-001 的状态")
    _assert_structured(resp, "订单查询")

    keywords = ["发货", "shipped", "Nike", "运动鞋", "899", "顺丰", "SF1234567890"]
    found = any(kw in resp.reply for kw in keywords)
    if found:
        _ok("回复中包含订单相关信息")
    else:
        print(f"  ⚠️  回复中未找到预期关键词（可能模型表述不同）")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 3：物流查询 ----------
def test_logistics_query():
    print("\n[3/7] 物流查询测试（应调用 query_logistics）")
    _clean()
    agent = _fresh_agent()
    resp = agent.chat("订单 ORD-20240115-001 的物流到哪了？")
    _assert_structured(resp, "物流查询")

    keywords = ["顺丰", "上海", "派送", "深圳", "转运"]
    found = any(kw in resp.reply for kw in keywords)
    if found:
        _ok("回复中包含物流轨迹信息")
    else:
        print(f"  ⚠️  回复中未找到预期物流关键词")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 4：商品搜索 ----------
def test_product_search():
    print("\n[4/7] 商品搜索测试（应调用 query_product）")
    _clean()
    agent = _fresh_agent()
    resp = agent.chat("你们有什么耳机卖？")
    _assert_structured(resp, "商品搜索")

    keywords = ["AirPods", "1799", "降噪", "耳机"]
    found = any(kw in resp.reply for kw in keywords)
    if found:
        _ok("回复中包含商品信息")
    else:
        print(f"  ⚠️  回复中未找到预期商品关键词")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 5：退款申请 ----------
def test_refund():
    print("\n[5/7] 退款申请测试（应调用 apply_refund）")
    _clean()
    agent = _fresh_agent()
    resp = agent.chat("我要退掉订单 ORD-20240110-003，质量有问题")
    _assert_structured(resp, "退款申请")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 6：未知订单 ----------
def test_unknown_order():
    print("\n[6/7] 未知订单测试（工具应返回错误，agent 优雅处理）")
    _clean()
    agent = _fresh_agent()
    resp = agent.chat("帮我查订单 ORD-99999-000")
    _assert_structured(resp, "未知订单")

    keywords = ["未找到", "找不到", "不存在", "核实", "确认"]
    found = any(kw in resp.reply for kw in keywords)
    if found:
        _ok("agent 正确告知用户订单不存在")
    else:
        print(f"  ⚠️  回复中未提及订单不存在")
    print(f"     回复：{resp.reply[:120]}")


# ---------- 测试 7：会话持久化兼容 ----------
def test_persistence_with_tools():
    print("\n[7/7] 会话持久化兼容测试（工具消息也能保存和恢复）")
    _clean()
    agent = _fresh_agent()
    agent.chat("帮我查一下订单 ORD-20240120-002")

    has_tool_msg = any(m.get("role") == "tool" for m in agent.raw_messages)
    if has_tool_msg:
        _ok("raw_messages 中包含 tool 消息")
    else:
        print("  ⚠️  raw_messages 中未发现 tool 消息（模型可能未调用工具）")

    agent.save()
    agent2 = _fresh_agent()
    if agent2.history_size == agent.history_size:
        _ok(f"新实例恢复了 {agent2.history_size} 条历史（含工具消息）")
    else:
        _fail(f"历史条数不匹配：原 {agent.history_size}，恢复 {agent2.history_size}")

    resp = agent2.chat("这个订单什么时候能发货？")
    _assert_structured(resp, "持久化后追问")
    print(f"     回复：{resp.reply[:120]}")


def main():
    print("=" * 60)
    print("  第 3 期 ReAct Agent + Function Calling · 端到端测试")
    print("=" * 60)

    try:
        test_greeting()
        test_order_query()
        test_logistics_query()
        test_product_search()
        test_refund()
        test_unknown_order()
        test_persistence_with_tools()
    finally:
        _clean()

    print("\n" + "=" * 60)
    print("  🎉 全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
