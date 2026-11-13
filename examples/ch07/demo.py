"""第 7 章：JSON 语法、字段合同和业务依据分别检查。"""

import argparse
import json
import re

from examples.ch05.demo import read_answer
from examples.common.llm import ModelAPIError, chat_completion


INTENTS = {"查询物流", "申请退货", "其他"}
SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": sorted(INTENTS)},
        "order_id": {"type": ["string", "null"]},
    },
    "required": ["intent", "order_id"],
    "additionalProperties": False,
}


def parse_json(raw: str) -> dict:
    """限制输入长度并解析严格 JSON；拒绝额外的非标准数值。"""
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError("输入不是文本或超过本例长度上限")

    def reject_constant(value: str) -> None:
        raise ValueError(f"非标准 JSON 数值：{value}")

    return json.loads(raw, parse_constant=reject_constant)


def validate_shape(data: object) -> dict:
    """手写本例的两字段合同检查，不实现通用 JSON Schema 校验器。"""
    if not isinstance(data, dict) or set(data) != {"intent", "order_id"}:
        raise ValueError("必须且只能包含 intent、order_id 两个字段")
    if not isinstance(data["intent"], str) or data["intent"] not in INTENTS:
        raise ValueError("intent 必须是三个允许的字符串之一")
    order_id = data["order_id"]
    if order_id is not None and not isinstance(order_id, str):
        raise ValueError("order_id 必须是字符串或 null")
    return data


def validate_business(data: dict, question: str, visible_ids: set[str]) -> dict:
    """提取值要有原文依据，并处在可信身份对应的可访问集合内。"""
    order_id = data["order_id"]
    mentioned = set(re.findall(r"(?<![A-Za-z0-9])A[0-9]{4}(?![A-Za-z0-9])", question))
    if order_id is None:
        if mentioned:
            raise ValueError("原文提供了订单号，提取结果却遗漏了")
        return data
    if order_id not in mentioned:
        raise ValueError("订单号不是用户本次明确提供的编号")
    if order_id not in visible_ids:
        raise ValueError("该身份无权访问此订单")
    return data


def inspect(raw: str, question: str) -> tuple[str, str]:
    """返回失败层级，用于解释每一层负责什么。"""
    try:
        data = parse_json(raw)
    except (ValueError, json.JSONDecodeError):
        return "JSON 语法", "文本不是本例可接收的标准 JSON"
    try:
        data = validate_shape(data)
    except ValueError as error:
        return "字段合同", str(error)
    try:
        validate_business(data, question, {"A1001"})
    except ValueError as error:
        return "业务依据", str(error)
    return "通过", "本例三层检查通过"


def main() -> None:
    """默认检查四个固定样本；真实模式请求模型返回结构化结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="显式调用支持结构化输出的模型")
    args = parser.parse_args()
    question = "请查订单 A1001 到哪了"
    if args.live:
        try:
            response = chat_completion(
                [{"role": "system", "content": "提取意图和原文订单号；缺订单号用 null。"},
                 {"role": "user", "content": question}],
                live=True,
                response_format={"type": "json_schema", "json_schema": {
                    "name": "order_intent", "strict": True, "schema": SCHEMA,
                }},
            )
            raw = read_answer(response)
        except (ModelAPIError, ValueError) as error:
            parser.exit(1, f"结构化调用未完成：{error}\n")
        print("真实模型输出：", raw)
        print("本地检查：", inspect(raw, question))
        return
    samples = {
        "语法错误": '{"intent":"查询物流",}',
        "类型错误": '{"intent":"查询物流","order_id":1001}',
        "内容错误": '{"intent":"查询物流","order_id":"A2001"}',
        "正确提取": '{"intent":"查询物流","order_id":"A1001"}',
    }
    print("性质：人工编写的校验样本，未调用模型")
    for label, raw in samples.items():
        print(label, "→", " / ".join(inspect(raw, question)))


if __name__ == "__main__":
    assert inspect('{"intent":"查询物流","order_id":"A1001"}', "查 A1001")[0] == "通过"
    assert inspect('{"intent":"查询物流","order_id":"A1001"}', "查订单A1001")[0] == "通过"
    assert inspect('{"intent":"查询物流","order_id":"A2001"}', "查 A1001")[0] == "业务依据"
    assert inspect('{"intent":"查询物流","order_id":"A2001"}', "查 A2001")[0] == "业务依据"
    assert inspect('{"intent":"查询物流","order_id":1001}', "查 A1001")[0] == "字段合同"
    assert inspect('{"intent":"其他","order_id":null}', "你好")[0] == "通过"
    assert inspect('{"intent":"查询物流"}', "查 A1001")[0] == "字段合同"
    assert inspect('{"intent":"未知","order_id":null}', "你好")[0] == "字段合同"
    assert inspect('{"intent":"查询物流","order_id":null}', "查 A1001")[0] == "业务依据"
    main()
