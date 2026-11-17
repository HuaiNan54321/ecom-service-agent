"""核对两种客服的会话归属和记忆资料在模型消息中的位置。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.agent.chat import EcomAgent
from app.agent.memory.extraction import extract_long_term_facts, extract_short_term_facts
from app.agent.memory.long_term import MemoryFact
from app.agent.storage import save_session
from app.config.settings import settings
from app.multi_agent.orchestrator import MultiAgentOrchestrator


class ChatContextTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.addCleanup(patch.stopall)
        for key, value in {
            "openai_api_key": "local-test",
            "openai_base_url": "http://127.0.0.1:9/v1",
            "mcp_enabled": False,
            "skills_enabled": False,
            "memory_enabled": True,
            "memory_dir": str(self.root / "memory"),
            "policy_db_path": str(self.root / "policy.sqlite3"),
        }.items():
            patch.object(settings, key, value).start()

    def test_unowned_session_is_preserved_and_each_user_resumes_their_own(self):
        base = self.root / "session.json"
        save_session(str(base), [{"role": "user", "content": "旧版本的订单记录"}], None)
        legacy_bytes = base.read_bytes()
        for owner in ("default", "小红", "小明"):
            agent = EcomAgent(str(base), user_id=owner)
            self.assertEqual(agent.history_size, 0)
            agent.raw_messages.append({"role": "user", "content": f"{owner}的订单记录"})
            agent.save()
            self.assertEqual(json.loads(Path(agent.session_path).read_text())["owner"], owner)
        self.assertEqual(base.read_bytes(), legacy_bytes)
        for owner in ("小明", "小红", "default"):
            restored = MultiAgentOrchestrator(str(base), user_id=owner)
            self.assertEqual(restored.raw_messages, [{"role": "user", "content": f"{owner}的订单记录"}])

    def test_customer_history_is_supplied_as_customer_data_in_both_modes(self):
        for agent_type in (EcomAgent, MultiAgentOrchestrator):
            with self.subTest(agent=agent_type.__name__):
                agent = agent_type(str(self.root / "session.json"), user_id="小红")
                agent.summary = "此前的会话摘要片段"
                agent.memory_manager.stm.facts = ["顾客记忆片段"]
                messages = (agent._build_messages() if isinstance(agent, EcomAgent)
                            else agent._build_messages(agent.agents["postsale"]))
                system = [m["content"] for m in messages if m["role"] == "system"]
                customer = [m["content"] for m in messages if m["role"] == "user"]
                for part in (agent.summary, "顾客记忆片段"):
                    self.assertFalse(any(part in text for text in system))
                    self.assertTrue(any(part in text for text in customer))

    def test_memory_extraction_keeps_existing_facts_out_of_system_messages(self):
        client = MagicMock()
        fact = "顾客上次保存的偏好"
        conversation = [{"role": "user", "content": "这次想要红色款"}]
        call = client.chat.completions.create
        call.return_value.choices[0].message.content = "无新信息"
        extract_short_term_facts(client, "local-test", conversation, [fact])
        call.return_value.choices[0].message.content = '{"facts":[],"interaction_summary":"选红色"}'
        extract_long_term_facts(client, "local-test", conversation, "历史摘要", [MemoryFact(fact, "preference", "")])
        for request in call.call_args_list:
            system, customer = request.kwargs["messages"]
            self.assertNotIn(fact, system["content"])
            self.assertEqual(customer["role"], "user")
            self.assertIn(fact, customer["content"])
            self.assertIn("这次想要红色款", customer["content"])
