"""离线演示过滤、排名融合与检索指标；所有政策和向量机制均为教学示例。"""

from examples.ch13.demo import POLICIES, cosine, encode


DOCUMENTS = [
    {"id": "P00", "text": "普通商品退货：签收7天内，未拆封且包装完好可申请退货。", "shop": "demo", "valid_from": "2026-01-01", "valid_to": "2026-10-31"},
    *[{**doc, "shop": "demo", "valid_from": "2026-11-01", "valid_to": "2026-12-31"} for doc in POLICIES],
]


def rank(query, documents):
    """使用第13章词袋余弦；按编号稳定处理同分。"""
    return sorted(documents, key=lambda doc: (-cosine(encode(query), encode(doc["text"])), doc["id"]))


def current_documents(shop, date):
    """教学日期统一使用补零的 ISO 格式；先保留适用的文档再排序。"""
    return [doc for doc in DOCUMENTS if doc["shop"] == shop and doc["valid_from"] <= date <= doc["valid_to"]]


def reciprocal_rank_fusion(rankings, constant=60):
    """合并名次；同一列表不能重复计分，未进入列表的文档贡献零。"""
    if type(constant) is not int or constant < 1:
        raise ValueError("排名常数必须是正整数")
    scores = {}
    for ranking in rankings:
        if len(ranking) != len(set(ranking)):
            raise ValueError("同一候选列表不能重复出现同一文档")
        for position, doc_id in enumerate(ranking, 1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1 / (constant + position)
    return sorted(scores.items(), key=lambda row: (-row[1], row[0]))


def retrieval_metrics(ranked_ids, relevant_ids, k):
    """Precision@k 固定以 k 为分母；不足 k 条的位置按未命中计算。"""
    if type(k) is not int or k < 1 or not relevant_ids:
        raise ValueError("k 必须为正整数，标注的相关片段不能为空")
    selected = ranked_ids[:k]
    if len(selected) != len(set(selected)):
        raise ValueError("返回结果不能重复")
    correct = len(set(selected) & set(relevant_ids))
    return {"precision": correct / k, "recall": correct / len(relevant_ids)}


def rerank_opened_example(candidate_ids):
    """专门针对已拆封问题的人工规则，用来说明重排位置，不是神经重排器。"""
    return sorted(candidate_ids, key=lambda doc_id: doc_id != "P03")


def main():
    query = "未拆封商品签收7天内能退货吗？"
    before = rank(query, DOCUMENTS)[0]["id"]
    after = rank(query, current_documents("demo", "2026-11-13"))[0]["id"]
    assert (before, after) == ("P00", "P01")
    assert current_documents("错误店铺", "2026-11-13") == []
    print("模式：离线构造案例，非真实Embedding或模型效果测评")
    print("过滤前首条：", before, "；过滤后首条：", after)
    fused = reciprocal_rank_fusion([["P02", "P01", "P03"], ["P01", "P03", "P02"]])
    assert fused[0][0] == "P01"
    print("RRF：", [(doc_id, round(score, 6)) for doc_id, score in fused])
    print("错误过滤后的候选数：", len(current_documents("错误店铺", "2026-11-13")))
    assert rerank_opened_example(["P01", "P02"]) == ["P01", "P02"]
    assert rerank_opened_example(["P01", "P03"])[0] == "P03"
    gold = {"P01", "P03"}
    bad = retrieval_metrics(["P01", "P02"], gold, 2)
    good = retrieval_metrics(["P01", "P03"], gold, 2)
    assert bad == {"precision": .5, "recall": .5}
    assert good == {"precision": 1.0, "recall": 1.0}
    assert retrieval_metrics(["P01"], gold, 2) == {"precision": .5, "recall": .5}
    print("候选A：", bad, "；候选B：", good)


if __name__ == "__main__":
    main()
