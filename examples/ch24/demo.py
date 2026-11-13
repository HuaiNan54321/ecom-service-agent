"""固定角色函数的串行/并行对照；不调用模型，不宣称多 Agent 效果提升。"""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from time import perf_counter
from typing import Callable
import json

from examples.ch17.dataset import load_tasks, make_environment, public_input
from examples.ch18.scoring import grade


def order_worker(read_order: Callable[[str], dict], order_id: str) -> dict:
    """只接收已经绑定主体的查单入口，不接收完整业务容器。"""
    result = read_order(order_id)
    return {"role": "order", "tool": "query_order",
            "arguments": {"order_id": order_id}, "result": result}


def policy_worker(policies: list[dict]) -> dict:
    """该角色只收到政策副本，不收到用户、订单库或写工具。"""
    policy = policies[0]
    return {"role": "policy", "policy_id": policy["policy_id"], "text": policy["text"]}


def merge(order_result: dict, policy_result: dict) -> dict:
    """汇总前检查交接结构；某个角色失败时不能编造完整答案。"""
    if order_result.get("role") != "order" or policy_result.get("role") != "policy":
        raise ValueError("角色交接格式不符")
    result = order_result.get("result", {})
    if result.get("success") is not True:
        raise ValueError("订单查询失败，不能合成成功回复")
    if not policy_result.get("policy_id") or not policy_result.get("text"):
        raise ValueError("政策依据缺失，不能声称已查阅政策")
    order = result["order"]
    return {"status": "answered", "facts": {"order_id": order["order_id"], "status": order["status"]},
            "text": f"订单状态为 {order['status']}；退款申请条件见 {policy_result['policy_id']}。"}


def run(task: dict, *, parallel: bool) -> dict:
    """两种方式使用相同任务、数据与评分器，只改变调度方式。"""
    request = public_input(task)
    box = make_environment(task)
    before = box.snapshot()
    policies = before["policies"]
    # 程序绑定当前主体；角色只传订单号，不能重新指定 user_id。
    read_order = partial(box.query_order, request["user_id"])
    start = perf_counter()
    if parallel:
        with ThreadPoolExecutor(max_workers=2) as executor:
            order_future = executor.submit(order_worker, read_order, request["order_id"])
            policy_future = executor.submit(policy_worker, policies)
            order_result, policy_result = order_future.result(timeout=5), policy_future.result(timeout=5)
    else:
        order_result = order_worker(read_order, request["order_id"])
        policy_result = policy_worker(policies)
    answer = merge(order_result, policy_result)
    milliseconds = (perf_counter() - start) * 1000
    verdict = grade(task, before, box.snapshot(), [order_result], answer)
    return {"模式": "并行角色" if parallel else "串行角色", "规则评分通过": verdict["passed"],
            "角色执行数": 2, "汇总次数": 1, "模型调用数": 0,
            "耗时毫秒": round(milliseconds, 3), "回答": answer}


def main() -> None:
    """只使用开发案例，避免把最终保留任务用于架构调试。"""
    task = next(case for case in load_tasks("dev") if case["id"] == "dev_01")
    serial, parallel = run(task, parallel=False), run(task, parallel=True)
    assert serial["规则评分通过"] and parallel["规则评分通过"]
    assert serial["回答"] == parallel["回答"]
    valid_order = {"role": "order", "result": {"success": True, "order": serial["回答"]["facts"]}}
    valid_policy = {"role": "policy", "policy_id": "P-REFUND-1", "text": "合成政策"}
    rejected_pairs = [
        ({"role": "order", "result": {"success": False}}, valid_policy),
        (valid_order, {"role": "policy"}),
        (valid_order, {"role": "unknown", "policy_id": "P-REFUND-1", "text": "合成政策"}),
    ]
    for order_result, policy_result in rejected_pairs:
        try:
            merge(order_result, policy_result)
        except ValueError:
            pass
        else:
            raise AssertionError("失败或缺少依据的角色结果不应被拼成成功答案")
    print(json.dumps({"性质": "固定角色函数与调度实验，不是模型能力对照",
                      "案例": task["id"], "结果": [serial, parallel],
                      "解释": "本地工作量极小，并行开销可能更高；不据此推荐多 Agent。"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
