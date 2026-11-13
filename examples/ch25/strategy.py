"""将少量明确的策略文字映射为固定执行开关，用来观察改进机制。

这不是大模型，也不理解任意自然语言。评分器、工具权限和案例数据均在
独立章节中；本模块只允许改变三条文本指令是否出现。
"""

from collections import Counter
import hashlib
import json


BASE = "处理订单请求，保持简洁。"
RULES = {
    "clarify_missing": "缺少订单号时，先追问，不猜测。",
    "check_result": "以工具返回的结果为准，不把失败写成成功。",
    "recover_timeout": "退款请求超时后，先查询申请状态，再决定是否继续。",
}


def make_text(*flags: str) -> str:
    """只用白名单内的条目组成教学策略文字。"""
    if len(set(flags)) != len(flags) or any(key not in RULES for key in flags):
        raise ValueError("策略条目重复或不在白名单中")
    return "\n".join([BASE, *(RULES[key] for key in flags)])


def parse_text(text: str) -> dict:
    """严格读取完整句子，不把包含关键词当作理解了任意指令。"""
    if not isinstance(text, str) or not text or len(text) > 1200:
        raise ValueError("策略必须是长度不超过1200字的非空文本")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    allowed = {BASE, *RULES.values()}
    if BASE not in lines or len(set(lines)) != len(lines):
        raise ValueError("必须保留基础句，且不得重复条目")
    if any(line not in allowed for line in lines):
        raise ValueError("候选含未支持的文字；不执行代码或未知指令")
    return {key: value in lines for key, value in RULES.items()}


def digest(value) -> str:
    """记录稳定内容指纹，帮助确认版本和数据有没有变化。"""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def evaluate(text: str, tasks: list) -> dict:
    """使用第20章的固定执行器和第18章的独立评分器。"""
    from examples.ch20.runner import run_suite
    return run_suite(tasks, policy=parse_text(text))


def development_feedback(report: dict) -> dict:
    """只汇总开发运行的失败，不向候选生成端传入隐藏判据。"""
    counts = Counter(
        failure
        for row in report["rows"]
        for failure in row["failures"]
    )
    return {"total": report["total"], "passed": report["passed"],
            "failure_counts": dict(sorted(counts.items()))}


def regressions(baseline: dict, candidate: dict) -> list:
    """逐任务找出改对为错的案例，不能让平均分掩盖退化。"""
    before = {row["task_id"]: row["passed"] for row in baseline["rows"]}
    after = {row["task_id"]: row["passed"] for row in candidate["rows"]}
    if before.keys() != after.keys():
        raise ValueError("两份报告必须针对同一批任务")
    return sorted(key for key, passed in before.items() if passed and not after[key])


def summary(report: dict) -> dict:
    """保留读者需要核对的分母、成绩与确定性工具成本。"""
    return {key: report[key] for key in ("mode", "passed", "total", "tool_calls")}
