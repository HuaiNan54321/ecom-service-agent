"""用可数清的小样本解释重复成功、裁判混淆矩阵与区间。"""

from math import comb, isfinite, sqrt


def repeated_success(n: int, c: int, k: int) -> dict:
    """对同一任务的 n 次独立同条件尝试，计算两种无放回组合估计。"""
    if any(type(value) is not int for value in (n, c, k)):
        raise ValueError("n、c、k 必须是整数")
    if not 0 <= c <= n or not 1 <= k <= n:
        raise ValueError("要求 0<=c<=n 且 1<=k<=n")
    total = comb(n, k)
    return {"pass_at_k": 1 - comb(n - c, k) / total,
            "pass_all_k": comb(c, k) / total}


def calibration(reference, predicted) -> dict:
    """参考标签须另行审核；这里的函数只做统计，不创造正确答案。"""
    if len(reference) != len(predicted) or not reference:
        raise ValueError("参考与预测标签须等长且非空")
    if any(type(value) is not bool for value in list(reference) + list(predicted)):
        raise ValueError("本例只接受明确的布尔标签，未知项应另行记录")
    tp = sum(a and b for a, b in zip(reference, predicted))
    tn = sum(not a and not b for a, b in zip(reference, predicted))
    fp = sum(not a and b for a, b in zip(reference, predicted))
    fn = sum(a and not b for a, b in zip(reference, predicted))
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "agreement": (tp + tn) / len(reference),
            "accept_precision": tp / (tp + fp) if tp + fp else None,
            "accept_recall": tp / (tp + fn) if tp + fn else None}


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple:
    """二项比例的 Wilson 区间；同任务相关重复不能直接当作独立样本。"""
    if type(successes) is not int or type(total) is not int or not 0 <= successes <= total or total == 0:
        raise ValueError("要求总数为正整数且成功数在范围内")
    if type(z) not in {int, float} or not isfinite(z) or z <= 0:
        raise ValueError("z 必须为有限正数")
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return center - half, center + half
