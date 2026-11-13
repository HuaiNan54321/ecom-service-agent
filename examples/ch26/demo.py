"""将开发失败整理为有边界的经验条目，再按条件加载策略文字。"""

from copy import deepcopy
from datetime import date
import json

from examples.ch17.dataset import load_tasks
from examples.ch25.strategy import BASE, RULES, evaluate, make_text, summary


def merge_entry(entries: list, candidate: dict) -> list:
    """同一适用范围和版本的同一规则去重；冲突由人检查，不静默覆盖。"""
    required = {"id", "scope", "policy_version", "expires_on", "instruction", "evidence_ids"}
    if set(candidate) != required or not candidate["evidence_ids"]:
        raise ValueError("经验字段不完整，或缺少支持它的开发轨迹")
    if candidate["instruction"] not in RULES.values():
        raise ValueError("经验必须是本演示支持的策略句")
    date.fromisoformat(candidate["expires_on"])
    result = deepcopy(entries)
    for entry in result:
        same_key = all(entry[key] == candidate[key] for key in ("id", "scope", "policy_version"))
        if same_key:
            if entry["instruction"] != candidate["instruction"]:
                raise ValueError("同一经验版本出现冲突，需人工选择新版本")
            entry["evidence_ids"] = sorted(set(entry["evidence_ids"] + candidate["evidence_ids"]))
            return result
    result.append(deepcopy(candidate))
    return result


def load_instructions(entries: list, scope: str, version: str, today: str) -> str:
    """仅加载仍适用的条目；时间使用显式教学日期，便于复现。"""
    current = date.fromisoformat(today)
    lines = [BASE]
    for entry in entries:
        if (entry["scope"] == scope and entry["policy_version"] == version
                and date.fromisoformat(entry["expires_on"]) >= current
                and entry["instruction"] not in lines):
            lines.append(entry["instruction"])
    return "\n".join(lines)


def run_demo() -> dict:
    """经验来源仅取开发运行；验证集不反向变成经验依据。"""
    dev = load_tasks("dev")
    before = evaluate(BASE, dev)
    repaired = evaluate(make_text("check_result"), dev)
    repaired_by_id = {row["task_id"]: row for row in repaired["rows"]}
    evidence = [row["task_id"] for row in before["rows"]
                if not row["passed"] and repaired_by_id[row["task_id"]]["passed"]]
    entry = {"id": "E001", "scope": "教学订单", "policy_version": "demo-v1",
             "expires_on": "2027-01-01", "instruction": RULES["check_result"],
             "evidence_ids": evidence}
    entries = merge_entry([], entry)
    entries = merge_entry(entries, entry)
    assert len(entries) == 1
    text = load_instructions(entries, "教学订单", "demo-v1", "2026-11-13")
    assert text == make_text("check_result")
    assert load_instructions(entries, "教学订单", "demo-v2", "2026-11-13") == BASE
    assert load_instructions(entries, "教学订单", "demo-v1", "2028-01-01") == BASE
    conflict = dict(entry, instruction=RULES["recover_timeout"])
    try:
        merge_entry(entries, conflict)
    except ValueError:
        pass
    else:
        raise AssertionError("冲突经验不应静默覆盖")
    validation = load_tasks("validation")
    return {"性质": "人工指定候选经验的确定性演示，非完整ACE或SkillRevise复现",
            "经验": entries, "加载的策略": text,
            "验证集基线": summary(evaluate(BASE, validation)),
            "验证集候选": summary(evaluate(text, validation)),
            "过期或版本不符": "不加载", "模型调用次数": 0}


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
