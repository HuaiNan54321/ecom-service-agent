"""客服只读取已采用的规则；维护者在评测通过后操作版本记录。"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.config.settings import settings


RULES = {
    "lookup_first": "涉及订单、物流、商品或售后政策时，先用可用工具核对业务事实，再根据返回结果作答。缺少必要信息时先向顾客核实。",
    "ground_reply": "回答查询时，从本轮工具结果中找出用户问到的字段，并把相应的商品名、金额或进度讲清楚。工具没有返回的信息要标明待核实。",
    "human_handoff": "顾客明确要求人工介入或强烈投诉时，先回应具体诉求，并在结构化答复中标记需要人工跟进；普通咨询继续由客服解答。",
}


def policy_scope(mode: str) -> str:
    """按客服模式、模型和规则文本隔离版本，防止在另一套模型上误用验证结论。"""
    if mode not in ("single", "multi"):
        raise ValueError("客服策略模式应为 single 或 multi")
    config = [mode, settings.model_name, settings.openai_base_url, settings.temperature,
              settings.max_react_steps, settings.skills_enabled, RULES]
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def _active(db: sqlite3.Connection, scope: str) -> tuple[int, tuple[str, ...]]:
    row = db.execute(
        "SELECT v.id, v.rules FROM active a JOIN versions v ON v.id = a.version "
        "WHERE a.scope = ? AND v.scope = ?", (scope, scope),
    ).fetchone()
    return (row[0], tuple(json.loads(row[1]))) if row else (0, ())


def current_policy(mode: str) -> tuple[int, tuple[str, ...]]:
    """首次启动时没有策略库，直接使用项目自带提示词。"""
    path = Path(settings.policy_db_path)
    if not path.is_file():
        return 0, ()
    with closing(sqlite3.connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='active'").fetchone():
            return 0, ()
        return _active(db, policy_scope(mode))


def policy_prompt(mode: str, override: tuple[str, ...] | None = None) -> str:
    rules = current_policy(mode)[1] if override is None else override
    if not rules:
        return ""
    return "\n\n客服处理规则\n" + "\n".join(f"- {RULES[key]}" for key in rules)


def _open_store() -> sqlite3.Connection:
    path = Path(settings.policy_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY, scope TEXT NOT NULL, parent INTEGER NOT NULL,
            rules TEXT NOT NULL, evidence TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS active (scope TEXT PRIMARY KEY, version INTEGER NOT NULL);
    """)
    return db


def passes_gate(paired: dict, errors: int) -> bool:
    """至少挽回一道原本失败的题，保住所有原本通过的题，两侧都完整运行。"""
    return bool(paired["improved"]) and not paired["regressed"] and errors == 0


def save_validated(mode: str, parent: int, rules: tuple[str, ...], evidence: dict) -> int:
    """保存待采用的版本；校验过程中基线若变化，需要重新做对照。"""
    if not evidence["development_cases"] or not passes_gate(evidence["paired"], evidence["errors"]):
        raise ValueError("缺少开发失败证据，或验证结果未达到入库门槛")
    scope = policy_scope(mode)
    with closing(_open_store()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if _active(db, scope)[0] != parent:
            raise ValueError("验证期间已切换客服策略，请重新对照当前版本")
        if not rules or any(key not in RULES for key in rules):
            raise ValueError("候选策略必须来自项目规则库")
        cursor = db.execute("INSERT INTO versions(scope, parent, rules, evidence) VALUES(?, ?, ?, ?)",
                            (scope, parent, json.dumps(rules), json.dumps(evidence, ensure_ascii=False)))
        return cursor.lastrowid


def switch_policy(mode: str, version: int | None, *, rollback_from: int | None = None) -> int:
    """指定版本表示采用；省略版本表示回到当前版本的父版本。"""
    scope = policy_scope(mode)
    with closing(_open_store()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        current, _ = _active(db, scope)
        if version is None:
            if current != rollback_from:
                raise ValueError("要撤回的版本已不是当前版本，客服策略未变更")
            if not current:
                raise ValueError("当前使用内置策略，没有可回滚的版本")
            version, = db.execute("SELECT parent FROM versions WHERE id=?", (current,)).fetchone()
        else:
            row = db.execute("SELECT parent FROM versions WHERE id=? AND scope=?", (version, scope)).fetchone()
            if not row:
                raise ValueError("找不到在当前模式和模型下验证通过的版本")
            if current == version:
                return version
            if row[0] != current:
                raise ValueError("候选所用基线与当前版本不同，请重新验证")
        db.execute("INSERT OR REPLACE INTO active(scope, version) VALUES(?, ?)", (scope, version))
        return version
