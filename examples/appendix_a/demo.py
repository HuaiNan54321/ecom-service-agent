"""用一组虚构订单串起 Python 容器、函数、分支、循环、JSON 与文件操作。"""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


ORDERS = {
    "A1001": {"status": "shipped", "amount_cents": 12900},
    "A1002": {"status": "pending", "amount_cents": 5900},
}


def lookup(order_id: str) -> dict:
    """类型标注帮助阅读；具体输入是否正确，仍由代码判断。"""
    if not isinstance(order_id, str):
        raise ValueError("订单号必须是字符串")
    order = ORDERS.get(order_id)
    if order is None:
        return {"success": False, "error": "未找到订单"}
    return {"success": True, "order": dict(order)}


def main():
    """文件只写到自动清理的临时目录，不覆盖读者自己的数据。"""
    print("查询结果:", lookup("A1001"))
    pending = []
    for order_id, order in ORDERS.items():
        if order["status"] == "pending":
            pending.append(order_id)
    assert pending == ["A1002"]
    assert lookup("A9999")["success"] is False
    print("待发货订单:", pending)
    text = json.dumps(ORDERS, ensure_ascii=False, indent=2)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "orders.json"
        path.write_text(text, encoding="utf-8")
        restored = json.loads(path.read_text(encoding="utf-8"))
        assert restored == ORDERS
    print("JSON 写入后读取，数据一致:", restored == ORDERS)
    try:
        json.loads('{"status":}')
    except json.JSONDecodeError:
        print("已捕获无效 JSON，未把解析失败当成成功")
    else:
        raise AssertionError("错误样本本应触发解析失败")
    try:
        lookup(1001)
    except ValueError:
        pass
    else:
        raise AssertionError("非字符串订单号必须被拒绝")
    configured = bool(os.environ.get("AGENTBOOK_API_KEY"))
    print("API Key：" + ("已配置" if configured else "未配置，离线示例仍可运行"))


if __name__ == "__main__":
    main()
