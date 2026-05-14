"""Chroma 向量数据库后端：嵌入式持久化 + 内置 HNSW 近似检索。

为什么选 Chroma：
- 嵌入式模式（PersistentClient）开箱即用，无需 Docker，便于教学
- 是 LangChain / LlamaIndex 等主流框架的默认后端，工程代表性强
- 内置 HNSW 索引，万级以上规模 Top-K 查询是 O(log n) 而非 O(n)

与 NumpyBackend 的关键差异（讲给学生听）：
1. 真正的索引结构：HNSW 图，构建/查询都是亚线性
2. 元数据原生支持：可按 doc/section 等字段过滤后再向量召回
3. 增量写入安全：Chroma 内部有锁，多进程写入不会脏
4. 距离 → 相似度的换算：collection 设 cosine 距离，score = 1 - distance

我们用 collection.metadata 存 embedding_model 标识，
加载时校验，避免"换了 embedding 模型却还在用老索引"这种隐蔽问题。
"""

from __future__ import annotations

from pathlib import Path

from rag.backends.base import RetrievedChunk, VectorBackend
from rag.chunker import Chunk

_EMBEDDING_MODEL_KEY = "embedding_model"


class ChromaBackend(VectorBackend):
    """Chroma 嵌入式向量数据库后端。"""

    def __init__(self, persist_dir: Path, collection_name: str = "ecom_kb"):
        self._persist_dir = Path(persist_dir)
        self._collection_name = collection_name
        self._client = None
        self._collection = None
        self._embedding_model: str = ""
        self._size_cache: int | None = None

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            import chromadb
        except ImportError as e:
            raise ImportError(
                "chromadb 未安装。请运行 `pip install chromadb` 或 "
                "`pip install -r requirements.txt`。"
            ) from e

        self._persist_dir.mkdir(parents=True, exist_ok=True)
        # PersistentClient 把数据写到磁盘上，进程重启可恢复
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))

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

        self._ensure_client()

        # 全量重建：先删后建，避免 embedding 模型切换时的脏数据
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:
            # 不存在则忽略
            pass

        # cosine 距离：score = 1 - distance，越大越相似
        self._collection = self._client.create_collection(
            name=self._collection_name,
            metadata={
                _EMBEDDING_MODEL_KEY: embedding_model,
                "hnsw:space": "cosine",
            },
        )

        self._collection.add(
            ids=[c.chunk_id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[
                {"doc": c.doc, "section": c.section, "chunk_id": c.chunk_id}
                for c in chunks
            ],
        )

        self._embedding_model = embedding_model
        self._size_cache = len(chunks)

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        if self._collection is None:
            self.load()

        result = self._collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
        )

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        out: list[RetrievedChunk] = []
        for cid, doc_text, meta, dist in zip(ids, documents, metadatas, distances):
            chunk = Chunk(
                chunk_id=meta.get("chunk_id", cid),
                doc=meta.get("doc", ""),
                section=meta.get("section", ""),
                text=doc_text,
            )
            score = 1.0 - float(dist)  # cosine distance → similarity
            out.append(RetrievedChunk(chunk=chunk, score=score))
        return out

    def size(self) -> int:
        if self._collection is None:
            try:
                self.load()
            except FileNotFoundError:
                return 0
        if self._size_cache is None:
            self._size_cache = self._collection.count()
        return self._size_cache

    def load(self) -> None:
        self._ensure_client()
        try:
            self._collection = self._client.get_collection(self._collection_name)
        except Exception as e:
            raise FileNotFoundError(
                f"Chroma collection '{self._collection_name}' 不存在于 "
                f"{self._persist_dir}。请先运行 "
                f"`python scripts/build_kb_index.py --backend chroma` 构建索引。"
            ) from e

        meta = self._collection.metadata or {}
        self._embedding_model = meta.get(_EMBEDDING_MODEL_KEY, "")
        self._size_cache = None  # 等需要时再 count

    def expected_embedding_model(self) -> str:
        if not self._embedding_model and self._collection is None:
            try:
                self.load()
            except FileNotFoundError:
                return ""
        return self._embedding_model
