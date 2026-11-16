"""在相同的客服任务上比较两套确定性程序策略。"""

from copy import deepcopy
from time import perf_counter
from examples.ch17.dataset import make_environment, public_input
from examples.ch18.scoring import grade


FLAGS = ("clarify_missing", "check_result", "recover_timeout")


def policy_flags(policy="checked"):
    """只允许三个明确的行为开关，评分器和业务权限不在修改范围内。"""
    if isinstance(policy, str):
        if policy not in {"baseline", "checked"}:
            raise ValueError("策略名称只能是 baseline 或 checked")
        return {name: policy == "checked" for name in FLAGS}
    if not isinstance(policy, dict) or set(policy) != set(FLAGS):
        raise ValueError("策略必须包含约定的三个开关")
    if any(type(value) is not bool for value in policy.values()):
        raise ValueError("策略开关必须是布尔值")
    return dict(policy)


def run_task(task, policy="checked"):
    """重新初始化一个案例，记录工具轨迹，再用私有目标评分。"""
    flags = policy_flags(policy)
    env = make_environment(task)
    before = env.snapshot()
    request = public_input(task)
    trace = []
    started = perf_counter()

    def call(tool, arguments):
        """把返回值和超时都保留在轨迹中，避免只有最终一句话。"""
        event = {"tool": tool, "arguments": deepcopy(arguments)}
        trace.append(event)
        try:
            result = getattr(env, tool)(**arguments)
            event["result"] = deepcopy(result)
            return result
        except TimeoutError:
            event["error"] = "TimeoutError"
            raise

    answer = {"status": "unknown", "text": "结果尚不确定。", "facts": {}}
    if request["order_id"] is None and flags["clarify_missing"]:
        answer = {"status": "clarify", "text": "请提供订单号。", "facts": {}}
    else:
        arguments = {"user_id": request["user_id"], "order_id": request["order_id"]}
        tool = request["action"]
        if tool not in {"query_order", "query_logistics", "request_refund", "query_refund"}:
            raise ValueError("任务包含不支持的工具动作")
        if tool == "request_refund":
            arguments.update({key: request[key] for key in ("reason", "request_id", "confirmed", "amount_cents")})
        try:
            result = call(tool, arguments)
            for _ in range(task["setup"].get("repeat", 1) - 1):
                result = call(tool, arguments)
            if "conflict_amount" in task["setup"]:
                arguments["amount_cents"] = task["setup"]["conflict_amount"]
                result = call(tool, arguments)
        except TimeoutError:
            result = None
            if flags["recover_timeout"] and tool == "request_refund":
                recovery = call("query_refund", {"user_id": request["user_id"], "order_id": request["order_id"]})
                if recovery["success"]:
                    result = recovery
        if result is not None:
            if flags["check_result"] and result["success"] is not True:
                answer = {"status": "denied", "text": result["error"]["message"], "facts": {}, "error_code": result["error"]["code"]}
            elif tool in {"request_refund", "query_refund"}:
                answer = {"status": "submitted", "text": "系统中已记录退款申请，尚未代表到账。", "facts": result.get("refund", {})}
            else:
                answer = {"status": "answered", "text": "以下为工具返回的记录。", "facts": result.get("order", result.get("logistics", {}))}
    elapsed_ms = round((perf_counter() - started) * 1000, 3)
    after = env.snapshot()
    verdict = grade(task, before, after, trace, answer)
    return {"task_id": task["id"], "family": task["family"], "split": task["split"],
            **verdict, "tool_calls": len(trace), "trace": trace, "answer": answer,
            "initial_state": before, "final_state": after,
            "elapsed_ms": elapsed_ms}


def run_suite(tasks, policy="checked"):
    """每个分组独立计算分母；耗时是本机程序耗时，模型用量为空。"""
    if not tasks:
        raise ValueError("评测任务不能为空")
    rows = [run_task(task, policy) for task in tasks]
    passed = sum(row["passed"] for row in rows)
    tool_calls = sum(row["tool_calls"] for row in rows)
    pass_at_1 = passed / len(rows)
    return {"mode": "deterministic_policy", "total": len(rows), "passed": passed,
            "rate": pass_at_1, "pass_at_1": pass_at_1, "tool_calls": tool_calls,
            "mean_tool_calls": tool_calls / len(rows),
            "model_calls": 0, "input_tokens": None, "output_tokens": None, "rows": rows}


def paired_changes(baseline, candidate):
    """按任务编号配对，只在两边都完整且每题各跑一次时计算差异。"""
    old = {row["task_id"]: row["passed"] for row in baseline["rows"]}
    new = {row["task_id"]: row["passed"] for row in candidate["rows"]}
    if (not old or old.keys() != new.keys()
            or len(old) != len(baseline["rows"]) or len(new) != len(candidate["rows"])):
        raise ValueError("两组须使用同一批非空任务，每个任务编号各出现一次")
    improved = sorted(key for key in old if not old[key] and new[key])
    regressions = sorted(key for key in old if old[key] and not new[key])
    return {"improved": improved, "regressions": regressions,
            "delta_pp": 100 * (len(improved) - len(regressions)) / len(old)}
