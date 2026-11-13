"""用人为设定的分数讲解温度和 top-p；不调用真实语言模型。"""

import math
import random


def softmax(logits, temperature=1.0):
    """把有限分数转成概率；本函数只处理大于零的温度。"""
    if not logits or not all(math.isfinite(x) for x in logits):
        raise ValueError("分数必须非空且均为有限数值")
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("温度必须是大于零的有限数值")
    largest = max(logits)
    weights = [math.exp((x - largest) / temperature) for x in logits]
    total = sum(weights)
    return [x / total for x in weights]


def nucleus(probabilities, top_p):
    """保留累计概率达到阈值的最短前缀，再归一化。"""
    if not 0 < top_p <= 1:
        raise ValueError("top_p 必须在零到一之间，且不能为零")
    if not probabilities or any(not math.isfinite(x) or x < 0 for x in probabilities):
        raise ValueError("概率必须非空、有限且非负")
    if not math.isclose(sum(probabilities), 1.0):
        raise ValueError("输入概率之和必须为一")
    ranked = sorted(range(len(probabilities)), key=lambda i: probabilities[i], reverse=True)
    kept = []
    mass = 0.0
    for index in ranked:
        kept.append(index)
        mass += probabilities[index]
        if mass >= top_p:
            break
    return {index: probabilities[index] / mass for index in kept}


def main():
    """打印固定数值，说明每次采样只选择一个候选。"""
    logits = [2.0, 1.0, 0.0]
    for temperature in (0.5, 1.0, 2.0):
        probabilities = softmax(logits, temperature)
        assert math.isclose(sum(probabilities), 1.0)
        print(f"温度 {temperature}: {[round(x, 4) for x in probabilities]}")
    kept = nucleus(softmax(logits), 0.8)
    assert list(kept) == [0, 1]
    assert math.isclose(sum(kept.values()), 1.0)
    assert nucleus([1.0, 0.0], 1.0) == {0: 1.0}
    assert softmax([10000.0, 10000.0]) == [0.5, 0.5]
    try:
        softmax(logits, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("零温度应走贪心分支，不能代入本公式")
    print("top_p=0.8:", {i: round(p, 4) for i, p in kept.items()})
    selected = random.Random(7).choices(list(kept), weights=list(kept.values()), k=5)
    print("固定随机种子的五次独立抽样:", selected)
    print("以上是人为设定的三候选分布，不代表任何真实模型的输出。")


if __name__ == "__main__":
    main()
