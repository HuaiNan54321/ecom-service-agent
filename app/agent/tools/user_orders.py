from app.agent.tools.mock_data import ORDERS

STATUS_LABELS = {
    "pending": "待发货",
    "shipped": "已发货",
    "delivered": "已签收",
    "refund_processing": "退款中",
}


def list_user_orders() -> dict:
    """查询当前用户的所有订单概要列表。"""
    orders = [
        {
            "order_id": o["order_id"],
            "status": STATUS_LABELS.get(o["status"], o["status"]),
            "items_summary": "、".join(item["name"] for item in o["items"]),
            "total": o["total"],
            "created_at": o["created_at"],
        }
        for o in ORDERS.values()
    ]
    return {"success": True, "count": len(orders), "orders": orders}
