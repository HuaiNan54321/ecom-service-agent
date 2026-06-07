"""端到端测试：验证第 8 期 Skill 可复用能力模块。

测试场景：
1. Skill 发现 — SkillManager 扫描并解析 SKILL.md frontmatter
2. Skill catalog 生成 — 技能目录文本可注入 system prompt
3. load_skill 工具 — 加载完整技能指令（成功）
4. load_skill 工具 — 未知技能（返回错误和可用列表）
5. Skill 关闭开关 — skills_enabled=False 时技能系统不启用
6. SKILL.md body 延迟加载 — 初始化后 body 未读取
7. Agent 端到端 — skill catalog 注入 prompt，Agent 能调用 load_skill

用法：python3 tests/test_skills.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.skills import SkillManager  # noqa: E402
from app.agent.tools.skill_tool import load_skill, set_skill_manager  # noqa: E402

TEST_SESSION = str(ROOT / "app" / "sessions" / "test_skills_session.json")


def _clean():
    Path(TEST_SESSION).unlink(missing_ok=True)


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


# ---------- 测试 1：Skill 发现 ----------
def test_skill_discovery():
    print("\n[1/7] Skill 发现测试")
    sm = SkillManager(skills_dir=str(ROOT / "app" / "agent" / "skills" / "definitions"), enabled=True)

    if sm.skill_count >= 3:
        _ok(f"发现 {sm.skill_count} 个技能")
    else:
        _fail(f"预期至少 3 个技能，实际 {sm.skill_count}")

    expected = {"process-return", "track-order", "product-recommend"}
    actual = set(sm.skill_names)
    if expected.issubset(actual):
        _ok(f"包含所有预期技能: {sorted(expected)}")
    else:
        _fail(f"缺少技能: {expected - actual}")


# ---------- 测试 2：Catalog 生成 ----------
def test_catalog_generation():
    print("\n[2/7] Skill catalog 生成测试")
    sm = SkillManager(skills_dir=str(ROOT / "app" / "agent" / "skills" / "definitions"), enabled=True)

    catalog = sm.get_catalog()
    if len(catalog) >= 3:
        _ok(f"catalog 包含 {len(catalog)} 个条目")
    else:
        _fail(f"catalog 条目不足: {len(catalog)}")

    for entry in catalog:
        if "name" in entry and "description" in entry and entry["description"]:
            _ok(f"  {entry['name']}: {entry['description'][:50]}...")
        else:
            _fail(f"catalog 条目缺少 name/description: {entry}")

    prompt_text = sm.build_catalog_prompt()
    if "可用技能" in prompt_text and "load_skill" in prompt_text:
        _ok("catalog prompt 包含使用说明")
    else:
        _fail("catalog prompt 格式不正确")


# ---------- 测试 3：load_skill 成功 ----------
def test_load_skill_success():
    print("\n[3/7] load_skill 工具测试（成功）")
    sm = SkillManager(skills_dir=str(ROOT / "app" / "agent" / "skills" / "definitions"), enabled=True)
    set_skill_manager(sm)

    result = load_skill("process-return")
    if result.get("success"):
        _ok("成功加载 process-return 技能")
    else:
        _fail(f"加载失败: {result}")

    instructions = result.get("instructions", "")
    if "退货" in instructions and "query_order" in instructions:
        _ok(f"指令内容完整（{len(instructions)} 字符）")
    else:
        _fail("指令内容不完整")

    result2 = load_skill("track-order")
    if result2.get("success") and "物流" in result2.get("instructions", ""):
        _ok("成功加载 track-order 技能")
    else:
        _fail(f"track-order 加载失败: {result2}")

    result3 = load_skill("product-recommend")
    if result3.get("success") and "推荐" in result3.get("instructions", ""):
        _ok("成功加载 product-recommend 技能")
    else:
        _fail(f"product-recommend 加载失败: {result3}")


# ---------- 测试 4：load_skill 未知技能 ----------
def test_load_skill_unknown():
    print("\n[4/7] load_skill 工具测试（未知技能）")
    sm = SkillManager(skills_dir=str(ROOT / "app" / "agent" / "skills" / "definitions"), enabled=True)
    set_skill_manager(sm)

    result = load_skill("nonexistent-skill")
    if not result.get("success"):
        _ok("正确返回错误")
    else:
        _fail("应该返回错误但返回了成功")

    if "可用技能" in result.get("error", "") or "未找到" in result.get("error", ""):
        _ok(f"错误信息: {result['error']}")
    else:
        _fail(f"错误信息格式不正确: {result.get('error')}")


# ---------- 测试 5：Skills 关闭 ----------
def test_skills_disabled():
    print("\n[5/7] Skill 关闭开关测试")
    sm = SkillManager(skills_dir=str(ROOT / "app" / "agent" / "skills" / "definitions"), enabled=False)

    if sm.skill_count == 0:
        _ok("enabled=False 时不加载技能")
    else:
        _fail(f"enabled=False 但加载了 {sm.skill_count} 个技能")

    prompt = sm.build_catalog_prompt()
    if prompt == "":
        _ok("disabled 时 catalog prompt 为空")
    else:
        _fail("disabled 时 catalog prompt 不为空")

    set_skill_manager(sm)
    result = load_skill("process-return")
    if not result.get("success") and "未启用" in result.get("error", ""):
        _ok("disabled 时 load_skill 返回未启用错误")
    else:
        _fail(f"disabled 时 load_skill 行为异常: {result}")


# ---------- 测试 6：延迟加载 ----------
def test_lazy_loading():
    print("\n[6/7] SKILL.md body 延迟加载测试")
    sm = SkillManager(skills_dir=str(ROOT / "app" / "agent" / "skills" / "definitions"), enabled=True)

    skill = sm._skills.get("process-return")
    if skill is None:
        _fail("process-return 技能不存在")

    if not skill._body_loaded:
        _ok("初始化后 body 未加载（延迟加载）")
    else:
        _fail("初始化后 body 已加载（应延迟）")

    body = skill.load_body()
    if skill._body_loaded and len(body) > 100:
        _ok(f"调用 load_body 后成功加载（{len(body)} 字符）")
    else:
        _fail("load_body 加载失败")


# ---------- 测试 7：Agent 集成 ----------
def test_agent_integration():
    print("\n[7/7] Agent 集成测试（E2E，需要 API 调用）")
    _clean()
    from app.agent.chat import EcomAgent

    try:
        agent = EcomAgent(session_path=TEST_SESSION)

        if hasattr(agent, "skill_manager") and agent.skill_manager.enabled:
            _ok("Agent 初始化了 SkillManager")
        else:
            _fail("Agent 未初始化 SkillManager")

        messages = agent._build_messages()
        system_content = messages[0]["content"]
        if "可用技能" in system_content and "process-return" in system_content:
            _ok("skill catalog 已注入 system prompt")
        else:
            _fail("skill catalog 未注入 system prompt")

        resp = agent.chat("我买的鞋子尺码不对，想退掉，订单号是 ORD-20240115-001")
        _ok(f"Agent 回复: {resp.reply[:80]}...")

        skill_loaded = any(
            tc.get("function", {}).get("name") == "load_skill"
            for msg in agent.raw_messages
            if msg.get("role") == "assistant"
            for tc in msg.get("tool_calls", [])
        )
        if skill_loaded:
            _ok("Agent 主动调用了 load_skill 工具")
        else:
            print("  ⚠️  Agent 未调用 load_skill（可能因模型决策差异，非致命）")

    finally:
        _clean()


def main():
    print("=" * 60)
    print("  第 8 期 Skill 可复用能力模块 · 端到端测试")
    print("=" * 60)

    try:
        test_skill_discovery()
        test_catalog_generation()
        test_load_skill_success()
        test_load_skill_unknown()
        test_skills_disabled()
        test_lazy_loading()
        test_agent_integration()
    finally:
        _clean()

    print("\n" + "=" * 60)
    print("  全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
