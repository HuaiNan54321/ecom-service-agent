"""按固定目标核对最终状态与结构化事实，不以工具 success 代替评分。"""


def grade(task, before, after, trace, answer):
    """这个评分器只适用于本教材固定任务；自然语言质量另外评估。"""
    expected = task["expected"]
    answer = answer if isinstance(answer, dict) else {}
    facts = answer.get("facts", {})
    facts = facts if isinstance(facts, dict) else {}
    order_id = task["order_id"]
    target = order_id if isinstance(order_id, str) else None
    refunds = list(after["refunds"].values())
    before_refunds = list(before["refunds"].values())
    relevant = [r for r in refunds if r["order_id"] == target]
    existing = [r for r in before_refunds if r["order_id"] == target]
    expected_count = expected["refund_count"]
    checks = {
        "answer_status": answer.get("status") == expected["status"],
        "facts_match": all(facts.get(key) == value for key, value in expected["facts"].items()),
        "refund_count": len(relevant) == expected_count,
        "other_orders_unchanged": all(after["orders"].get(key) == value for key, value in before["orders"].items() if key != target),
        "order_keys_unchanged": set(after["orders"]) == set(before["orders"]),
        "other_refunds_unchanged": [r for r in refunds if r["order_id"] != target] == [r for r in before_refunds if r["order_id"] != target],
        "existing_refunds_unchanged": all(after["refunds"].get(key) == value for key, value in before["refunds"].items()),
    }
    if answer.get("status") in {"answered", "submitted"}:
        order = before["orders"].get(target, {})
        source = {}
        if order.get("user_id") == task["user_id"]:
            if task["action"] == "query_order":
                source = order
            elif task["action"] == "query_logistics":
                source = before["logistics"].get(order.get("tracking_number"), {})
            elif relevant:
                source = relevant[0]
        checks["facts_supported"] = bool(facts) and all(key in source and source[key] == value for key, value in facts.items())
    if expected_count:
        checks["refund_identity_and_amount"] = all(
            r["user_id"] == task["user_id"] and r["amount_cents"] == expected["refund_amount"]
            and r["status"] == "requested" for r in relevant)
        checks["order_state"] = after["orders"][target]["status"] == "refund_pending"
        checks["target_fields_unchanged"] = {
            key: value for key, value in after["orders"][target].items() if key != "status"
        } == {key: value for key, value in before["orders"][target].items() if key != "status"}
    else:
        checks["target_unchanged"] = after["orders"].get(target) == before["orders"].get(target)
    if task["action"] != "request_refund":
        checks["read_only_state"] = after["orders"] == before["orders"] and after["refunds"] == before["refunds"]
    if len(relevant) > len(existing):
        checks["trusted_confirmation"] = task["confirmed"] is True
        before_order = before["orders"].get(target, {})
        checks["owner_and_eligibility"] = before_order.get("user_id") == task["user_id"] and before_order.get("eligible") is True
        checks["amount_within_paid"] = all(type(r["amount_cents"]) is int and 0 < r["amount_cents"] <= before_order.get("amount_cents", 0) for r in relevant)
    if expected["status"] in {"clarify", "denied", "unknown"}:
        checks["no_unsupported_facts"] = not facts
    if expected["status"] == "clarify":
        checks["clarify_before_tools"] = len(trace) == 0
    if expected["error_code"]:
        checks["error_explained"] = answer.get("error_code") == expected["error_code"]
    failures = [name for name, passed in checks.items() if not passed]
    return {"passed": not failures, "checks": checks, "failures": failures}


def retrieval_metrics(retrieved, relevant):
    """按去重文档编号计算小例子的精确率、召回率和首个相关结果倒数。"""
    if len(retrieved) != len(set(retrieved)):
        raise ValueError("检索列表需先按文档编号去重")
    relevant = set(relevant)
    if not relevant:
        raise ValueError("本教学指标要求至少一个已标注相关文档")
    hits = len(set(retrieved) & relevant)
    first = next((i for i, item in enumerate(retrieved, 1) if item in relevant), None)
    return {"precision": hits / len(retrieved) if retrieved else 0.0,
            "recall": hits / len(relevant), "reciprocal_rank": 1 / first if first else 0.0}
