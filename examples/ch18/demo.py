"""运行真实状态评分，并用故意造错的结果检查评分器。"""

from copy import deepcopy
import json
from examples.ch17.dataset import load_tasks
from examples.ch18.scoring import grade, retrieval_metrics
from examples.ch20.runner import run_task


def main():
    """成功、假成功、错订单、改金额和错误事实应得到不同判定。"""
    task = load_tasks("dev")[4]
    row = run_task(task)
    assert row["passed"]
    no_write = grade(task, row["initial_state"], row["initial_state"], row["trace"], row["answer"])
    assert not no_write["passed"] and "refund_count" in no_write["failures"]
    wrong_order = deepcopy(row["final_state"])
    next(iter(wrong_order["refunds"].values()))["order_id"] = "A1001"
    assert not grade(task, row["initial_state"], wrong_order, row["trace"], row["answer"])["passed"]
    wrong_amount = deepcopy(row["final_state"])
    wrong_amount["orders"]["A1002"]["amount_cents"] = 1
    assert not grade(task, row["initial_state"], wrong_amount, row["trace"], row["answer"])["passed"]
    query = load_tasks("dev")[0]
    query_row = run_task(query)
    lie = deepcopy(query_row["answer"])
    lie["facts"]["status"] = "delivered"
    assert not grade(query, query_row["initial_state"], query_row["final_state"], query_row["trace"], lie)["passed"]
    extra = deepcopy(query_row["answer"])
    extra["facts"]["fabricated_delivery"] = "明天"
    assert not grade(query, query_row["initial_state"], query_row["final_state"], query_row["trace"], extra)["passed"]
    existing_task = load_tasks("validation")[6]
    existing_row = run_task(existing_task)
    replaced = deepcopy(existing_row["final_state"])
    next(iter(replaced["refunds"].values()))["reason"] = "被悄悄替换"
    assert not grade(existing_task, existing_row["initial_state"], replaced, existing_row["trace"], existing_row["answer"])["passed"]
    metrics = retrieval_metrics(["P-X", "P-1", "P-2"], {"P-1", "P-2", "P-3"})
    assert metrics == {"precision": 2 / 3, "recall": 2 / 3, "reciprocal_rank": 0.5}
    print(json.dumps({"正常申请": row["passed"], "只说成功但未写入": no_write,
                      "检索小例子": metrics, "评分器反例检查": "通过"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
