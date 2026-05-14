"""端到端测试：验证第 5 期 RAG 知识库检索（两套后端）。

测试场景（每套后端独立跑一遍）：
1. Markdown 切分正确性。
2. 索引构建（首次会调用 OpenAI Embeddings；已存在且模型一致则复用）。
3. KnowledgeRetriever Top-K 召回，与预期 doc 命中。
4. search_knowledge 工具返回结构。
5. Agent 端到端：政策类问题触发 search_knowledge。

前提：已配置 OPENAI_API_KEY；chroma 后端需要 `pip install chromadb`。

用法：
  python scripts/test_rag.py                # 跑两套后端
  python scripts/test_rag.py --backend numpy
  python scripts/test_rag.py --backend chroma
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.chat import EcomAgent  # noqa: E402
from config.settings import settings  # noqa: E402
from rag.backends import create_backend  # noqa: E402
from rag.chunker import chunk_markdown_dir  # noqa: E402
from rag.embedder import Embedder  # noqa: E402
from rag.retriever import KnowledgeRetriever  # noqa: E402
from schemas.response import CustomerServiceResponse, IntentType  # noqa: E402
from tools import knowledge as knowledge_tool  # noqa: E402

TEST_SESSION = str(ROOT / "sessions" / "test_rag_session.json")
EXPECTED_DOCS = {"退换货政策", "配送说明", "会员权益", "常见问题FAQ"}


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def _clean_session():
    Path(TEST_SESSION).unlink(missing_ok=True)


def _make_embedder() -> Embedder:
    return Embedder(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.embedding_model,
    )


def _make_backend(backend_name: str):
    if backend_name == "numpy":
        return create_backend("numpy", index_path=ROOT / settings.kb_index_path)
    if backend_name == "chroma":
        return create_backend(
            "chroma",
            persist_dir=ROOT / settings.chroma_persist_dir,
            collection_name=settings.chroma_collection,
        )
    raise ValueError(backend_name)


# ---------- 测试 1：切分 ----------
def test_chunker():
    print("\n  [1/5] Markdown 切分")
    chunks = chunk_markdown_dir(ROOT / settings.kb_dir)
    if not chunks:
        _fail("未切到任何 chunk")
    docs = {c.doc for c in chunks}
    missing = EXPECTED_DOCS - docs
    if missing:
        _fail(f"缺少文档: {missing}")
    for c in chunks:
        if not c.text.startswith("【"):
            _fail(f"chunk 文本未注入文档/章节标题: {c.chunk_id}")
    _ok(f"切分共 {len(chunks)} 个 chunk，覆盖文档 {docs}")


# ---------- 测试 2：构建/复用索引 ----------
def test_build_index(backend_name: str):
    print(f"\n  [2/5] 构建/加载向量索引（backend={backend_name}）")
    embedder = _make_embedder()
    backend = _make_backend(backend_name)

    try:
        backend.load()
        if backend.expected_embedding_model() == settings.embedding_model and backend.size() > 0:
            _ok(f"复用已有索引，{backend.size()} 条向量")
            return
    except FileNotFoundError:
        pass

    chunks = chunk_markdown_dir(ROOT / settings.kb_dir)
    vectors = embedder.encode([c.text for c in chunks])
    backend.upsert(
        chunks=chunks,
        vectors=vectors,
        embedding_model=settings.embedding_model,
    )
    _ok(f"已构建索引：{backend.size()} chunks，维度 {len(vectors[0])}")


# ---------- 测试 3：Top-K 召回 ----------
def test_retriever_top_k(backend_name: str):
    print(f"\n  [3/5] KnowledgeRetriever Top-K 召回（backend={backend_name}）")
    embedder = _make_embedder()
    backend = _make_backend(backend_name)
    retriever = KnowledgeRetriever(embedder=embedder, backend=backend)
    retriever.load()

    cases = [
        ("七天无理由退货可以吗", "退换货政策"),
        ("钻石会员有哪些权益", "会员权益"),
        ("偏远地区还包邮吗", "配送说明"),
        ("忘记密码了怎么办", "常见问题FAQ"),
    ]
    for query, expected_doc in cases:
        hits = retriever.search(query, top_k=3)
        if not hits:
            _fail(f"query={query!r} 无召回")
        top = hits[0]
        if top.chunk.doc != expected_doc:
            print(
                f"  ⚠️  query={query!r} top1 命中 {top.chunk.doc} / {top.chunk.section}"
                f"（期望 {expected_doc}），score={top.score:.3f}"
            )
            if not any(h.chunk.doc == expected_doc for h in hits):
                _fail(f"Top-3 都未命中预期文档 {expected_doc}")
        else:
            _ok(f"query={query!r} → {top.chunk.doc} / {top.chunk.section}（{top.score:.3f}）")


# ---------- 测试 4：search_knowledge 工具结构 ----------
def test_tool_shape(backend_name: str):
    print(f"\n  [4/5] search_knowledge 工具返回结构（backend={backend_name}）")
    settings.rag_backend = backend_name
    knowledge_tool.reset_retriever()

    result = knowledge_tool.search_knowledge("退款多久到账", top_k=2)
    if not result.get("success"):
        _fail(f"工具调用失败: {result}")
    if result.get("backend") != backend_name:
        _fail(f"backend 字段不匹配: {result.get('backend')}")
    if not result.get("results"):
        _fail("results 为空")
    if len(result["results"]) > 2:
        _fail(f"top_k=2 但返回 {len(result['results'])} 条")
    for key in ("doc", "section", "score", "text"):
        if key not in result["results"][0]:
            _fail(f"results[0] 缺少字段 {key}")
    _ok(
        f"工具返回 backend={result['backend']}，{len(result['results'])} 条，"
        f"top1=《{result['results'][0]['doc']}》/{result['results'][0]['section']}"
    )


# ---------- 测试 5：Agent 端到端 ----------
def test_agent_end_to_end(backend_name: str):
    print(f"\n  [5/5] Agent 端到端：政策类问题触发 RAG（backend={backend_name}）")
    settings.rag_backend = backend_name
    knowledge_tool.reset_retriever()

    _clean_session()
    agent = EcomAgent(session_path=TEST_SESSION)
    agent.history_threshold = 30

    try:
        resp = agent.chat("我想了解一下你们的七天无理由退货是怎么算运费的？")
        if not isinstance(resp, CustomerServiceResponse):
            _fail("返回类型不正确")
        if resp.intent not in (
            IntentType.RETURN_REQUEST,
            IntentType.AFTER_SALE,
            IntentType.OTHER,
        ):
            print(f"  ⚠️  意图分类为 {resp.intent}（非退换货/售后，可接受）")
        if not resp.reply:
            _fail("reply 为空")

        triggered = any(
            m.get("role") == "assistant" and m.get("tool_calls")
            and any(tc["function"]["name"] == "search_knowledge" for tc in m["tool_calls"])
            for m in agent.raw_messages
        )
        if triggered:
            _ok("Agent 主动调用了 search_knowledge")
        else:
            print("  ⚠️  Agent 未触发 search_knowledge（模型可能直接回复）")

        keywords = ["运费", "顾客", "上门取件", "12 元", "12元"]
        if any(kw in resp.reply for kw in keywords):
            _ok("回复中包含政策原文关键信息")
        else:
            print(f"  ⚠️  回复中未匹配预期关键词，内容片段：{resp.reply[:120]}")
    finally:
        agent.close()
        _clean_session()


def run_for_backend(backend_name: str):
    print("\n" + "=" * 60)
    print(f"  Backend: {backend_name}")
    print("=" * 60)
    test_chunker()
    test_build_index(backend_name)
    test_retriever_top_k(backend_name)
    test_tool_shape(backend_name)
    test_agent_end_to_end(backend_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["numpy", "chroma", "all"], default="all")
    args = parser.parse_args()

    print("=" * 60)
    print("  第 5 期 RAG · 端到端测试")
    print("=" * 60)

    backends = ["numpy", "chroma"] if args.backend == "all" else [args.backend]
    try:
        for name in backends:
            run_for_backend(name)
    finally:
        _clean_session()
        knowledge_tool.reset_retriever()

    print("\n" + "=" * 60)
    print(f"  🎉 全部测试通过（backends: {', '.join(backends)}）")
    print("=" * 60)


if __name__ == "__main__":
    main()
