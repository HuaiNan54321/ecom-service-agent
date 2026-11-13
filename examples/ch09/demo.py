"""第09章：展示工具请求、真实本地查询与回包配对；默认模型消息为离线预设。"""

import argparse
import json
import re

from examples.common import Sandbox
from examples.common.llm import ModelAPIError, chat_completion


DESCRIPTIONS = {
    "query_order": "按订单号查询当前用户的订单状态；不修改订单。",
    "query_logistics": "按订单号查询当前用户的物流；未发货时可能没有物流。",
}


def tool_definitions(names=("query_order",)):
    """仅声明调用方选择的只读工具，不把用户身份暴露为模型参数。"""
    return [{
        "type": "function",
        "function": {
            "name": name,
            "description": DESCRIPTIONS[name],
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    } for name in names]


def tool_request(name, order_id, call_id):
    """构造作者预设的消息，用于离线观察协议，不表示一次模型实测。"""
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function", "function": {
            "name": name,
            "arguments": json.dumps({"order_id": order_id}),
        },
    }]}


def offline_response(message):
    """将预设助理消息装进 Chat Completions 响应的常用结构。"""
    return {"choices": [{"message": message, "finish_reason":
                         "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": None}


def failure(code, message):
    """保持应用错误和共享模拟环境的错误结构一致。"""
    return {"success": False, "error": {"code": code, "message": message}}


def execute_tool_call(box, user_id, call, allowed_names=("query_order",)):
    """验证不可信请求后分发；身份由应用传入，不从模型参数读取。"""
    if not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]:
        raise ValueError("工具请求缺少可配对的调用标识")
    function = call.get("function")
    if call.get("type") != "function" or not isinstance(function, dict):
        result = failure("INVALID_CALL", "工具请求结构不正确")
    elif function.get("name") not in allowed_names or function.get("name") not in DESCRIPTIONS:
        result = failure("UNKNOWN_TOOL", "当前步骤没有开放这个工具")
    else:
        raw = function.get("arguments")
        try:
            if not isinstance(raw, str) or len(raw) > 2048:
                raise ValueError("参数必须是长度受限的 JSON 文本")
            args = json.loads(raw)
            if not isinstance(args, dict) or set(args) != {"order_id"}:
                raise ValueError("参数只能包含 order_id")
            order_id = args["order_id"]
            if not isinstance(order_id, str) or not re.fullmatch(r"A\d{4}", order_id):
                raise ValueError("教学订单号格式为 A 加四位数字")
        except (ValueError, TypeError) as exc:
            result = failure("INVALID_ARGUMENTS", str(exc))
        else:
            # 工具映射由程序固定，不使用 eval 执行模型提供的文本。
            handlers = {"query_order": box.query_order,
                        "query_logistics": box.query_logistics}
            try:
                result = handlers[function["name"]](user_id, order_id)
            except TimeoutError:
                result = failure("TIMEOUT", "查询超时，尚未取得可用结果")
    return {"role": "tool", "tool_call_id": call["id"],
            "content": json.dumps(result, ensure_ascii=False)}


def response_message(raw):
    """先检查响应是否完整，避免把截断消息当作可执行的工具请求。"""
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("响应缺少 choices[0]")
    choice = choices[0]
    if choice.get("finish_reason") in {"length", "content_filter"}:
        raise ValueError("响应被截断或过滤，本轮不执行工具")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("响应没有合法的 assistant 消息")
    if message.get("refusal"):
        raise ValueError("模型拒绝了本次请求")
    calls = message.get("tool_calls")
    if calls is not None and not isinstance(calls, list):
        raise ValueError("tool_calls 必须是列表")
    return message


def run(live=False):
    """完整演示两次模型请求之间的一次只读工具执行。"""
    box = Sandbox()
    messages = [{"role": "system", "content": "查询订单必须使用工具；只依据结果回答。"},
                {"role": "user", "content": "请查一下订单 A1001 的状态。"}]
    raw = chat_completion(messages, live=live, tools=tool_definitions(),
                          offline_response=None if live else offline_response(
                              tool_request("query_order", "A1001", "call_order_01")))
    assistant = response_message(raw)
    messages.append(assistant)
    calls = assistant.get("tool_calls") or []
    if len(calls) > 1:
        raise ValueError("本章只允许执行一次工具请求，请使用第10章的受限循环")
    if not calls:
        return {"模式": "真实模型调用" if live else "离线预设模型消息",
                "模型调用次数": 1, "工具执行次数": 0,
                "说明": "模型没有请求查询，不能据此证明订单状态已核对。",
                "最终消息": assistant, "usage": raw.get("usage")}
    tool_message = execute_tool_call(box, "U1001", calls[0])
    messages.append(tool_message)
    data = json.loads(tool_message["content"])
    fixed_text = (f"订单 A1001 的状态是 {data['order']['status']}。"
                  if data.get("success") else "本次未取得可用订单记录。")
    raw_final = chat_completion(messages, live=live, tool_choice="none",
                                tools=tool_definitions(),
                                offline_response=None if live else offline_response(
                                    {"role": "assistant", "content": fixed_text}))
    final = response_message(raw_final)
    if final.get("tool_calls"):
        raise ValueError("已进入回答阶段，不再执行额外工具")
    return {"模式": "真实模型调用" if live else "离线预设模型消息",
            "模型调用次数": 2, "工具执行次数": 1,
            "工具请求": assistant, "工具回包": tool_message,
            "最终消息": final, "usage": [raw.get("usage"), raw_final.get("usage")]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="显式使用环境变量配置的模型服务，可能产生费用")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.live), ensure_ascii=False, indent=2))
    except (ModelAPIError, ValueError) as exc:
        parser.exit(1, f"调用未完成：{exc}\n")
