"""用两个独立 Python 进程演示提交后断线、磁盘检查点与安全恢复。"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from examples.common import Sandbox


def save(path: Path, value: dict) -> None:
    """先写临时文件再替换，避免读到只写了一半的 JSON。"""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def phase(directory: Path, mode: str) -> int:
    """业务库与任务检查点分开保存；两者不假设在同一事务中。"""
    database = directory / "business.json"
    checkpoint = directory / "checkpoint.json"
    if mode == "start":
        box = Sandbox()
        intent = {"user_id": "U1001", "order_id": "A1001", "reason": "教学申请",
                  "request_id": "CH22-001", "amount_cents": 12900}
        state = {"phase": "pending", "intent": intent, "tool_calls": 0}
        save(checkpoint, state)
        box.inject_failure("request_refund", when="after_commit")
        try:
            state["tool_calls"] += 1
            save(checkpoint, state)
            box.request_refund(**intent, confirmed=True)
        except TimeoutError:
            # 外部系统已提交，保存的是外部系统自己的持久数据。
            save(database, box.snapshot())
            print("回复丢失：任务检查点仍为 pending，业务库已有申请。")
            return 17
        raise AssertionError("预期的提交后超时没有发生")
    box = Sandbox.from_snapshot(json.loads(database.read_text(encoding="utf-8")))
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    if state["tool_calls"] >= 3:
        raise RuntimeError("工具预算耗尽，保留检查点并交接")
    intent = state["intent"]
    state["tool_calls"] += 1
    # 先持久化预算，再调用工具；超时或中断也已经消耗一次机会。
    save(checkpoint, state)
    result = box.query_refund(intent["user_id"], intent["order_id"])
    if not result["success"]:
        raise RuntimeError("结果尚不能确认，交接核对，不盲目重试")
    refund = result["refund"]
    if any(refund.get(key) != intent[key] for key in intent):
        raise RuntimeError("现有申请与待执行意图不同，交接核对")
    state.update(phase="completed", refund_id=refund["refund_id"])
    save(checkpoint, state)
    assert len(box.snapshot()["refunds"]) == 1
    print("恢复完成：先查询已有申请，没有再次提交；申请数 = 1。")
    return 0


def stop_reason(*, steps: int, max_steps: int, elapsed: float, timeout: float) -> str:
    """在开始下一步前检查；实际网络请求还需要各自的超时。"""
    if elapsed >= timeout:
        return "deadline_exceeded"
    if steps >= max_steps:
        return "step_limit"
    return "continue"


def main() -> None:
    """临时目录自动清理，整段实验不触及真实交易或持久用户文件。"""
    parser = argparse.ArgumentParser(description="检查点与恢复演示")
    parser.add_argument("--phase", choices=["start", "resume"])
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.phase:
        if args.directory is None:
            parser.error("分阶段运行必须提供 --directory")
        raise SystemExit(phase(args.directory, args.phase))
    with tempfile.TemporaryDirectory(prefix="agentbook-ch22-") as temporary:
        command = [sys.executable, "-m", "examples.ch22.demo", "--directory", temporary]
        started = subprocess.run(command + ["--phase", "start"], check=False, timeout=20)
        assert started.returncode == 17
        subprocess.run(command + ["--phase", "resume"], check=True, timeout=20)
        state = json.loads((Path(temporary) / "checkpoint.json").read_text(encoding="utf-8"))
        assert state["phase"] == "completed" and state["tool_calls"] == 2
    assert stop_reason(steps=2, max_steps=2, elapsed=1, timeout=5) == "step_limit"
    assert stop_reason(steps=0, max_steps=2, elapsed=5, timeout=5) == "deadline_exceeded"
    assert stop_reason(steps=0, max_steps=2, elapsed=1, timeout=5) == "continue"
    print("步数、时限、正常继续三个分支：通过。")


if __name__ == "__main__":
    main()
