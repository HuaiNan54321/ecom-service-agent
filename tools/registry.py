"""工具注册表：OpenAI function calling schema + 分发执行"""

import json
from typing import Callable

from tools.order import query_order
from tools.product import query_product
from tools.logistics import query_logistics
from tools.refund import apply_refund

_TOOL_MAP: dict[str, Callable] = {
    "query_order": query_order,
    "query_product": query_product,
    "query_logistics": query_logistics,
    "apply_refund": apply_refund,
}

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "根据订单号查询订单详情，包括订单状态、商品信息、金额、物流单号等",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，例如 ORD-20240115-001",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_product",
            "description": "根据商品名称关键词或商品ID查询商品信息，包括价格、库存、规格等。支持模糊搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "商品名称关键词或商品ID，例如「耳机」「运动鞋」「SHOE-270-BK-42」",
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_logistics",
            "description": "根据订单号查询物流轨迹信息，包括快递公司、运单号、运输状态和轨迹事件",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，例如 ORD-20240115-001",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_refund",
            "description": "为指定订单申请退款。注意：这是一个敏感操作，调用前应先与用户确认",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "要退款的订单号",
                    },
                    "reason": {
                        "type": "string",
                        "description": "退款原因，例如「尺码不合适」「质量问题」「不想要了」",
                    },
                },
                "required": ["order_id", "reason"],
            },
        },
    },
]


def execute_tool(name: str, arguments: dict) -> str:
    """根据工具名称分发执行，返回 JSON 字符串结果。"""
    func = _TOOL_MAP.get(name)
    if not func:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    try:
        result = func(**arguments)
    except Exception as e:
        result = {"error": f"工具执行出错: {e}"}
    return json.dumps(result, ensure_ascii=False)
