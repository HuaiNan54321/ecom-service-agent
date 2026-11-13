"""可选真实 Embedding 请求；仅 --live 联网，默认显示准备要求。"""

import argparse
import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from examples.ch13.demo import POLICIES, cosine


class NoRedirect(HTTPRedirectHandler):
    """拒绝接口重定向，避免授权头被转发到另一个地址。"""

    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def parse_vectors(payload, count):
    """按响应 index 还原输入顺序，拒绝缺项、重复编号和异常数值。"""
    if not isinstance(payload, dict):
        raise ValueError("Embedding 响应必须是对象")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != count:
        raise ValueError("Embedding 响应数量与输入不一致")
    if any(not isinstance(item, dict) for item in data):
        raise ValueError("Embedding 响应项必须是对象")
    indices = [item.get("index") for item in data]
    if any(type(index) is not int for index in indices) or set(indices) != set(range(count)):
        raise ValueError("Embedding 响应编号不完整或重复")
    vectors = [item.get("embedding") for item in sorted(data, key=lambda item: item["index"])]
    if any(not isinstance(vec, list) or not vec for vec in vectors):
        raise ValueError("Embedding 响应必须包含非空向量")
    dimension = len(vectors[0])
    if any(len(vec) != dimension or any(type(x) not in (int, float) or not math.isfinite(x) for x in vec) for vec in vectors):
        raise ValueError("Embedding 维度或数值不合法")
    return vectors


def embed_live(texts):
    """对显式配置的兼容接口发送一次请求；不打印密钥或服务端响应正文。"""
    base = os.environ.get("AGENTBOOK_BASE_URL", "").rstrip("/")
    key = os.environ.get("AGENTBOOK_API_KEY", "")
    model = os.environ.get("AGENTBOOK_EMBEDDING_MODEL", "")
    parsed = urlparse(base)
    if not key or not model or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请配置 HTTPS 的 AGENTBOOK_BASE_URL、API_KEY 与 EMBEDDING_MODEL")
    body = json.dumps({"model": model, "input": texts}, ensure_ascii=False).encode("utf-8")
    request = Request(base + "/embeddings", data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Embedding 请求失败：HTTP {exc.code}，请核对模型、地域及额度") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Embedding 网络连接失败或超时") from None
    vectors = parse_vectors(payload, len(texts))
    return vectors, payload.get("usage", {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="发送一次真实 Embedding 请求，可能产生费用")
    args = parser.parse_args()
    if not args.live:
        print("未联网。配置 AGENTBOOK_BASE_URL、AGENTBOOK_API_KEY、AGENTBOOK_EMBEDDING_MODEL 后加 --live。")
        return
    query = "未拆封商品签收7天内能退货吗？"
    vectors, usage = embed_live([query, *[doc["text"] for doc in POLICIES]])
    scores = [(doc["id"], round(cosine(vectors[0], vec), 4)) for doc, vec in zip(POLICIES, vectors[1:])]
    print("真实向量排序：", sorted(scores, key=lambda row: -row[1]))
    print("维度：", len(vectors[0]), "用量：", usage)


if __name__ == "__main__":
    main()
