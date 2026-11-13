"""检查记忆写入的同意、字段和版本边界。"""

import unittest

from examples.ch15.demo import MemoryStore


class MemoryTests(unittest.TestCase):
    def test_consent_scope_and_conflict(self):
        with MemoryStore(":memory:") as store:
            kwargs = dict(source="用户表达", expected_version=0, now=10, expires_at=20)
            with self.assertRaises(ValueError):
                store.put("U1001", "reply_style", "简短", consent=False, **kwargs)
            with self.assertRaises(ValueError):
                store.put("U1001", "password", "不应保存", consent=True, **kwargs)
            store.put("U1001", "reply_style", "简短", consent=True, **kwargs)
            with self.assertRaises(ValueError):
                store.put("U1001", "reply_style", "重复写入", consent=True, **kwargs)
            self.assertEqual(store.recall("U1001", now=11)["value"], "简短")
            self.assertIsNone(store.recall("U1002", now=11))
            self.assertIsNone(store.recall("U1001", now=20))


if __name__ == "__main__":
    unittest.main()
