"""观察订单事实来自哪里：本实验使用虚构数据，不调用大模型或网络。

查询逻辑改编自 ecom-service-agent/app/agent/tools/order.py，保留了
订单不存在时的错误处理。这里的订单号和状态是独立编写的教学数据。
"""

import json


ORDERS = {"A1001": {"status": "已发货"}}


def query_order(order_id: str) -> dict:
    """从教学数据中查找订单，返回查到的记录或明确的错误。"""
    order = ORDERS.get(order_id)
    if not order:
        return {"success": False, "error": f"未找到订单 {order_id}，请核实订单号"}
    return {"success": True, "order": order}


if __name__ == "__main__":
    result = query_order("A1001")
    assert result == {"success": True, "order": {"status": "已发货"}}
    assert query_order("A9999")["success"] is False
    print(json.dumps(result, ensure_ascii=False, indent=2))
