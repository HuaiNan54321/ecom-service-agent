"""单客服和多客服共用的聊天回合、确认回执和会话持久化。"""

import hashlib
import json
from pathlib import Path

from app.agent.storage import delete_session, load_session, save_session
from app.agent.tools.refund import RefundLedger
from app.config.settings import settings
from app.schemas.response import CustomerServiceResponse, IntentType


def run_requested_tool(manager, call, print_action) -> str:
    """模型只提供工具参数。用户确认只从聊天入口接收。"""
    name = call.function.name
    try:
        args = json.loads(call.function.arguments)
        if not isinstance(args, dict):
            raise ValueError
    except (ValueError, TypeError):
        return json.dumps({"success": False, "error": "工具参数必须是有效的 JSON 对象。"}, ensure_ascii=False)
    print_action(name, args)
    try:
        return manager.execute_tool(name, args)
    except Exception:
        # 一个工具暂时不可用时，也要给这次调用补齐观察结果，后续对话才能继续。
        return json.dumps({"success": False, "error": f"暂时无法核对 {name} 的结果，请稍后查询。"}, ensure_ascii=False)


def refund_reply(records: list[dict]) -> CustomerServiceResponse:
    """显示宿主生成的草案、拒绝原因或业务回执，不让模型改写金额和确认口令。"""
    messages = [row.get("message") or row.get("error") or "未取得可核对的退款结果。" for row in records]
    result = CustomerServiceResponse(
        intent=IntentType.RETURN_REQUEST,
        confidence=1.0,
        reply="\n".join(messages),
        requires_human=any(row.get("requires_human") for row in records),
    )
    result._receipt_ids = tuple(row["request_id"] for row in records if row.get("status") == "submitted")
    return result


class ChatSession:
    """两种客服共用同一退款确认边界；各自实现模型调用与历史摘要。"""

    def _bind_session(self, path: str | None, user_id: str) -> None:
        base = Path(path or settings.session_path)
        self.user_id = user_id
        key = hashlib.sha256(user_id.encode()).hexdigest()
        scoped = base.with_name(f"{base.stem}.{key}{base.suffix}")
        self.session_path = str(scoped)
        if user_id == "default" and not scoped.exists():
            if not base.exists() or (load_session(str(base)) or {}).get("owner") == user_id:
                self.session_path = str(base)
            else:
                print(f"旧会话的用户归属无法确认，历史记录保留在 {base}。")
        if scoped.exists() and (load_session(str(scoped)) or {}).get("owner") != user_id:
            print(f"旧会话的用户归属无法确认，历史记录保留在 {scoped}。")
            self.session_path = str(scoped.with_name(f"{scoped.stem}.owned{scoped.suffix}"))
        self.refund_ledger = RefundLedger(str(base), user_id)
        self.policy_override = None

    def _restore_session(self) -> None:
        loaded = load_session(self.session_path) or {}
        if loaded and loaded.get("owner") != self.user_id:
            raise ValueError("会话文件与当前用户不匹配，请使用自己的会话路径。")
        self.raw_messages = loaded.get("messages", [])
        self.summary = loaded.get("summary")
        if loaded.get("short_term_memory"):
            self.memory_manager.restore_stm(loaded["short_term_memory"])

    @property
    def history_size(self) -> int:
        return len(self.raw_messages)

    def chat(self, user_input: str) -> CustomerServiceResponse:
        """先核对上次未交付的回执；只接受本轮用户原话中的操作口令。"""
        recovered = self.refund_ledger.recover()
        command = self.refund_ledger.handle_user_input(user_input)
        self.raw_messages.append({"role": "user", "content": user_input})

        answer = refund_reply([command]) if command is not None else self._answer_user(user_input)
        from_host = isinstance(answer, CustomerServiceResponse)
        if from_host:
            result = answer
        else:
            result = self._extract_structured_response(answer)
            self.memory_manager.update_short_term(self.raw_messages[-6:])

        answered_request = command.get("request_id") if command else None
        notices = [r for r in recovered if not answered_request or r.get("request_id") != answered_request]
        if notices:
            notice = refund_reply(notices)
            result.reply = notice.reply + "\n" + result.reply
            result._receipt_ids += notice._receipt_ids

        self.raw_messages.append({"role": "assistant", "content": result.model_dump_json(ensure_ascii=False)})
        # 退款草案和确认回执都直接保存，避免模型调用失败导致回执无法交付。
        if not from_host and len(self.raw_messages) > self.history_threshold:
            self._compress_history()
        self.save()
        return result

    def acknowledge_reply(self, result: CustomerServiceResponse) -> None:
        """调用方成功展示这条回答后，确认其中的业务回执已送达。"""
        for request_id in result._receipt_ids:
            self.refund_ledger.acknowledge(request_id)

    def reset(self) -> None:
        self.refund_ledger.cancel_pending()
        self.raw_messages = []
        self.summary = None
        self.memory_manager.reset_short_term()
        delete_session(self.session_path)

    def save(self) -> None:
        save_session(
            self.session_path, self.raw_messages, self.summary,
            short_term_memory=self.memory_manager.stm_to_dict(), owner=self.user_id,
        )
