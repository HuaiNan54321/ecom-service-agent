"""可复算的向量、矩阵、概率与统计小例子，只使用 Python 标准库。"""

import math


def dot(a, b):
    """对应坐标相乘再求和，拒绝不等长或空向量。"""
    if not a or len(a) != len(b):
        raise ValueError("向量必须等长且非空")
    if any(not math.isfinite(x) for x in a + b):
        raise ValueError("向量元素必须为有限数值")
    return sum(x * y for x, y in zip(a, b))


def cosine(a, b):
    """比较方向；零向量没有可用的方向，不能硬算相似度。"""
    numerator = dot(a, b)
    norm_a, norm_b = math.sqrt(dot(a, a)), math.sqrt(dot(b, b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("零向量的余弦相似度未定义")
    return numerator / (norm_a * norm_b)


def matmul(left, right):
    """用左矩阵的行与右矩阵的列做点积。"""
    if not left or not right or not left[0] or not right[0]:
        raise ValueError("矩阵不能为空")
    if any(len(row) != len(left[0]) for row in left):
        raise ValueError("左矩阵必须每行等长")
    if any(len(row) != len(right[0]) for row in right):
        raise ValueError("右矩阵必须每行等长")
    if len(left[0]) != len(right):
        raise ValueError("左矩阵列数必须等于右矩阵行数")
    columns = [list(column) for column in zip(*right)]
    return [[dot(row, column) for column in columns] for row in left]


def main():
    """核对维度、零向量与分母，并打印正文所用的数值。"""
    result = matmul([[1, 2], [0, 1]], [[3, 0], [1, 2]])
    assert result == [[5, 4], [1, 2]]
    assert dot([1, 2], [3, 4]) == 11
    assert math.isclose(cosine([1, 2], [2, 4]), 1.0)
    for a, b in [([0, 0], [1, 0]), ([1], [1, 2])]:
        try:
            cosine(a, b)
        except ValueError:
            pass
        else:
            raise AssertionError("无效向量应被拒绝")
    print("点积:", dot([1, 2], [3, 4]))
    print("同方向余弦:", round(cosine([1, 2], [2, 4]), 4))
    print("矩阵乘法:", result)
    scores = [2.0, 1.0, 0.0]
    weights = [math.exp(x - max(scores)) for x in scores]
    probabilities = [x / sum(weights) for x in weights]
    assert math.isclose(sum(probabilities), 1.0)
    print("softmax:", [round(x, 4) for x in probabilities])
    print("按全部样本合计:", round((9 + 1) / (10 + 2), 4))
    print("两个组等权平均:", round((9 / 10 + 1 / 2) / 2, 4))


if __name__ == "__main__":
    main()
