"""RAG 模块：知识库切分、向量化、检索。

第 5 期：让 Agent 能基于 FAQ、退换货政策、配送说明、会员权益等
非结构化知识回答问题，而不只依赖工具返回的结构化数据。
"""

from rag.backends import NumpyBackend, RetrievedChunk, VectorBackend, create_backend
from rag.chunker import Chunk, chunk_markdown_dir
from rag.embedder import Embedder
from rag.retriever import KnowledgeRetriever

__all__ = [
    "Chunk",
    "chunk_markdown_dir",
    "Embedder",
    "KnowledgeRetriever",
    "RetrievedChunk",
    "VectorBackend",
    "NumpyBackend",
    "create_backend",
]
