"""端到端测试：验证第 2 期多轮对话管理能力。

测试场景：
1. 压缩触发：降低阈值后多轮对话触发 summary
2. 持久化：chat 后文件落盘，新实例能恢复
3. Reset：清空内存 + 删除文件
4. 损坏 JSON：降级为新会话不崩溃

用法：python3 scripts/test_conversation_management.py
"""

import json
import sys
from pathlib import Path

# 把项目根加入 sys.path，允许从 scripts/ 下直接运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.chat import EcomAgent  # noqa: E402
from agent.storage import load_session  # noqa: E402


TEST_SESSION = str(ROOT / "sessions" / "test_session.json")


def _fresh_agent(threshold: int = 20, keep: int = 6) -> EcomAgent:
    """构造测试用 Agent：指定 session 路径 + 可覆盖阈值"""
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


# ---------- 测试 1：压缩触发 ----------
def test_summary_triggered():
    print("\n[1/4] 压缩触发测试（threshold=4, keep=2）")
    _clean()
    agent = _fresh_agent(threshold=4, keep=2)

    prompts = [
        "你好，我的订单 A123456 还没发货，怎么回事？",
        "我下单两天了，明天要出差用",
        "那可以帮我催一下吗？我会员等级是金牌",
        "另外这个订单能不能改地址，寄到公司？",
    ]
    for i, p in enumerate(prompts, 1):
        resp = agent.chat(p)
        print(f"    第 {i} 轮：用户='{p[:20]}...' 意图={resp.intent}")

    if agent.summary is None:
        _fail("summary 未生成")
    _ok(f"summary 已生成，{len(agent.summary)} 字")
    print(f"     summary 内容预览：{agent.summary[:120]}...")

    if len(agent.raw_messages) > 4:
        _fail(f"raw_messages 未被截断，当前 {len(agent.raw_messages)} 条")
    _ok(f"raw_messages 已截断到 {len(agent.raw_messages)} 条（≤ keep*2+余量）")

    # 验证 summary 里确实保留了订单号这种关键事实
    if "A123456" not in agent.summary:
        print(f"  ⚠️  summary 中未检索到订单号 A123456（可能模型表述不同）")
    else:
        _ok("summary 正确保留了订单号 A123456")


# ---------- 测试 2：持久化 + 恢复 ----------
def test_persistence_and_recovery():
    print("\n[2/4] 持久化 + 恢复测试")
    _clean()
    agent = _fresh_agent()

    agent.chat("我的订单号是 B999888，想退货")
    agent.chat("商品有质量问题，收到就是坏的")

    # 文件应该存在
    if not Path(TEST_SESSION).exists():
        _fail("session.json 未生成")
    _ok("session.json 已落盘")

    raw = json.loads(Path(TEST_SESSION).read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        _fail(f"version 字段异常：{raw.get('version')}")
    if len(raw["messages"]) != 4:
        _fail(f"messages 条数预期 4，实际 {len(raw['messages'])}")
    _ok(f"文件格式正确（version={raw['version']}, messages={len(raw['messages'])}）")

    # 模拟重启：新 Agent 实例加载同一文件
    agent2 = _fresh_agent()
    if agent2.history_size != 4:
        _fail(f"恢复的历史条数不对，预期 4，实际 {agent2.history_size}")
    _ok(f"新实例恢复了 {agent2.history_size} 条历史")

    # 追问上下文，验证模型能接上
    resp = agent2.chat("我刚刚说的订单号是多少？")
    print(f"     模型回复：{resp.reply[:100]}")
    if "B999888" in resp.reply:
        _ok("模型能从恢复的历史中找回订单号")
    else:
        print("  ⚠️  模型回复中没提到订单号（可能表述不同或模型能力问题，不一定是 bug）")


# ---------- 测试 3：Reset ----------
def test_reset():
    print("\n[3/4] Reset 测试")
    _clean()
    agent = _fresh_agent()
    agent.chat("随便说一句话")
    if not Path(TEST_SESSION).exists():
        _fail("chat 后文件未生成")

    agent.reset()
    if Path(TEST_SESSION).exists():
        _fail("reset 后文件仍存在")
    if agent.raw_messages or agent.summary:
        _fail("reset 后内存状态未清空")
    _ok("reset 成功清空内存 + 删除文件")


# ---------- 测试 4：损坏 JSON 降级 ----------
def test_corrupted_json():
    print("\n[4/4] 损坏 JSON 降级测试")
    _clean()
    Path(TEST_SESSION).parent.mkdir(parents=True, exist_ok=True)
    Path(TEST_SESSION).write_text("{ this is not valid json", encoding="utf-8")

    # 不应崩溃
    try:
        agent = _fresh_agent()
    except Exception as e:
        _fail(f"加载损坏 JSON 崩溃了：{e}")

    if agent.history_size != 0 or agent.summary is not None:
        _fail("损坏 JSON 未降级为空会话")
    _ok("损坏 JSON 已优雅降级为新会话")


def main():
    print("=" * 60)
    print("  第 2 期多轮对话管理 · 端到端测试")
    print("=" * 60)

    try:
        test_summary_triggered()
        test_persistence_and_recovery()
        test_reset()
        test_corrupted_json()
    finally:
        _clean()

    print("\n" + "=" * 60)
    print("  🎉 全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
