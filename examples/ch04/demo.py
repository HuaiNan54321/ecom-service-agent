"""用负对数概率和一次分数更新解释学习目标，不训练真实语言模型。"""

import math


def loss(probability):
    """目标越不被看好，损失越大；零概率的极限损失为无穷大。"""
    if not math.isfinite(probability) or not 0 < probability <= 1:
        raise ValueError("本演示要求目标概率大于零且不超过一")
    return -math.log(probability)


def probabilities(logits):
    """稳定计算有限分数的 softmax。"""
    if not logits or any(not math.isfinite(x) for x in logits):
        raise ValueError("分数必须非空且有限")
    weights = [math.exp(x - max(logits)) for x in logits]
    return [x / sum(weights) for x in weights]


def update_logits(logits, target, learning_rate):
    """直接调整三个分数，展示交叉熵梯度；真实训练还会反传到模型参数。"""
    if type(target) is not int or not 0 <= target < len(logits):
        raise ValueError("目标必须是有效候选编号")
    if not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("学习率必须为正的有限数值")
    probs = probabilities(logits)
    gradient = [p - (1 if i == target else 0) for i, p in enumerate(probs)]
    return [score - learning_rate * g for score, g in zip(logits, gradient)]


def main():
    """展示已核对的小数；单条样本变好不等于能处理新的任务。"""
    for probability in (0.8, 0.2):
        print(f"目标概率 {probability:.1f}，损失 {loss(probability):.4f}")
    print(f"两个位置的平均损失: {(loss(0.8) + loss(0.2)) / 2:.4f}")
    before = [0.0, 0.0, 0.0]
    after = update_logits(before, target=0, learning_rate=0.5)
    p_before, p_after = probabilities(before), probabilities(after)
    assert loss(p_after[0]) < loss(p_before[0])
    assert math.isclose(sum(p_after), 1.0)
    assert loss(1.0) == 0.0
    try:
        loss(0.0)
    except ValueError:
        pass
    else:
        raise AssertionError("零概率不能代入有限对数计算")
    print("更新前分数:", before)
    print("更新后分数:", [round(x, 4) for x in after])
    print("更新后概率:", [round(x, 4) for x in p_after])
    print(f"目标损失: {loss(p_before[0]):.4f} -> {loss(p_after[0]):.4f}")


if __name__ == "__main__":
    main()
