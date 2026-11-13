"""用固定小数据说明训练输入、低秩参数量、偏好损失与奖励缺陷；不训练模型。"""

import json
import math


SFT_SAMPLE = {
    "messages": [
        {"role": "user", "content": "资料：A1001已发货。请概括状态。"},
        {"role": "assistant", "content": "根据提供的资料，A1001已发货。"},
    ]
}


def validate_sample(sample):
    """这里只检查本章两轮样本格式，不替代训练平台的数据校验。"""
    messages = sample.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError("本例需要一条用户输入和一条助手示范")
    for message, role in zip(messages, ("user", "assistant")):
        if message.get("role") != role:
            raise ValueError("消息角色或顺序错误")
        if not isinstance(message.get("content"), str) or not message["content"].strip():
            raise ValueError("内容必须是非空字符串")


def dpo_loss(chosen_logp, rejected_logp, ref_chosen, ref_rejected, beta=0.1):
    """计算一对固定序列对数概率的 DPO 损失，省略梯度和训练过程。"""
    if beta <= 0:
        raise ValueError("beta 必须大于零")
    margin = beta * ((chosen_logp - rejected_logp) - (ref_chosen - ref_rejected))
    return max(0.0, -margin) + math.log1p(math.exp(-abs(margin)))


def group_advantages(rewards):
    """演示组内标准化；同分时显式返回零，避免除以零。"""
    if len(rewards) < 2 or not all(math.isfinite(x) for x in rewards):
        raise ValueError("需要至少两个有限奖励")
    mean = sum(rewards) / len(rewards)
    std = math.sqrt(sum((x - mean) ** 2 for x in rewards) / len(rewards))
    return [(x - mean) / std if std else 0.0 for x in rewards]


def strict_reward(trajectory):
    """依据授权和结果状态判定，不依据回复中是否包含成功字样。"""
    return int(
        trajectory["authorized"]
        and trajectory["order_id"] == "A1001"
        and trajectory["refund_created"]
    )


def main():
    """打印可复核数值，所有数字来自本地确定性计算。"""
    validate_sample(SFT_SAMPLE)
    try:
        validate_sample({"messages": [{"role": "assistant", "content": "已完成"}]})
    except ValueError:
        pass
    else:
        raise AssertionError("缺失用户输入的样本应被拒绝")
    full = 4096 * 4096
    low_rank = 8 * (4096 + 4096)
    advantages = group_advantages([0, 0, 1, 1])
    assert advantages == [-1.0, -1.0, 1.0, 1.0]
    assert group_advantages([1, 1]) == [0.0, 0.0]
    base = dpo_loss(-2, -2, -2, -2)
    preferred = dpo_loss(-1, -3, -2, -2)
    assert math.isclose(base, math.log(2)) and preferred < base
    fake = {"text": "已完成", "authorized": True, "order_id": "A1001", "refund_created": False}
    real = {"text": "申请已创建", "authorized": True, "order_id": "A1001", "refund_created": True}
    assert strict_reward(fake) == 0 and strict_reward(real) == 1
    assert strict_reward({**real, "authorized": False}) == 0
    result = {
        "性质": "固定数据的公式与校验演示，没有模型训练",
        "SFT格式检查": "通过",
        "单矩阵全量参数": full,
        "秩8新增参数": low_rank,
        "组内优势": advantages,
        "DPO基线损失": round(base, 6),
        "DPO偏好增大后损失": round(preferred, 6),
        "只看成功措辞的错误得分": int("已完成" in fake["text"]),
        "检查最终状态后的得分": strict_reward(fake),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
