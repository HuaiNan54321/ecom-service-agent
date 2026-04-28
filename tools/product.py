from tools.mock_data import PRODUCTS


def query_product(keyword: str) -> dict:
    """根据商品名称关键词或商品ID查询商品信息，包括价格、库存、规格等。"""
    if keyword in PRODUCTS:
        return {"success": True, "products": [PRODUCTS[keyword]]}

    results = [
        p for p in PRODUCTS.values()
        if keyword.lower() in p["name"].lower()
        or keyword.lower() in p["category"].lower()
    ]
    if not results:
        return {"success": False, "error": f"未找到与「{keyword}」相关的商品"}
    return {"success": True, "products": results}
