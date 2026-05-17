"""手写余弦相似度后端：JSON 持久化 + 全量打分。

适用场景：
- 教学：代码 < 100 行，整个检索过程透明可调试
- 小规模：< 1k chunks 全量打分耗时可忽略
- 零外部依赖：不引入向量数据库

不适用场景：
- 万级以上规模：每次查询 O(n) 打分会成为瓶颈，需要 HNSW/IVF 等近似搜索
- 多进程并发写：JSON 文件无锁，建议升级到向量数据库
- 元数据过滤：自己写过滤逻辑可以但很冗长，向量数据库原生支持
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from rag.backends.base import RetrievedChunk, VectorBackend
from rag.chunker import Chunk


class NumpyBackend(VectorBackend):
    """JSON 持久化 + 全量余弦相似度。"""

    def __init__(self, index_path: Path):
        self._index_path = Path(index_path)
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []
        self._embedding_model: str = ""

    def upsert(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks 与 vectors 长度不一致: {len(chunks)} vs {len(vectors)}"
            )
        self._chunks = list(chunks)
        self._vectors = list(vectors)
        self._embedding_model = embedding_model

        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "embedding_model": embedding_model,
            "chunks": [c.to_dict() for c in chunks],
            "vectors": vectors,
        }
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        if not self._chunks:
            self.load()

        scored = [
            (idx, _cosine(query_vector, vec))
            for idx, vec in enumerate(self._vectors)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            RetrievedChunk(chunk=self._chunks[idx], score=score)
            for idx, score in scored[:top_k]
        ]

    def size(self) -> int:
        if not self._chunks and self._index_path.exists():
            self.load()
        return len(self._chunks)

    def load(self) -> None:
        if not self._index_path.exists():
            raise FileNotFoundError(
                f"知识库索引不存在: {self._index_path}\n"
                "请先运行 `python scripts/build_kb_index.py` 构建索引。"
            )
        data = json.loads(self._index_path.read_text(encoding="utf-8"))
        self._embedding_model = data.get("embedding_model", "")
        self._chunks = [Chunk(**c) for c in data["chunks"]]
        self._vectors = data["vectors"]

    def expected_embedding_model(self) -> str:
        if not self._embedding_model and self._index_path.exists():
            self.load()
        return self._embedding_model


def _cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
