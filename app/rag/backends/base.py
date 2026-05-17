"""向量后端抽象接口。

设计要点：
- upsert：构建索引时调用，传入 chunks + 向量 + embedding_model 标识。
  实现需把 embedding_model 持久化，下次加载时校验一致性（防止跨模型混用）。
- search：在线检索时调用，输入 query 向量，返回 Top-K 命中。
- size：当前已索引的 chunk 数量；首次访问可触发懒加载。
- load：从持久化路径加载索引；NumpyBackend 是读 JSON，ChromaBackend 是连 client。

不在接口里抽象 query 文本→向量这一步，是因为 embedder 由 KnowledgeRetriever 持有，
让后端只关心"向量怎么存、怎么搜"这一件事，职责更纯粹。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from rag.chunker import Chunk


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float


class VectorBackend(ABC):
    """向量索引后端的统一接口。"""

    @abstractmethod
    def upsert(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        """全量重建索引（覆盖式）。

        每次调用都会清空既有数据再写入，避免脏数据。增量更新不在第 5 期范围。
        """

    @abstractmethod
    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        """按余弦相似度（或等价度量）返回 Top-K 命中。"""

    @abstractmethod
    def size(self) -> int:
        """当前已索引的 chunk 数量。"""

    @abstractmethod
    def load(self) -> None:
        """从持久化存储加载索引；不存在时抛 FileNotFoundError。"""

    @abstractmethod
    def expected_embedding_model(self) -> str:
        """已持久化索引使用的 embedding 模型名（用于校验）。"""
