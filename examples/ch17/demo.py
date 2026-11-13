"""展示任务、分组和环境隔离；本章不调用模型。"""

import json
from examples.ch17.dataset import load_tasks, make_environment, public_input


def main():
    """打印可核对的案例数，并确认运行间不会共享订单状态。"""
    counts = {split: len(load_tasks(split)) for split in ("dev", "validation", "test")}
    assert counts == {"dev": 10, "validation": 10, "test": 10}
    all_tasks = sum((load_tasks(split) for split in counts), [])
    assert len({task["id"] for task in all_tasks}) == 30
    assert len({task["family"] for task in all_tasks}) == 30
    case = load_tasks("dev")[4]
    left, right = make_environment(case), make_environment(case)
    left.request_refund("U1001", "A1002", "不再需要", request_id="ISOLATION", confirmed=True)
    assert right.query_order("U1001", "A1002")["order"]["status"] == "pending"
    assert "expected" not in public_input(case) and "setup" not in public_input(case)
    print(json.dumps({"任务数": counts, "环境隔离": "通过", "对外输入": public_input(case)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
