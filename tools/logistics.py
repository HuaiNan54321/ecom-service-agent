from tools.mock_data import LOGISTICS, ORDERS


def query_logistics(order_id: str) -> dict:
    """根据订单号查询物流轨迹信息。"""
    order = ORDERS.get(order_id)
    if not order:
        return {"success": False, "error": f"未找到订单 {order_id}，请核实订单号"}

    tracking_number = order.get("tracking_number")
    if not tracking_number:
        return {"success": False, "error": "该订单尚未发货，暂无物流信息"}

    logistics = LOGISTICS.get(tracking_number)
    if not logistics:
        return {"success": False, "error": f"物流单号 {tracking_number} 暂无轨迹信息"}

    return {"success": True, "logistics": logistics}
