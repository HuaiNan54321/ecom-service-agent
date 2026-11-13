"""第10章：固定工作流与受限工具循环；默认决策是可检查的离线脚本。"""

import argparse
import json

from examples.common import Sandbox
from examples.common.llm import ModelAPIError, chat_completion
from examples.ch09.demo import (
    execute_tool_call, offline_response, response_message,
    tool_definitions, tool_request,
)


NAMES = ("query_order", "query_logistics")


def fixed_workflow(order_id):
    """开发者提前写好分支，未发货订单不查询物流。"""
    box = Sandbox()
    order = box.query_order("U1001", order_id)
    calls = ["query_order"]
    if not order["success"] or order["order"]["status"] != "shipped":
        return {"工具": calls, "模型调用次数": 0, "数据": order}
    logistics = box.query_logistics("U1001", order_id)
    calls.append("query_logistics")
    return {"工具": calls, "模型调用次数": 0, "数据": logistics}


def scripted_next(messages, order_id):
    """离线规则按已有结果选下一条预设消息，不具有模型推理能力。"""
    results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
    if not results:
        return tool_request("query_order", order_id, "call_step_1")
    last = results[-1]
    if not last.get("success"):
        return {"role": "assistant", "content": "查询未成功，需要核对输入或稍后重试。"}
    if "order" in last and last["order"]["status"] == "shipped":
        return tool_request("query_logistics", order_id, "call_step_2")
    if "order" in last:
        return {"role": "assistant", "content":
                f"订单状态是 {last['order']['status']}，本轮不继续查询物流。"}
    return {"role": "assistant", "content": "已经取得物流记录，可依据这份记录说明进度。"}


def run_loop(order_id="A1001", *, live=False, max_model_calls=4, max_tool_calls=4):
    """按预算循环；无最终消息时返回明确停止状态，不再追加一次模型调用。"""
    if max_model_calls < 1 or max_tool_calls < 0:
        raise ValueError("模型预算至少为1，工具预算不能为负数")
    box = Sandbox()
    messages = [{"role": "system", "content":
                 "先查订单；若已发货再查物流。查询失败如实说明；不要编造结果。"},
                {"role": "user", "content": f"请查询订单 {order_id} 到哪了。"}]
    trace = []
    usages = []
    model_calls = 0
    used_ids = set()
    for _ in range(max_model_calls):
        fixed = scripted_next(messages, order_id) if not live else None
        raw = chat_completion(messages, live=live, tools=tool_definitions(NAMES),
                              offline_response=offline_response(fixed) if fixed else None)
        model_calls += 1
        usages.append(raw.get("usage"))
        usage_report = {"usage": usages, "用量是否完整": all(
            isinstance(u, dict) and all(type(u.get(k)) is int and u[k] >= 0
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
            for u in usages)}
        assistant = response_message(raw)
        calls = assistant.get("tool_calls") or []
        if not calls:
            text = assistant.get("content")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("模型没有工具请求，也没有可展示的最终文本")
            return {**usage_report, "停止原因": "final_answer", "模型调用次数": model_calls,
                    "工具次数": len(trace), "轨迹": trace, "回复": text}
        ids = [c.get("id") if isinstance(c, dict) else None for c in calls]
        if any(not isinstance(i, str) or not i for i in ids):
            raise ValueError("工具调用缺少标识，本轮不执行")
        if len(set(ids)) != len(ids) or used_ids.intersection(ids):
            raise ValueError("工具调用标识重复，本轮不执行")
        if len(trace) + len(calls) > max_tool_calls:
            return {**usage_report, "停止原因": "tool_budget", "模型调用次数": model_calls,
                    "工具次数": len(trace), "轨迹": trace}
        messages.append(assistant)
        for call in calls:
            result = execute_tool_call(box, "U1001", call, NAMES)
            messages.append(result)
            used_ids.add(call["id"])
            trace.append({"call_id": call["id"], "name": call.get("function", {}).get("name"),
                          "result": json.loads(result["content"])})
    return {**usage_report, "停止原因": "model_budget", "模型调用次数": model_calls,
            "工具次数": len(trace), "轨迹": trace}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="显式联网调用模型服务，可能产生费用")
    parser.add_argument("--order-id", default="A1001", help="真实调用时要查询的教学订单")
    args = parser.parse_args()
    try:
        ids = [args.order_id] if args.live else ["A1001", "A1002"]
        output = {"模式": "真实模型调用" if args.live else "离线脚本决策，不代表模型能力",
                  "对照": [{"订单": oid, "固定流程": fixed_workflow(oid),
                            "受限循环": run_loop(oid, live=args.live)} for oid in ids]}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ModelAPIError, ValueError) as exc:
        parser.exit(1, f"执行未完成：{exc}\n")
