"""第11章：本地模拟退款申请的权限、幂等和提交后回包丢失。"""

import json

from examples.common import Sandbox


def run():
    """所有数据均虚构；确认标记由应用传入，不由模型生成。"""
    box = Sandbox()
    foreign = box.request_refund("U1001", "A1003", "尺寸不合适",
                                 request_id="req_foreign", confirmed=True)
    unconfirmed = box.request_refund("U1001", "A1002", "不再需要",
                                     request_id="req_unconfirmed", confirmed=False)
    before = box.query_refund("U1001", "A1002")
    # 模拟用户已在应用确认这笔订单、本次原因和全额申请。
    trusted_confirmation = True
    box.inject_failure("request_refund", when="after_commit")
    timed_out = False
    try:
        box.request_refund("U1001", "A1002", "不再需要",
                           request_id="req_001", confirmed=trusted_confirmation)
    except TimeoutError:
        timed_out = True
    # 回包丢失只代表调用方不知道结果，先从权威状态查询是否已经提交。
    after_timeout = box.query_refund("U1001", "A1002")
    restored = Sandbox.from_snapshot(box.snapshot())
    replay = restored.request_refund("U1001", "A1002", "不再需要",
                                     request_id="req_001", confirmed=True)
    changed = restored.request_refund("U1001", "A1002", "改成另一条原因",
                                      request_id="req_001", confirmed=True)
    order = restored.query_order("U1001", "A1002")
    return {"模式": "离线状态实验，无模型和真实资金流转",
            "查询他人订单的退款": foreign,
            "未确认申请": unconfirmed, "提交前申请存在": before["success"],
            "收到超时": timed_out, "超时后查询": after_timeout,
            "恢复后原请求重放": replay, "同键改变参数": changed,
            "最终订单状态": order["order"]["status"]}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
