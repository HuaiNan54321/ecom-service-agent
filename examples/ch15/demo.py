"""用 SQLite 和新进程演示记忆的持久化、更新、隔离与遗忘。"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


class MemoryStore:
    """本地教学存储；调用方必须先认证用户，不能让模型决定用户身份。"""

    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS memory (
            user_id TEXT, key TEXT, value TEXT, source TEXT,
            version INTEGER, updated_at INTEGER, expires_at INTEGER,
            PRIMARY KEY (user_id, key))""")
        self.connection.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    @staticmethod
    def check_scope(user_id, key):
        """限制教学身份格式和可保存字段，不接收任意敏感资料。"""
        if not isinstance(user_id, str) or not re.fullmatch(r"U[0-9]{4}", user_id):
            raise ValueError("用户编号格式不正确")
        if key not in {"reply_style", "language"}:
            raise ValueError("该字段不在可保存的偏好清单内")

    def put(self, user_id, key, value, *, source, expected_version, now, expires_at, consent):
        """只在明确同意且版本匹配时更新，旧候选不能覆盖刚刚纠正的偏好。"""
        self.check_scope(user_id, key)
        if consent is not True:
            raise ValueError("未获得保存偏好的明确同意")
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError("偏好值必须是1至200字的文本")
        if not isinstance(source, str) or not source.strip() or len(source) > 80:
            raise ValueError("必须提供简短的来源标识")
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("期望版本必须是非负整数")
        if type(now) is not int or type(expires_at) is not int or expires_at <= now:
            raise ValueError("到期时间必须晚于写入时间")
        with self.connection:
            if expected_version == 0:
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO memory VALUES (?, ?, ?, ?, 1, ?, ?)",
                    (user_id, key, value, source, now, expires_at),
                )
            else:
                cursor = self.connection.execute(
                    "UPDATE memory SET value=?,source=?,version=version+1,updated_at=?,expires_at=? "
                    "WHERE user_id=? AND key=? AND version=?",
                    (value, source, now, expires_at, user_id, key, expected_version),
                )
            if cursor.rowcount != 1:
                raise ValueError("版本冲突，请重新读取后处理")

    def recall(self, user_id, key="reply_style", *, now):
        """只读当前用户、当前字段且未到期的记录；过期不等于物理删除。"""
        self.check_scope(user_id, key)
        row = self.connection.execute(
            "SELECT value,source,version,expires_at FROM memory "
            "WHERE user_id=? AND key=? AND expires_at>?",
            (user_id, key, now),
        ).fetchone()
        return dict(zip(("value", "source", "version", "expires_at"), row)) if row else None

    def forget(self, user_id, key="reply_style"):
        """只删除指定用户的指定偏好；其他缓存及历史消息需应用另外处理。"""
        self.check_scope(user_id, key)
        with self.connection:
            self.connection.execute("DELETE FROM memory WHERE user_id=? AND key=?", (user_id, key))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read", action="store_true", help="新进程读取指定教学数据库")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--user", default="U1001")
    args = parser.parse_args()
    if args.read:
        if not args.db or not args.db.is_file():
            parser.error("--read 必须同时提供已有数据库的 --db 路径")
        with MemoryStore(args.db) as store:
            print(json.dumps(store.recall(args.user, now=1001), ensure_ascii=False))
        return
    with TemporaryDirectory(prefix="agentbook-memory-") as directory:
        path = Path(directory) / "memory.sqlite3"
        with MemoryStore(path) as store:
            for user, value in (("U1001", "简短"), ("U1002", "详细")):
                store.put(user, "reply_style", value, source="用户明确表达", expected_version=0, now=1000, expires_at=2000, consent=True)
        raw = subprocess.check_output([sys.executable, "-m", "examples.ch15.demo", "--read", "--db", str(path)], text=True)
        restored = json.loads(raw)
        assert restored["value"] == "简短" and restored["version"] == 1
        print("新进程读取：", restored["value"], "；版本：", restored["version"])
        with MemoryStore(path) as store:
            assert store.recall("U1003", now=1001) is None
            store.put("U1001", "reply_style", "详细", source="用户明确纠正", expected_version=1, now=1002, expires_at=2000, consent=True)
            print("纠正后：", store.recall("U1001", now=1003)["value"], "；版本：", store.recall("U1001", now=1003)["version"])
            try:
                store.put("U1001", "reply_style", "简短", source="旧任务候选", expected_version=1, now=1004, expires_at=2000, consent=True)
            except ValueError as exc:
                print("旧候选：", exc)
            else:
                raise AssertionError("旧版本候选不应覆盖新记录")
            assert store.recall("U1001", now=2000) is None
            print("到期读取：", store.recall("U1001", now=2000))
            store.forget("U1001")
            assert store.recall("U1001", now=1005) is None
            assert store.recall("U1002", now=1005)["value"] == "详细"
            print("遗忘后 U1001：", store.recall("U1001", now=1005), "；U1002：", store.recall("U1002", now=1005)["value"])
    print("演示使用临时数据库，退出后清理；没有训练模型。")


if __name__ == "__main__":
    main()
