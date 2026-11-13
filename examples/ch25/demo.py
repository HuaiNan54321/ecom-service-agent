"""比较三种固定修订策略，演示反馈与执行结果的区别，不调用模型。"""

import json

from examples.ch17.dataset import load_tasks
from examples.ch25.strategy import BASE, evaluate, make_text, summary


def run_demo() -> dict:
    """在同一开发集上重置环境，比较无检查、空泛自评和具体修订。"""
    tasks = load_tasks("dev")
    candidates = {
        "无检查": BASE,
        "预设自评说没有问题": BASE,
        "按工具结果修订": make_text("check_result"),
    }
    reports = {name: evaluate(text, tasks) for name, text in candidates.items()}
    assert reports["无检查"]["passed"] == reports["预设自评说没有问题"]["passed"]
    assert all(report["total"] == len(tasks) for report in reports.values())
    return {"性质": "固定策略的机制演示，不是真实模型反思成绩",
            "结果": {name: summary(report) for name, report in reports.items()},
            "模型调用次数": 0}


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
