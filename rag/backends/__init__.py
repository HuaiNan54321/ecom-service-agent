"""向量后端：抽象接口 + 两套实现（Numpy 手写 / Chroma 向量数据库）。

教学目的：同一份知识库可在两种后端间切换，便于直观对比
- 手写余弦（教学透明，零依赖，适合 < 1k chunks）
- 向量数据库（生产标配，HNSW/IVF 索引，支持亿级规模 + 元数据过滤 + 并发写入）

通过 settings.rag_backend 选择，对上层 KnowledgeRetriever / search_knowledge 透明。
"""

from rag.backends.base import RetrievedChunk, VectorBackend
from rag.backends.numpy_backend import NumpyBackend

__all__ = ["RetrievedChunk", "VectorBackend", "NumpyBackend", "create_backend"]


def create_backend(name: str, **kwargs) -> VectorBackend:
    """工厂方法：根据名称创建对应后端。

    name: "numpy" | "chroma"
    kwargs: 后端特定参数（index_path / persist_dir / collection 等）
    """
    name = (name or "numpy").lower()
    if name == "numpy":
        return NumpyBackend(index_path=kwargs["index_path"])
    if name == "chroma":
        from rag.backends.chroma_backend import ChromaBackend

        return ChromaBackend(
            persist_dir=kwargs["persist_dir"],
            collection_name=kwargs.get("collection_name", "ecom_kb"),
        )
    raise ValueError(f"未知的 RAG 后端: {name}（可选: numpy / chroma）")
