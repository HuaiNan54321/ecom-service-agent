import json
import os
from tempfile import NamedTemporaryFile
from datetime import datetime
from pathlib import Path
from typing import Optional

SESSION_VERSION = 1


def save_session(
    path: str,
    messages: list[dict],
    summary: Optional[str],
    short_term_memory: Optional[dict] = None,
    *,
    owner: Optional[str] = None,
) -> None:
    """把对话状态原子写入 JSON 文件。

    messages 只包含原始 user/assistant 条目（不含 system / summary）。
    short_term_memory 为短期记忆的序列化数据（第7期）。
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": SESSION_VERSION,
        "owner": owner,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "messages": messages,
        "short_term_memory": short_term_memory,
    }

    tmp = NamedTemporaryFile(mode="w", encoding="utf-8", dir=file_path.parent, delete=False)
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
        os.replace(tmp_path, file_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def load_session(path: str) -> Optional[dict]:
    """读取会话文件。不存在或损坏都返回 None（降级为新会话）。"""
    file_path = Path(path)
    if not file_path.exists():
        return None

    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  会话文件损坏，已忽略（{e}）")
        return None

    if not isinstance(data, dict) or "messages" not in data:
        print("⚠️  会话文件格式不识别，已忽略")
        return None

    return {
        "owner": data.get("owner"),
        "summary": data.get("summary"),
        "messages": data.get("messages", []),
        "short_term_memory": data.get("short_term_memory"),
    }


def delete_session(path: str) -> None:
    """删除会话文件，不存在时静默。"""
    file_path = Path(path)
    if file_path.exists():
        file_path.unlink()
