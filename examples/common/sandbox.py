"""用可核对的状态讲解查询、权限、退款申请、幂等和中断恢复。"""

from copy import deepcopy


def seed_state() -> dict:
    """返回独立的原创合成数据，金额单位为分，时间不随运行日期变化。"""
    return {
        "version": 1,
        "users": {"U1001": {"name": "小林"}, "U1002": {"name": "小周"}},
        "orders": {
            "A1001": {"order_id": "A1001", "user_id": "U1001", "status": "shipped", "amount_cents": 12900, "item": "帆布背包", "tracking_number": "T1001", "eligible": True},
            "A1002": {"order_id": "A1002", "user_id": "U1001", "status": "pending", "amount_cents": 5900, "item": "保温杯", "tracking_number": None, "eligible": True},
            "A1003": {"order_id": "A1003", "user_id": "U1002", "status": "delivered", "amount_cents": 9900, "item": "折叠伞", "tracking_number": "T1003", "eligible": True},
            "A1004": {"order_id": "A1004", "user_id": "U1001", "status": "delivered", "amount_cents": 2990, "item": "定制姓名贴", "tracking_number": "T1004", "eligible": False},
        },
        "logistics": {
            "T1001": {"tracking_number": "T1001", "status": "in_transit", "events": ["教学第1日：已揽收", "教学第2日：运输中"]},
            "T1003": {"tracking_number": "T1003", "status": "delivered", "events": ["教学第1日：已签收"]},
            "T1004": {"tracking_number": "T1004", "status": "delivered", "events": ["教学第1日：已签收"]},
        },
        "policies": [{"policy_id": "P-REFUND-1", "text": "本教学规则：eligible 为真且用户确认后，允许提交一笔不超过实付金额的退款申请。申请不等于审核通过或到账。"}],
        "refunds": {},
        "requests": {},
        "next_refund_id": 1,
    }


def _error(code: str, message: str) -> dict:
    """业务失败使用结构化返回，便于代码检查而非猜测错误文案。"""
    return {"success": False, "error": {"code": code, "message": message}}


def _text(value, limit: int = 100) -> bool:
    """只接受长度受限且非空的字符串，避免把列表等当成字典键。"""
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


class Sandbox:
    """单进程教学环境；不提供真实身份认证、并发事务或文件持久化。"""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """恢复默认种子；失败注入也一并清除，不影响其他实例。"""
        self._state = seed_state()
        self._failures = {}

    def snapshot(self) -> dict:
        """深复制业务状态与幂等记录；返回值不会直接修改运行中的环境。"""
        return deepcopy(self._state)

    @classmethod
    def from_snapshot(cls, state: dict):
        """从可信教学夹具或本程序快照恢复，不把模型输出当成快照。"""
        required = {"users", "orders", "logistics", "refunds", "requests"}
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("快照格式错误或版本不支持")
        if any(not isinstance(state.get(key), dict) for key in required):
            raise ValueError("快照缺少必要的字典字段")
        if not isinstance(state.get("policies"), list):
            raise ValueError("快照缺少政策列表")
        if type(state.get("next_refund_id")) is not int or state["next_refund_id"] < 1:
            raise ValueError("退款编号计数器必须是正整数")
        for order_id, order in state["orders"].items():
            if not isinstance(order, dict) or order.get("order_id") != order_id:
                raise ValueError("订单主键与记录不一致")
            if order.get("user_id") not in state["users"]:
                raise ValueError("订单所属用户不存在")
            if type(order.get("amount_cents")) is not int or order["amount_cents"] <= 0:
                raise ValueError("订单金额必须是正整数分")
            if type(order.get("eligible")) is not bool:
                raise ValueError("订单资格必须是布尔值")
        obj = cls()
        obj._state = deepcopy(state)
        return obj

    def inject_failure(self, operation: str, when: str = "before") -> None:
        """让下次指定操作超时一次；提交后丢回包只适用于退款申请。"""
        allowed = {"query_order", "query_logistics", "request_refund", "query_refund"}
        if operation not in allowed or when not in {"before", "after_commit"}:
            raise ValueError("失败注入的操作或时机不支持")
        if when == "after_commit" and operation != "request_refund":
            raise ValueError("只有退款写操作可以在提交后模拟丢回包")
        self._failures[operation] = when

    def _fail(self, operation: str, when: str) -> None:
        if self._failures.get(operation) == when:
            del self._failures[operation]
            raise TimeoutError(f"教学故障：{operation} 在 {when} 时模拟超时")

    def _check_order(self, user_id, order_id):
        if not _text(user_id) or not _text(order_id):
            return None, _error("INVALID_ARGUMENT", "用户标识和订单号必须是非空字符串")
        if user_id not in self._state["users"]:
            return None, _error("UNAUTHORIZED", "调用方尚未提供有效用户身份")
        order = self._state["orders"].get(order_id)
        if order is None or order["user_id"] != user_id:
            return None, _error("ORDER_NOT_ACCESSIBLE", "订单不存在或当前用户无权访问")
        return order, None

    def query_order(self, user_id: str, order_id: str) -> dict:
        """身份来自可信调用方；不能把模型生成的用户标识当成登录身份。"""
        self._fail("query_order", "before")
        order, error = self._check_order(user_id, order_id)
        return error if error else {"success": True, "order": deepcopy(order)}

    def query_logistics(self, user_id: str, order_id: str) -> dict:
        """先核对订单归属，再取物流；知道物流号本身不代表有读取权限。"""
        self._fail("query_logistics", "before")
        order, error = self._check_order(user_id, order_id)
        if error:
            return error
        tracking = order.get("tracking_number")
        record = self._state["logistics"].get(tracking)
        if record is None:
            return _error("LOGISTICS_NOT_AVAILABLE", "这笔订单尚无可用物流记录")
        return {"success": True, "logistics": deepcopy(record)}

    def query_refund(self, user_id: str, order_id: str) -> dict:
        """查询系统中的申请记录，不依赖上次工具回复是否送达。"""
        self._fail("query_refund", "before")
        order, error = self._check_order(user_id, order_id)
        if error:
            return error
        for refund in self._state["refunds"].values():
            if refund["order_id"] == order["order_id"]:
                return {"success": True, "refund": deepcopy(refund)}
        return _error("REFUND_NOT_FOUND", "系统尚无这笔订单的退款申请")

    def request_refund(self, user_id: str, order_id: str, reason: str, *,
                       request_id: str, confirmed: bool = False,
                       amount_cents: int | None = None) -> dict:
        """原子步骤的教学模拟：校验、写入申请、修改状态、记下幂等结果。"""
        self._fail("request_refund", "before")
        order, error = self._check_order(user_id, order_id)
        if error:
            return error
        if not _text(reason, 500) or not _text(request_id):
            return _error("INVALID_ARGUMENT", "退款原因和请求编号必须是非空字符串")
        if confirmed is not True:
            return _error("CONFIRMATION_REQUIRED", "写操作需要可信交互流程取得的明确确认")
        amount = order["amount_cents"] if amount_cents is None else amount_cents
        if type(amount) is not int or not 0 < amount <= order["amount_cents"]:
            return _error("INVALID_AMOUNT", "申请金额须为正整数分且不超过实付金额")
        payload = {"order_id": order_id, "reason": reason, "amount_cents": amount}
        user_requests = self._state["requests"].get(user_id, {})
        previous = user_requests.get(request_id)
        if previous is not None:
            if previous["payload"] != payload:
                return _error("IDEMPOTENCY_CONFLICT", "同一请求编号不能对应不同的业务参数")
            return {"success": True, "refund": deepcopy(previous["refund"]), "replayed": True}
        if order["eligible"] is not True:
            return _error("POLICY_DENIED", "该订单不符合本教学规则的退款申请条件")
        if any(r["order_id"] == order_id for r in self._state["refunds"].values()):
            return _error("REFUND_ALREADY_EXISTS", "该订单已有退款申请，请先查询结果")
        if order["status"] not in {"pending", "shipped", "delivered"}:
            return _error("STATE_CONFLICT", "当前订单状态不允许新建退款申请")
        refund_id = f"R{self._state['next_refund_id']:04d}"
        refund = {"refund_id": refund_id, "user_id": user_id, **payload, "request_id": request_id, "status": "requested"}
        self._state["next_refund_id"] += 1
        self._state["refunds"][refund_id] = refund
        order["status"] = "refund_pending"
        user_requests[request_id] = {"payload": deepcopy(payload), "refund": deepcopy(refund)}
        self._state["requests"][user_id] = user_requests
        self._fail("request_refund", "after_commit")
        return {"success": True, "refund": deepcopy(refund), "replayed": False}
