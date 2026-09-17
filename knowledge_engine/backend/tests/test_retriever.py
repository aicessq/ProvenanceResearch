"""Phase 6 retriever 测试。"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.fusion import RetrievalHit
from app.services.metadata_filter import MetadataFilter
from app.services.retriever import HybridRetriever


@dataclass(slots=True)
class FakeEmbeddingService:
    def embed_text(self, text: str) -> list[float]:
        assert text == "网络安全法 第一条"
        return [0.1, 0.2, 0.3]


class FakeVectorStore:
    def search(self, query_vector, *, top_k: int, filters: MetadataFilter):
        assert query_vector == [0.1, 0.2, 0.3]
        assert top_k == 30
        assert filters.doc_type == ["law"]
        return [
            RetrievalHit(
                chunk_id="chunk-1",
                score=0.9,
                source="vector",
                chunk_text="第一条 为了规范网络安全工作，制定本法。",
                document_id="doc-1",
                version_id="ver-1",
                doc_title="网络安全法样例",
                doc_type="law",
            )
        ]


class FakeKeywordStore:
    def search(
        self,
        query: str,
        *,
        top_k: int,
        filters: MetadataFilter,
    ) -> list[RetrievalHit]:
        assert query == "网络安全法 第一条"
        assert top_k == 30
        assert filters.doc_type == ["law"]
        return [
            RetrievalHit(
                chunk_id="chunk-1",
                score=0.7,
                source="keyword",
                chunk_text="第一条 为了规范网络安全工作，制定本法。",
                document_id="doc-1",
                version_id="ver-1",
                doc_title="网络安全法样例",
                doc_type="law",
            ),
            RetrievalHit(
                chunk_id="chunk-2",
                score=0.5,
                source="keyword",
                chunk_text="第二条 国家支持网络安全技术创新。",
                document_id="doc-1",
                version_id="ver-1",
                doc_title="网络安全法样例",
                doc_type="law",
            ),
        ]


def test_hybrid_retriever_returns_top_k_fused_chunks() -> None:
    retriever = HybridRetriever(
        embedding_service=FakeEmbeddingService(),
        vector_store=FakeVectorStore(),
        keyword_store=FakeKeywordStore(),
    )

    response = retriever.retrieve(
        query="网络安全法 第一条",
        top_k=1,
        filters=MetadataFilter.from_input({"doc_type": ["law"]}),
        debug=True,
    )

    assert response.query == "网络安全法 第一条"
    assert response.top_k == 1
    assert len(response.final_results) == 1
    assert response.final_results[0].chunk_id == "chunk-1"
    assert response.debug.vector_results
    assert response.debug.keyword_results
    assert response.debug.fused_results


def test_hybrid_retriever_consumes_search_keywords_and_sub_queries() -> None:
    keyword_queries: list[str] = []
    vector_queries: list[str] = []

    class RecordingEmbedding:
        def embed_text(self, text: str) -> list[float]:
            vector_queries.append(text)
            return [0.1]

    class EmptyVector:
        def search(self, query_vector, *, top_k: int, filters: MetadataFilter):
            return []

    class RecordingKeyword:
        def search(self, query: str, *, top_k: int, filters: MetadataFilter):
            keyword_queries.append(query)
            return []

    retriever = HybridRetriever(
        embedding_service=RecordingEmbedding(),
        vector_store=EmptyVector(),
        keyword_store=RecordingKeyword(),
    )

    retriever.search(
        query="什么是个人信息",
        search_keywords=["个人信息"],
        sub_queries=["个人信息 是指"],
    )

    assert keyword_queries == ["个人信息"]
    assert vector_queries == ["什么是个人信息", "个人信息 是指"]


def test_hybrid_retriever_keeps_high_score_hits_from_later_sub_queries() -> None:
    class QueryEmbedding:
        def embed_text(self, text: str) -> list[float]:
            return [1.0 if text == "主查询" else 2.0]

    class QueryVector:
        def search(self, query_vector, *, top_k: int, filters: MetadataFilter):
            if query_vector == [1.0]:
                return [
                    RetrievalHit(
                        chunk_id=f"primary-{index}", score=0.5 - index / 100,
                        source="vector", chunk_text=f"主候选 {index}",
                        document_id="doc", version_id="ver", doc_title="文档", doc_type="law",
                    )
                    for index in range(30)
                ]
            return [
                RetrievalHit(
                    chunk_id="subquery-best", score=0.99, source="vector",
                    chunk_text="子查询高分候选", document_id="doc", version_id="ver",
                    doc_title="文档", doc_type="law",
                )
            ]

    class EmptyKeyword:
        def search(self, query: str, *, top_k: int, filters: MetadataFilter):
            return []

    response = HybridRetriever(
        embedding_service=QueryEmbedding(),
        vector_store=QueryVector(),
        keyword_store=EmptyKeyword(),
    ).search(query="主查询", sub_queries=["子查询"], top_k=30)

    assert response.final_results[0].chunk_id == "subquery-best"


def test_hybrid_retriever_reranks_fused_top_twenty_before_top_k() -> None:
    from app.services.reranker import RerankerService

    class Scores:
        def predict(self, sentences, *, batch_size: int, show_progress_bar: bool):
            assert batch_size == 4
            assert show_progress_bar is False
            assert all(query == "定义" for query, _ in sentences)
            return [float(index) for index, _ in enumerate(sentences)]

    class Embedding:
        def embed_text(self, text: str) -> list[float]:
            return [0.1]

    class Vector:
        def search(self, query_vector, *, top_k: int, filters: MetadataFilter):
            return [
                RetrievalHit(
                    chunk_id=f"chunk-{index}", score=1.0 - index / 100, source="vector",
                    chunk_text=f"候选 {index}", document_id="doc", version_id="ver",
                    doc_title="文档", doc_type="law",
                )
                for index in range(25)
            ]

    class Keyword:
        def search(self, query: str, *, top_k: int, filters: MetadataFilter):
            return []

    response = HybridRetriever(
        embedding_service=Embedding(), vector_store=Vector(), keyword_store=Keyword(),
        reranker_service=RerankerService(Scores(), batch_size=4),
    ).search(query="定义", top_k=5, debug=True)

    assert len(response.debug.fused_results) == 20
    assert response.debug.fused_results[0].score == 1.0
    assert "reranker" not in response.debug.fused_results[0].source_scores
    assert response.final_results[0].chunk_id == "chunk-19"
    assert response.final_results[0].source_scores["reranker"] == 19.0


def test_hybrid_retriever_keeps_pipeline_ids_when_debug_is_false() -> None:
    retriever = HybridRetriever(
        embedding_service=FakeEmbeddingService(),
        vector_store=FakeVectorStore(),
        keyword_store=FakeKeywordStore(),
    )

    response = retriever.retrieve(
        query="网络安全法 第一条",
        filters=MetadataFilter.from_input({"doc_type": ["law"]}),
        debug=False,
    )

    assert response.debug.vector_results == []
    assert response.debug.keyword_results == []
    assert response.debug.fused_results
    assert response.debug.reranked_results


def test_hybrid_retriever_rejects_empty_query() -> None:
    retriever = HybridRetriever(
        embedding_service=FakeEmbeddingService(),
        vector_store=FakeVectorStore(),
        keyword_store=FakeKeywordStore(),
    )

    try:
        retriever.retrieve(query="   ")
    except ValueError as exc:
        assert "query 不能为空" in str(exc)
    else:  # pragma: no cover - 测试必须抛错
        raise AssertionError("空 query 应抛出 ValueError")
