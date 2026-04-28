from tools.mock_data import ORDERS


def apply_refund(order_id: str, reason: str) -> dict:
    """为指定订单申请退款，需提供退款原因。"""
    order = ORDERS.get(order_id)
    if not order:
        return {"success": False, "error": f"未找到订单 {order_id}，请核实订单号"}

    if order["status"] == "refund_processing":
        return {"success": False, "error": "该订单已有退款申请正在处理中，请耐心等待"}

    if order["status"] == "pending":
        return {
            "success": True,
            "message": (
                f"订单 {order_id} 尚未发货，已直接取消并发起退款。"
                f"退款原因：{reason}。退款将在 1-3 个工作日内原路退回。"
            ),
        }

    return {
        "success": True,
        "message": (
            f"退款申请已提交。订单 {order_id}，退款原因：{reason}。"
            f"预计 1-3 个工作日内审核完成，届时会通知您退货地址。"
        ),
    }
