"""三个位置的单头因果注意力：Q、K、V 为手工数据，不是训练后的模型。"""

import math


def attention(queries, keys, values):
    """对每个位置只计算当前位置及过去位置的权重和加权结果。"""
    if not queries or len(queries) != len(keys) or len(keys) != len(values):
        raise ValueError("Q、K、V 必须包含相同且非零的位置数")
    key_dim = len(keys[0])
    value_dim = len(values[0])
    if key_dim == 0 or value_dim == 0:
        raise ValueError("向量维度不能为零")
    if any(len(x) != key_dim for x in queries + keys):
        raise ValueError("Q 与 K 的每个向量必须具有相同维度")
    if any(len(x) != value_dim for x in values):
        raise ValueError("V 的向量维度必须一致")
    if any(not math.isfinite(n) for row in queries + keys + values for n in row):
        raise ValueError("本示例只接受有限数值")
    weights, outputs = [], []
    for position, query in enumerate(queries):
        scores = [sum(q * k for q, k in zip(query, key)) / math.sqrt(key_dim)
                  for key in keys[:position + 1]]
        exponentials = [math.exp(score - max(scores)) for score in scores]
        visible = [x / sum(exponentials) for x in exponentials]
        row = visible + [0.0] * (len(keys) - len(visible))
        weights.append(row)
        outputs.append([sum(row[j] * values[j][d] for j in range(len(values)))
                        for d in range(value_dim)])
    return weights, outputs


def main():
    """核对遮罩、归一化与未来位置不会影响过去位置。"""
    queries = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    keys = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    values = [[2.0, 0.0], [0.0, 2.0], [2.0, 2.0]]
    weights, outputs = attention(queries, keys, values)
    for i, row in enumerate(weights):
        assert math.isclose(sum(row), 1.0)
        assert all(x == 0.0 for x in row[i + 1:])
    changed = [values[0], values[1], [200.0, -200.0]]
    _, changed_outputs = attention(queries, keys, changed)
    assert changed_outputs[:2] == outputs[:2]
    assert changed_outputs[2] != outputs[2]
    assert outputs[0] == [2.0, 0.0]
    assert math.isclose(outputs[1][1], 1.3395230986533138)
    print("注意力权重:")
    for row in weights:
        print([round(x, 4) for x in row])
    print("加权结果:")
    for row in outputs:
        print([round(x, 4) for x in row])
    print("修改第三个 V 后，前两个位置输出不变：通过")


if __name__ == "__main__":
    main()
