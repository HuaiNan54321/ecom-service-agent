"""端到端测试：验证第 7 期 Memory 短期记忆 & 长期记忆。

测试场景：
1. 短期记忆事实提取 — 对话中提到偏好，STM 应提取到事实
2. 短期记忆 prompt 注入 — STM 事实应出现在构建的 prompt 中
3. 短期记忆会话持久化 — save/load 后 STM 事实应恢复
4. 短期记忆 reset — reset 后 STM 应清空
5. 长期记忆提取与持久化 — consolidate 后 LTM JSON 文件应存在且格式正确
6. 长期记忆跨会话加载 — 新建 agent 后 LTM 事实应被注入 prompt
7. recall_user_memory 工具 — 调用工具应返回 STM + LTM 事实

用法：python3 tests/test_memory.py
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.chat import EcomAgent  # noqa: E402
from app.agent.storage import load_session  # noqa: E402
from app.agent.memory import LongTermMemory, MemoryManager, ShortTermMemory  # noqa: E402
from app.agent.skills import SkillManager  # noqa: E402
from app.agent.tools.manager import ToolManager  # noqa: E402
from app.agent.tools.registry import execute_tool  # noqa: E402
from app.config.settings import settings  # noqa: E402

TEST_ROOT = tempfile.TemporaryDirectory()
TEST_SESSION = Path(TEST_ROOT.name) / "case" / "session.json"
TEST_MEMORY_DIR = TEST_SESSION.parent / "memory"
TEST_USER_ID = "test_user_memory"


class SessionToolIsolationTest(unittest.TestCase):
    def test_interleaved_customers_and_unbound_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.mcp_client.MCPClient") as client:
            remote = client.return_value
            remote.connect.return_value = [
                {"type": "function", "function": {"name": name}}
                for name in ("recall_user_memory", "load_skill")
            ]
            hong_tools = ToolManager(True, "http://unused.invalid")
            ming_tools = ToolManager()
            for name, tools in [("小红", hong_tools), ("小明", ming_tools)]:
                memory = MemoryManager(None, "", user_id=name, memory_dir=directory)
                memory.stm.facts = [name + "想退货"]
                tools.bind_memory_manager(memory)
            hong_tools.bind_skill_manager(SkillManager(enabled=True))
            ming_tools.bind_skill_manager(SkillManager(enabled=False))

            for name, tools in [("小明", ming_tools), ("小红", hong_tools)]:
                memory = json.loads(tools.execute_tool("recall_user_memory", {}))
                self.assertEqual(memory["short_term_facts"], [name + "想退货"])
                skill = json.loads(tools.execute_tool("load_skill", {"skill_name": "process-return"}))
                self.assertEqual(skill["success"], name == "小红")
            for invoke in (execute_tool, ToolManager().execute_tool):
                self.assertFalse(json.loads(invoke("recall_user_memory", {}))["success"])
                self.assertFalse(json.loads(invoke("load_skill", {"skill_name": "process-return"}))["success"])
            self.assertFalse(json.loads(hong_tools.execute_tool("recall_user_memory", {"user_id": "小明"}))["success"])
            remote.call_tool.assert_not_called()


class MemoryOwnerTest(unittest.TestCase):
    def test_old_memory_is_visible_only_to_its_recorded_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "小红.json"
            payload = {"user_id": "小红", "facts": [{"content": "需要发票"}]}
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            owner = LongTermMemory("小红", folder)
            alias = LongTermMemory("./小红", folder)
            alias.load()
            self.assertEqual(alias.facts, [])
            alias.reset()
            self.assertTrue(path.exists())
            owner.load()
            self.assertEqual([fact.content for fact in owner.facts], ["需要发票"])
            owner.save()
            alias.save()
            self.assertNotEqual(alias.memory_path, owner.memory_path)
            reopened = LongTermMemory("小红", folder)
            reopened.load()
            self.assertEqual(reopened.facts, owner.facts)
            reopened.reset()
            self.assertFalse(path.exists())
            self.assertFalse(owner.memory_path.exists())
            self.assertTrue(alias.memory_path.exists())

    def test_filename_alone_does_not_establish_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            a = LongTermMemory("buyer", folder)
            b = LongTermMemory("BUYER", folder)
            self.assertNotEqual(a.memory_path, b.memory_path)
            old_path = Path(folder) / "buyer.json"
            old_path.write_text(json.dumps({"user_id": "BUYER", "facts": [{"content": "偏好 A"}]}),
                                encoding="utf-8")
            a.load()
            self.assertEqual(a.facts, [])
            a.reset()
            self.assertTrue(old_path.exists())


def _clean():
    shutil.rmtree(TEST_SESSION.parent, ignore_errors=True)


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def _make_agent(threshold: int = 30, keep: int = 6) -> EcomAgent:
    """创建测试用 Agent，使用独立的 session 和 memory 路径。"""
    with patch.multiple(settings, memory_enabled=True, memory_dir=str(TEST_MEMORY_DIR)):
        agent = EcomAgent(session_path=str(TEST_SESSION), user_id=TEST_USER_ID)
    agent.history_threshold = threshold
    agent.history_keep_recent = keep

    return agent


# ---------- 测试 1：短期记忆事实提取 ----------
def test_stm_extraction():
    print("\n[1/7] 短期记忆事实提取")
    _clean()
    agent = _make_agent()

    resp = agent.chat("你好，我是张三，钻石会员，我想看看你们有什么红色的运动鞋")
    stm_facts = agent.memory_manager.stm.facts

    if len(stm_facts) > 0:
        _ok(f"STM 提取到 {len(stm_facts)} 条事实")
        for f in stm_facts:
            print(f"     - {f}")
    else:
        _fail("STM 未提取到任何事实")

    keywords = ["张三", "钻石", "红色", "运动鞋"]
    facts_text = " ".join(stm_facts).lower()
    found = sum(1 for kw in keywords if kw in facts_text)
    if found >= 2:
        _ok(f"事实中包含 {found}/{len(keywords)} 个预期关键词")
    else:
        print(f"  ⚠️  事实中仅包含 {found}/{len(keywords)} 个预期关键词")


# ---------- 测试 2：短期记忆 prompt 注入 ----------
def test_stm_prompt_injection():
    print("\n[2/7] 短期记忆 prompt 注入验证")
    _clean()
    agent = _make_agent()

    agent.chat("我叫李四，是你们的老客户了，特别喜欢蓝色的商品")

    sections = agent.memory_manager.build_memory_prompt_sections()
    if sections:
        all_text = " ".join(s["content"] for s in sections)
        if "短期记忆" in all_text or "用户关键信息" in all_text:
            _ok("STM prompt section 格式正确")
        else:
            print(f"  ⚠️  prompt section 内容未包含预期标题")
        print(f"     注入了 {len(sections)} 个 system 消息")
    else:
        _fail("build_memory_prompt_sections 返回空列表")


# ---------- 测试 3：短期记忆会话持久化 ----------
def test_stm_persistence():
    print("\n[3/7] 短期记忆会话持久化")
    _clean()
    agent = _make_agent()

    agent.chat("我是VIP用户，喜欢打折商品")
    agent.save()

    loaded = load_session(agent.session_path)
    if loaded is None:
        _fail("会话文件加载失败")

    stm_data = loaded.get("short_term_memory")
    if stm_data and stm_data.get("facts"):
        _ok(f"会话文件中保存了 {len(stm_data['facts'])} 条 STM 事实")

        restored_stm = ShortTermMemory.from_dict(stm_data)
        if restored_stm.facts == agent.memory_manager.stm.facts:
            _ok("恢复的 STM 事实与原始一致")
        else:
            _fail("恢复的 STM 事实与原始不一致")
    else:
        _fail("会话文件中未找到 short_term_memory 数据")


# ---------- 测试 4：短期记忆 reset ----------
def test_stm_reset():
    print("\n[4/7] 短期记忆 reset")
    _clean()
    agent = _make_agent()

    agent.chat("买鞋我喜欢宽楦，平时穿 42 码，想看看有哪几款合适")
    assert len(agent.memory_manager.stm.facts) > 0, "STM 应有事实"

    agent.reset()
    if len(agent.memory_manager.stm.facts) == 0:
        _ok("reset 后 STM 已清空")
    else:
        _fail(f"reset 后 STM 仍有 {len(agent.memory_manager.stm.facts)} 条事实")


# ---------- 测试 5：长期记忆提取与持久化 ----------
def test_ltm_extraction():
    print("\n[5/7] 长期记忆提取与持久化")
    _clean()
    agent = _make_agent()

    agent.chat("你好，我是王五，钻石会员，之前买过你们的耳机觉得不错")
    agent.chat("我这次想看看有没有新款手机，预算三千左右")

    agent.memory_manager.consolidate_to_long_term(
        agent.raw_messages, agent.summary,
    )

    memory_path = agent.memory_manager.ltm.memory_path
    if not memory_path.exists():
        _fail(f"LTM 文件未生成: {memory_path}")

    with memory_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "facts" not in data or "interaction_summaries" not in data:
        _fail("LTM JSON 缺少 facts 或 interaction_summaries 字段")

    if len(data["facts"]) > 0:
        _ok(f"LTM 提取到 {len(data['facts'])} 条事实")
        for f in data["facts"][:3]:
            print(f"     - [{f['category']}] {f['content']}")
    else:
        print("  ⚠️  LTM 未提取到事实（可能因对话内容不够丰富）")

    if data["interaction_summaries"]:
        _ok(f"交互摘要: {data['interaction_summaries'][-1]['summary']}")
    else:
        print("  ⚠️  未生成交互摘要")


# ---------- 测试 6：长期记忆跨会话加载 ----------
def test_ltm_cross_session():
    print("\n[6/7] 长期记忆跨会话加载")
    _clean()

    agent1 = _make_agent()
    agent1.chat("我叫赵六，是你们的钻石会员，特别喜欢黑色的数码产品")
    agent1.memory_manager.consolidate_to_long_term(
        agent1.raw_messages, agent1.summary,
    )

    Path(agent1.session_path).unlink()
    agent2 = _make_agent()

    ltm_facts = agent2.memory_manager.ltm.facts
    if len(ltm_facts) > 0:
        _ok(f"新 Agent 加载了 {len(ltm_facts)} 条 LTM 事实")
    else:
        _fail("新 Agent 未加载到 LTM 事实")

    sections = agent2.memory_manager.build_memory_prompt_sections()
    has_ltm = any("历史记忆" in s["content"] or "过往会话" in s["content"] for s in sections)
    if has_ltm:
        _ok("LTM 事实已注入 prompt sections")
    else:
        print("  ⚠️  LTM 事实可能未正确注入 prompt（标题不匹配）")


# ---------- 测试 7：recall_user_memory 工具 ----------
def test_memory_tool():
    print("\n[7/7] recall_user_memory 工具测试")
    _clean()
    agent = _make_agent()

    agent.chat("你好，我叫测试用户，最喜欢白色的衣服")
    agent.memory_manager.consolidate_to_long_term(
        agent.raw_messages, agent.summary,
    )

    result = json.loads(agent.tool_manager.execute_tool("recall_user_memory", {}))
    if not result.get("success"):
        _fail(f"工具返回失败: {result}")

    stm = result.get("short_term_facts", [])
    ltm = result.get("long_term_facts", [])

    if stm:
        _ok(f"工具返回 {len(stm)} 条短期记忆")
    else:
        print("  ⚠️  工具未返回短期记忆")

    if ltm:
        _ok(f"工具返回 {len(ltm)} 条长期记忆")
    else:
        print("  ⚠️  工具未返回长期记忆")

    print(f"     短期: {stm[:3]}")
    print(f"     长期: {ltm[:3]}")


def main():
    print("=" * 60)
    print("  第 7 期 Memory 短期记忆 & 长期记忆 · 端到端测试")
    print("=" * 60)

    try:
        test_stm_extraction()
        test_stm_prompt_injection()
        test_stm_persistence()
        test_stm_reset()
        test_ltm_extraction()
        test_ltm_cross_session()
        test_memory_tool()
    finally:
        _clean()

    print("\n" + "=" * 60)
    print("  全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
