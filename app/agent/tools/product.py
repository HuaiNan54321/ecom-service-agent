import random

from app.agent.tools.mock_data import PRODUCTS


def _match_score(product: dict, keywords: list[str]) -> int:
    """计算商品与关键词列表的匹配度（命中关键词数量）。"""
    searchable = " ".join([
        product["name"],
        product["category"],
        product.get("description", ""),
        " ".join(str(v) for v in product.get("specs", {}).values()),
    ]).lower()
    return sum(1 for kw in keywords if kw in searchable)


def _generate_mock_product(keyword: str) -> dict:
    """未命中任何商品时，生成一个 mock 商品兜底。"""
    price = round(random.uniform(99, 2999), 2)
    return {
        "product_id": f"MOCK-{random.randint(1000,9999)}",
        "name": f"{keyword}（热销款）",
        "category": keyword,
        "price": price,
        "stock": random.randint(10, 200),
        "description": f"并夕夕精选{keyword}，品质保证，支持七天无理由退换",
        "specs": {"备注": "模拟商品数据"},
    }


def query_product(keyword: str) -> dict:
    """根据商品名称关键词或商品ID查询商品信息，包括价格、库存、规格等。"""
    if keyword in PRODUCTS:
        return {"success": True, "products": [PRODUCTS[keyword]]}

    keywords = [kw.lower() for kw in keyword.split() if kw.strip()]
    if not keywords:
        keywords = [keyword.lower()]

    scored = [(p, _match_score(p, keywords)) for p in PRODUCTS.values()]
    results = [p for p, score in scored if score > 0]

    if not results:
        return {"success": True, "products": [_generate_mock_product(keyword)]}
    return {"success": True, "products": results}
