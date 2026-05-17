"""离线构建知识库向量索引。

用法：
  # 默认走 settings.rag_backend
  python scripts/build_kb_index.py

  # 显式指定后端，便于一份知识库同时构建两种后端的索引做对比
  python scripts/build_kb_index.py --backend numpy
  python scripts/build_kb_index.py --backend chroma

流程：
  1. 扫描 knowledge/ 下的所有 .md 文件，按二级标题切分。
  2. 调用 OpenAI Embeddings 将每个 chunk 向量化。
  3. 通过 backend.upsert 持久化索引（NumpyBackend 写 JSON / ChromaBackend 写 PersistentClient）。
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import settings  # noqa: E402
from rag.backends import create_backend  # noqa: E402
from rag.chunker import chunk_markdown_dir  # noqa: E402
from rag.embedder import Embedder  # noqa: E402


def _build_backend(name: str):
    if name == "numpy":
        return create_backend(
            "numpy",
            index_path=ROOT / settings.kb_index_path,
        ), str(ROOT / settings.kb_index_path)
    if name == "chroma":
        return create_backend(
            "chroma",
            persist_dir=ROOT / settings.chroma_persist_dir,
            collection_name=settings.chroma_collection,
        ), f"{ROOT / settings.chroma_persist_dir} (collection={settings.chroma_collection})"
    raise ValueError(f"未知后端: {name}")


def main():
    parser = argparse.ArgumentParser(description="构建知识库向量索引")
    parser.add_argument(
        "--backend",
        choices=["numpy", "chroma"],
        default=settings.rag_backend,
        help=f"向量后端（默认: {settings.rag_backend}）",
    )
    args = parser.parse_args()

    kb_dir = ROOT / settings.kb_dir

    if not kb_dir.exists():
        print(f"❌ 知识库目录不存在: {kb_dir}")
        sys.exit(1)

    backend, target_desc = _build_backend(args.backend)

    print("=" * 60)
    print("  并夕夕 · 知识库索引构建")
    print(f"  后端      : {args.backend}")
    print(f"  源目录    : {kb_dir}")
    print(f"  索引目标  : {target_desc}")
    print(f"  Embedding : {settings.embedding_model}")
    print("=" * 60)

    print("\n[1/3] 扫描并切分 markdown 文档...")
    chunks = chunk_markdown_dir(kb_dir)
    if not chunks:
        print("❌ 未发现任何文档，请检查 knowledge/ 目录")
        sys.exit(1)

    by_doc: dict[str, int] = {}
    for c in chunks:
        by_doc[c.doc] = by_doc.get(c.doc, 0) + 1
    for doc, n in by_doc.items():
        print(f"   - {doc}: {n} chunk")
    print(f"   合计 {len(chunks)} 个 chunk")

    print(f"\n[2/3] 调用 {settings.embedding_model} 批量向量化...")
    embedder = Embedder(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.embedding_model,
    )
    vectors = embedder.encode([c.text for c in chunks])
    dim = len(vectors[0]) if vectors else 0
    print(f"   完成，向量维度 = {dim}")

    print(f"\n[3/3] 写入 {args.backend} 索引...")
    backend.upsert(
        chunks=chunks,
        vectors=vectors,
        embedding_model=settings.embedding_model,
    )
    print(f"   已写入 {backend.size()} 条向量")

    print("\n🎉 索引构建完成。")


if __name__ == "__main__":
    main()
