"""客服的退款检查点和模拟业务账本。模型准备草案，顾客确认后由宿主登记。"""

import re
import sqlite3
from contextlib import closing, contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.agent.tools.mock_data import ORDERS
from app.agent.tools.logistics import query_logistics
from app.agent.tools.user_orders import STATUS_LABELS


def _error(message, status="rejected"):
    return {"success": False, "status": status, "message": message, "error": message}


def apply_refund(order_id: str, reason: str) -> dict:
    """独立工具调用没有已绑定的顾客会话，不能提交退款。"""
    return _error("请通过客服会话申请退款，并由订单本人确认。")


class RefundLedger:
    """同一目录共享模拟订单的退款记录；确认与待回复的回执归属于各自会话。"""

    def __init__(self, session_path, user_id):
        session = Path(session_path).resolve()
        self.path = session.parent / "refunds.sqlite3"
        self.session = session.name
        self.owner = "小明" if user_id == "default" else user_id

    @contextmanager
    def _db(self, write=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.executescript("""
                CREATE TABLE IF NOT EXISTS refund_requests (
                    request_id TEXT PRIMARY KEY, session TEXT NOT NULL, owner TEXT NOT NULL,
                    order_id TEXT NOT NULL, amount_cents INTEGER NOT NULL, reason TEXT NOT NULL,
                    phase TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS refunds (
                    order_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    owner TEXT NOT NULL, amount_cents INTEGER NOT NULL, reason TEXT NOT NULL
                );
            """)
            with db:
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db

    @staticmethod
    def _result(row, status):
        """回复由已保存的意图和回执生成，避免模型把草案说成已退款。"""
        ref, order, cents = row["request_id"], row["order_id"], row["amount_cents"]
        amount = f"{cents // 100}.{cents % 100:02d}"
        messages = {
            "awaiting_confirmation": (
                f"待确认：订单 {order} 的整单退款申请，金额 {amount} 元，原因「{row['reason']}」。"
                f"同意登记请输入「确认退款 {ref}」，放弃请输入「取消退款 {ref}」。"
            ),
            "approved": f"订单 {order} 的确认已保存，尚未查到 {ref} 的业务回执。请核对后使用「确认退款 {ref}」继续。",
            "submitted": f"已查到订单 {order} 的退款申请 {ref}，金额 {amount} 元，当前为退款处理中。",
            "cancelled": f"已取消订单 {order} 的退款草案 {ref}。",
            "superseded": f"订单 {order} 已有另一笔申请，草案 {ref} 未重复提交。",
        }
        return {"status": status, "success": status in {"submitted", "cancelled"},
                "request_id": ref, "order_id": order, "amount_cents": cents,
                "reason": row["reason"], "message": messages[status]}

    def _owned(self, order_id):
        order = ORDERS.get(order_id) if isinstance(order_id, str) else None
        return order if order and order["user"] == self.owner else None

    def _request(self, db, ref):
        return db.execute("SELECT * FROM refund_requests WHERE request_id=? AND session=? AND owner=?",
                          (ref, self.session, self.owner)).fetchone()

    def _progress(self, db, row):
        """顾客查询进度、进程恢复时，都用真实业务申请核对检查点。"""
        phase = row["phase"]
        if phase not in {"approved", "submitted"}:
            return self._result(row, phase)
        receipt = db.execute("SELECT * FROM refunds WHERE order_id=?", (row["order_id"],)).fetchone()
        if receipt is None and phase == "approved":
            return self._result(row, "approved")
        if receipt and phase == "approved" and receipt["request_id"] != row["request_id"]:
            return self._result(row, "superseded")
        fields = ("request_id", "owner", "amount_cents", "reason")
        if receipt and all(receipt[k] == row[k] for k in fields):
            return self._result(row, "submitted")
        return _error("申请检查点与业务回执不一致，请人工核对。")

    def prepare(self, order_id, reason):
        order = self._owned(order_id)
        if not order:
            return _error("找不到当前顾客名下的这笔订单。")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200 or not reason.isprintable():
            return _error("请提供不超过 200 字的单行退款原因。")
        if order["status"] != "pending":
            note = {"shipped": "在途订单需待签收后申请退货，或选择拒收。",
                    "delivered": "已签收商品请先按退货政策核对资格，再联系售后办理。",
                    "refund_processing": "该订单已有退款申请在处理中。"}
            return _error(note.get(order["status"], "此订单状态不支持直接申请退款。"))
        reason = reason.strip()
        cents = int(Decimal(str(order["total"])) * 100)
        with self._db(write=True) as db:
            if db.execute("SELECT 1 FROM refunds WHERE order_id=?", (order_id,)).fetchone():
                return _error("该订单已有退款申请在处理中，请查询订单进度。", "already_submitted")
            row = db.execute("""SELECT * FROM refund_requests WHERE session=? AND owner=? AND order_id=?
                                AND phase IN ('awaiting_confirmation','approved')""",
                             (self.session, self.owner, order_id)).fetchone()
            if row:
                if row["reason"] != reason or row["amount_cents"] != cents:
                    return _error(f"此订单已有待处理的草案，请先查询「退款进度 {row['request_id']}」。")
                return self._result(row, row["phase"])
            ref = "RF-" + uuid4().hex[:12]
            db.execute("""INSERT INTO refund_requests
                       (request_id,session,owner,order_id,amount_cents,reason,phase)
                       VALUES (?,?,?,?,?,?,'awaiting_confirmation')""",
                       (ref, self.session, self.owner, order_id, cents, reason))
            return self._result(self._request(db, ref), "awaiting_confirmation")

    def _submit(self, ref):
        """业务提交与回执同一事务；顾客确认后即使两个进程同时执行也只登记一次。"""
        with self._db(write=True) as db:
            row = self._request(db, ref)
            receipt = db.execute("SELECT * FROM refunds WHERE order_id=?", (row["order_id"],)).fetchone()
            if receipt:
                if receipt["request_id"] != ref:
                    db.execute("UPDATE refund_requests SET phase='superseded' WHERE request_id=?", (ref,))
                    return self._result(row, "superseded")
                if any(receipt[k] != row[k] for k in ("owner", "amount_cents", "reason")):
                    return _error("已登记的记录与确认信息不匹配，请人工核对。")
            elif row["phase"] == "approved":
                order = self._owned(row["order_id"])
                if not order or order["status"] != "pending" or int(Decimal(str(order["total"])) * 100) != row["amount_cents"]:
                    return _error("订单状态、归属或金额发生变化，请人工核对。")
                db.execute("INSERT INTO refunds VALUES (?,?,?,?,?)",
                           tuple(row[k] for k in ("order_id", "request_id", "owner", "amount_cents", "reason")))
            else:
                return _error("未找到已授权且可核对的退款记录，请人工核对。")
            db.execute("UPDATE refund_requests SET phase='submitted' WHERE request_id=?", (ref,))
            return self._result(row, "submitted")

    def handle_user_input(self, text):
        """只接受聊天入口交过来的整条顾客命令，工具参数没有确认权限。"""
        cmd = text.strip()
        parts = cmd.split()
        if not parts or parts[0] not in {"确认退款", "取消退款", "退款进度"}:
            return None
        if len(parts) != 2 or not re.fullmatch(r"RF-[0-9a-f]{12}", parts[1]):
            return _error("请带上待确认草案中的完整请求号，如「确认退款 RF-xxxxxxxxxxxx」。")
        action, ref = parts
        if not self.path.is_file():
            return _error("本会话找不到这条退款申请。")
        with self._db(write=action != "退款进度") as db:
            row = self._request(db, ref)
            if not row:
                return _error("本会话找不到这条退款申请。")
            if action == "退款进度" or row["phase"] == "superseded":
                return self._progress(db, row)
            if action == "取消退款":
                if row["phase"] in {"approved", "submitted"}:
                    return _error("此申请已获确认，请先核对申请进度。")
                db.execute("UPDATE refund_requests SET phase='cancelled' WHERE request_id=?", (ref,))
                return self._result(row, "cancelled")
            if row["phase"] == "cancelled":
                return _error("草案已取消，请重新发起申请。")
            if row["phase"] == "awaiting_confirmation":
                db.execute("UPDATE refund_requests SET phase='approved' WHERE request_id=?", (ref,))
        return self._submit(ref)

    def pending(self):
        if not self.path.is_file():
            return []
        with self._db() as db:
            rows = db.execute("""SELECT * FROM refund_requests
                WHERE session=? AND owner=? AND phase='awaiting_confirmation' ORDER BY rowid""",
                              (self.session, self.owner))
            return [self._result(row, row["phase"]) for row in rows]

    def recover(self):
        """只核对既有申请；无回执时保持原请求，不能在启动时重做写操作。"""
        if not self.path.is_file():
            return []
        with self._db() as db:
            rows = db.execute("""SELECT * FROM refund_requests WHERE session=? AND owner=?
                AND phase IN ('approved','submitted') AND notified=0 ORDER BY rowid""", (self.session, self.owner))
            return [self._progress(db, row) for row in rows]

    def acknowledge(self, request_id):
        """宿主保存或交付回执后才标记已告知。"""
        if self.path.is_file():
            with self._db(write=True) as db:
                db.execute("""UPDATE refund_requests SET notified=1
                    WHERE request_id=? AND session=? AND owner=? AND phase='submitted'""",
                           (request_id, self.session, self.owner))

    def cancel_pending(self):
        if self.path.is_file():
            with self._db(write=True) as db:
                db.execute("""UPDATE refund_requests SET phase='cancelled'
                    WHERE session=? AND owner=? AND phase='awaiting_confirmation'""", (self.session, self.owner))

    def query_order(self, order_id):
        order = self._owned(order_id)
        if not order:
            return _error("找不到当前顾客名下的这笔订单。")
        order = dict(order)
        if self.path.is_file():
            with self._db() as db:
                row = db.execute("SELECT * FROM refunds WHERE order_id=? AND owner=?",
                                 (order_id, self.owner)).fetchone()
                if row:
                    order.update(status="refund_processing", refund_status="已登记，待处理",
                                 refund_request_id=row["request_id"], refund_amount_cents=row["amount_cents"])
        return {"success": True, "order": order}

    def query_logistics(self, order_id):
        return query_logistics(order_id) if self._owned(order_id) else _error("找不到当前顾客名下的这笔订单。")

    def list_user_orders(self):
        orders = []
        for order_id, seed in ORDERS.items():
            if seed["user"] == self.owner:
                o = self.query_order(order_id)["order"]
                orders.append({"order_id": order_id, "status": STATUS_LABELS.get(o["status"], o["status"]),
                               "items_summary": "、".join(i["name"] for i in o["items"]),
                               "total": o["total"], "created_at": o["created_at"]})
        return {"success": True, "count": len(orders), "orders": orders}
