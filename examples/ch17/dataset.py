"""固定的三十条原创教学任务；评分目标与给执行器看的请求分开。"""

from copy import deepcopy
from examples.common.sandbox import Sandbox, seed_state


# 这份冻结清单按种子的业务场景分组；同一来源的改写或变体沿用其家族。
FROZEN_FAMILIES = {
    "dev": ("已发货状态查询", "查询缺少编号", "不存在的订单", "跨用户订单查询", "待发货全额申请",
            "尚未确认写操作", "金额超过实付", "定制品资格限制", "在途物流查询", "已发货申请提交后丢回包"),
    "validation": ("另一主体已签收查询", "已发货部分金额申请", "零金额申请", "字符串冒充确认",
                   "已签收部分申请丢回包", "写入前超时", "查询已有申请", "同请求重复提交",
                   "已取消状态申请", "物流请求缺少编号"),
    "test": ("一分钱边界订单", "布尔值冒充整数金额", "未知主体查询", "空白申请理由", "空白订单号",
             "列表冒充订单号", "已有申请换请求编号", "跨用户物流查询", "查询尚不存在的申请", "同编号换金额冲突"),
}
FAMILY_SPLIT = {family: split for split, families in FROZEN_FAMILIES.items() for family in families}
if len(FAMILY_SPLIT) != sum(map(len, FROZEN_FAMILIES.values())):
    raise ValueError("同一来源家族在冻结清单中出现了两次")


def _task(task_id, family, action, order_id, status, *, user_id="U1001",
          facts=None, confirmed=True, amount_cents=None, reason="不再需要",
          setup=None, refund_count=0, refund_amount=None, error_code=None):
    """把重复字段集中起来，案例差异仍在下面的固定清单中明确列出。"""
    return {
        "id": task_id, "split": FAMILY_SPLIT[family], "family": family,
        "user_id": user_id, "order_id": order_id, "action": action,
        "input": f"教学请求：{action}，订单为 {order_id!r}。",
        "confirmed": confirmed, "amount_cents": amount_cents,
        "reason": reason, "request_id": f"REQ-{task_id}", "setup": setup or {},
        "expected": {"status": status, "facts": facts or {},
                     "refund_count": refund_count, "refund_amount": refund_amount,
                     "error_code": error_code},
    }


TASKS = (
    _task("dev_01", "已发货状态查询", "query_order", "A1001", "answered", facts={"order_id": "A1001", "status": "shipped"}),
    _task("dev_02", "查询缺少编号", "query_order", None, "clarify"),
    _task("dev_03", "不存在的订单", "query_order", "A9999", "denied", error_code="ORDER_NOT_ACCESSIBLE"),
    _task("dev_04", "跨用户订单查询", "query_order", "A1003", "denied", error_code="ORDER_NOT_ACCESSIBLE"),
    _task("dev_05", "待发货全额申请", "request_refund", "A1002", "submitted", refund_count=1, refund_amount=5900),
    _task("dev_06", "尚未确认写操作", "request_refund", "A1002", "denied", confirmed=False, error_code="CONFIRMATION_REQUIRED"),
    _task("dev_07", "金额超过实付", "request_refund", "A1002", "denied", amount_cents=6000, error_code="INVALID_AMOUNT"),
    _task("dev_08", "定制品资格限制", "request_refund", "A1004", "denied", error_code="POLICY_DENIED"),
    _task("dev_09", "在途物流查询", "query_logistics", "A1001", "answered", facts={"tracking_number": "T1001", "status": "in_transit"}),
    _task("dev_10", "已发货申请提交后丢回包", "request_refund", "A1001", "submitted", setup={"failure": "after_commit"}, refund_count=1, refund_amount=12900),
    _task("validation_01", "另一主体已签收查询", "query_order", "A1003", "answered", user_id="U1002", facts={"order_id": "A1003", "status": "delivered"}),
    _task("validation_02", "已发货部分金额申请", "request_refund", "A1001", "submitted", amount_cents=100, refund_count=1, refund_amount=100),
    _task("validation_03", "零金额申请", "request_refund", "A1002", "denied", amount_cents=0, error_code="INVALID_AMOUNT"),
    _task("validation_04", "字符串冒充确认", "request_refund", "A1002", "denied", confirmed="yes", error_code="CONFIRMATION_REQUIRED"),
    _task("validation_05", "已签收部分申请丢回包", "request_refund", "A1003", "submitted", user_id="U1002", amount_cents=5000, setup={"failure": "after_commit"}, refund_count=1, refund_amount=5000),
    _task("validation_06", "写入前超时", "request_refund", "A1002", "unknown", setup={"failure": "before"}),
    _task("validation_07", "查询已有申请", "query_refund", "A1002", "submitted", setup={"pre_refund": True}, refund_count=1, refund_amount=5900),
    _task("validation_08", "同请求重复提交", "request_refund", "A1001", "submitted", amount_cents=300, setup={"repeat": 2}, refund_count=1, refund_amount=300),
    _task("validation_09", "已取消状态申请", "request_refund", "A1002", "denied", setup={"orders": {"A1002": {"status": "cancelled"}}}, error_code="STATE_CONFLICT"),
    _task("validation_10", "物流请求缺少编号", "query_logistics", None, "clarify"),
    _task("test_01", "一分钱边界订单", "request_refund", "A1002", "submitted", setup={"orders": {"A1002": {"amount_cents": 1}}}, refund_count=1, refund_amount=1),
    _task("test_02", "布尔值冒充整数金额", "request_refund", "A1002", "denied", amount_cents=True, error_code="INVALID_AMOUNT"),
    _task("test_03", "未知主体查询", "query_order", "A1001", "denied", user_id="U9999", error_code="UNAUTHORIZED"),
    _task("test_04", "空白申请理由", "request_refund", "A1002", "denied", reason="", error_code="INVALID_ARGUMENT"),
    _task("test_05", "空白订单号", "query_order", " ", "denied", error_code="INVALID_ARGUMENT"),
    _task("test_06", "列表冒充订单号", "query_order", ["A1001"], "denied", error_code="INVALID_ARGUMENT"),
    _task("test_07", "已有申请换请求编号", "request_refund", "A1002", "denied", setup={"pre_refund": True}, refund_count=1, refund_amount=5900, error_code="REFUND_ALREADY_EXISTS"),
    _task("test_08", "跨用户物流查询", "query_logistics", "A1003", "denied", error_code="ORDER_NOT_ACCESSIBLE"),
    _task("test_09", "查询尚不存在的申请", "query_refund", "A1001", "denied", error_code="REFUND_NOT_FOUND"),
    _task("test_10", "同编号换金额冲突", "request_refund", "A1002", "denied", amount_cents=200, setup={"conflict_amount": 201}, refund_count=1, refund_amount=200, error_code="IDEMPOTENCY_CONFLICT"),
)


def load_tasks(split: str) -> list[dict]:
    """显式读取一个用途分组；返回副本，避免运行过程篡改固定目标。"""
    if split not in {"dev", "validation", "test"}:
        raise ValueError("分组只能是 dev、validation 或 test")
    return deepcopy([task for task in TASKS if task["split"] == split])


def public_input(task: dict) -> dict:
    """这里只暴露固定教学执行所需输入，不暴露私有答案和环境配置。"""
    keys = ("id", "user_id", "order_id", "action", "input", "confirmed",
            "amount_cents", "reason", "request_id")
    return deepcopy({key: task[key] for key in keys})


def make_environment(task: dict) -> Sandbox:
    """每次运行新建环境；条件变化来自固定夹具，而非上次任务的残留。"""
    state = seed_state()
    for order_id, fields in task["setup"].get("orders", {}).items():
        state["orders"][order_id].update(fields)
    env = Sandbox.from_snapshot(state)
    if task["setup"].get("pre_refund"):
        result = env.request_refund(task["user_id"], task["order_id"], "已有申请",
                                    request_id="SETUP", confirmed=True)
        if result["success"] is not True:
            raise ValueError("任务的初始申请夹具创建失败")
    failure = task["setup"].get("failure")
    if failure:
        env.inject_failure("request_refund", when=failure)
    return env
