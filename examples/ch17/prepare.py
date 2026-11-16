"""用已标注的合成种子演示清洗、按来源分组，以及扩充前的业务复核。"""

import argparse
import json
import re
from copy import deepcopy

from examples.ch05.demo import fixed_response, read_answer
from examples.ch17.dataset import FAMILY_SPLIT, TASKS, make_environment
from examples.common.llm import chat_completion


AMOUNT_PHRASES = ("订单 A1002 我确认只退 {amount} 元，请提交申请。", "订单 A1002 只申请退 {amount} 元，我确认提交。")
GENERATION_RULE = (
    "给开发集出一道已确认的部分退款题。订单 A1002 实付 59 元且可退。"
    "只返回 JSON 对象，amount_yuan 取 1 到 58 之间的整数元；utterance 从下列句式选一句，"
    "把 {amount} 替换为同一个金额。不产生评分答案或其他字段。句式：" + " / ".join(AMOUNT_PHRASES)
)


def seed_records():
    """每条合成记录指向人工核对过的夹具；额外三条用来展示退回原因。"""
    rows = [
        {"source": t["id"], "fixture": t["id"], "action": t["action"], "text": t["input"]}
        for t in TASKS
    ]
    refund = next(row for row in rows if row["source"] == "dev_05")
    refund["text"] = "请为订单 A1002 申请全额退款，我确认提交。联系邮箱 buyer@example.invalid。"
    return rows + [
        {**refund, "source": "重复导出", "text": refund["text"].replace("buyer@", "alias@")},
        {"source": "开票咨询", "action": "issue_invoice", "fixture": None, "text": "这笔订单能开发票吗？"},
        {"source": "缺少原始记录", "action": "request_refund", "fixture": None, "text": "昨天替我办好了吗？"},
    ]


def refund_variant(seed, *, live=False):
    """生成一条候选请求，由程序计算预期金额，再从独立沙箱核对实际状态。"""
    if seed["id"] != "dev_05" or FAMILY_SPLIT[seed["family"]] != "dev":
        raise ValueError("只允许基于指定开发种子出题")
    offline = {"amount_yuan": 12, "utterance": AMOUNT_PHRASES[0].format(amount=12)}
    response = chat_completion(
        [{"role": "user", "content": GENERATION_RULE}], live=live, response_format={"type": "json_object"},
        offline_response=None if live else fixed_response(json.dumps(offline, ensure_ascii=False)),
        max_completion_tokens=160,
    )
    candidate = json.loads(read_answer(response))
    if not isinstance(candidate, dict) or set(candidate) != {"amount_yuan", "utterance"}:
        raise ValueError("候选只能提交 amount_yuan 和 utterance")
    amount = candidate["amount_yuan"]
    if type(amount) is not int or not 1 <= amount <= 58:
        raise ValueError("部分退款金额应为 1 至 58 之间的整数元")
    if candidate["utterance"] not in [phrase.format(amount=amount) for phrase in AMOUNT_PHRASES]:
        raise ValueError("话术须符合出题约束，明确订单、金额和用户确认")
    case = deepcopy(seed)
    case.update(id="dev_05_partial", request_id="REQ-dev_05_partial", amount_cents=amount * 100,
                input=candidate["utterance"], parent_id=seed["id"],
                generation={"来源": "在线模型" if live else "固定候选（离线）", "模型": response.get("model")})
    case["expected"]["refund_amount"] = amount * 100
    env = make_environment(case)
    env.request_refund(case["user_id"], case["order_id"], case["reason"],
                       request_id=case["request_id"], confirmed=case["confirmed"],
                       amount_cents=case["amount_cents"])
    final = env.snapshot()
    refunds = list(final["refunds"].values())
    expected = case["expected"]
    if (len(refunds) != expected["refund_count"] or
            refunds[0]["amount_cents"] != expected["refund_amount"] or
            refunds[0]["order_id"] != case["order_id"] or
            refunds[0]["user_id"] != case["user_id"] or
            refunds[0]["status"] != "requested" or
            final["orders"][case["order_id"]]["status"] != "refund_pending"):
        raise ValueError("变体的预期结果与沙箱记录不符")
    return case


def prepare_dataset(rows, *, augment=False, live=False):
    """按预先确定的业务范围和来源分组处理记录，返回可直接交给运行器的任务。"""
    fixtures = {t["id"]: t for t in TASKS}
    allowed_actions = {t["action"] for t in TASKS}
    splits = {name: [] for name in ("dev", "validation", "test")}
    seen, rejected = set(), {}
    sources = set()
    for row in rows:
        if row["source"] in sources:
            raise ValueError("每条原始记录需要单独的来源编号，否则排除日志会被覆盖")
        sources.add(row["source"])
        fixture = fixtures.get(row["fixture"])
        if row["action"] not in allowed_actions:
            rejected[row["source"]] = "超出本轮业务范围"
            continue
        if fixture is None or fixture["action"] != row["action"]:
            rejected[row["source"]] = "缺少可核对的任务夹具"
            continue
        # 这批合成原文只混入了邮箱；订单号是沙箱内可以追溯的虚构编号。
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]+", "[邮箱]", row["text"].strip(), flags=re.ASCII)
        if fixture["id"] in seen:
            rejected[row["source"]] = "同一来源夹具已收录"
            continue
        seen.add(fixture["id"])
        case = {**deepcopy(fixture), "input": text}
        splits[FAMILY_SPLIT[case["family"]]].append(case)
        if (augment or live) and fixture["id"] == "dev_05":
            variant = refund_variant(case, live=live)
            splits[FAMILY_SPLIT[variant["family"]]].append(variant)
    return splits, rejected


def main():
    """打印准备前后的数量、排除理由和一条确实改变了目标的变体。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--augment", action="store_true", help="用固定候选演示出题、校验和纳入开发集")
    parser.add_argument("--live", action="store_true", help="调用已配置的模型生成一条候选，再用规则和沙箱复核")
    args = parser.parse_args()
    rows = seed_records()
    splits, rejected = prepare_dataset(rows, augment=args.augment, live=args.live)
    report = {"原始种子记录": len(rows),
              "退款种子原文（合成）": next(row["text"] for row in rows if row["source"] == "dev_05"),
              "排除": rejected,
              "按来源切分": {name: len(tasks) for name, tasks in splits.items()}}
    report["退款示例"] = [
        {"任务": t["id"], "家族": t["family"], "清洗后输入": t["input"],
         **({"父题": t["parent_id"], **t["generation"]} if "generation" in t else {}),
         "预期申请条数": t["expected"]["refund_count"], "预期金额（分）": t["expected"]["refund_amount"]}
        for t in splits["dev"] if t["id"] in ("dev_05", "dev_05_partial")
    ]
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
