"""混合检索服务（向量 + 关键词 + RRF）。

Phase 6 负责第一次把“已索引 child chunk”升级为“可查询并返回的检索结果”。
本模块只做基础检索链路，不提前实现 answer generation。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from sqlalchemy.orm import Session

from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.services.fusion import FusedRetrievalHit, RetrievalHit, reciprocal_rank_fusion
from app.services.keyword_store import KeywordStore
from app.services.metadata_filter import MetadataFilter
from app.services.reranker import RerankerService, get_reranker_service
from app.services.vector_store import QdrantVectorStore


@dataclass(slots=True)
class RetrievalDebugInfo:
    """调试接口输出的检索明细。"""

    vector_results: list[RetrievalHit] = field(default_factory=list)
    keyword_results: list[RetrievalHit] = field(default_factory=list)
    fused_results: list[FusedRetrievalHit] = field(default_factory=list)
    reranked_results: list[FusedRetrievalHit] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalResponse:
    """混合检索服务输出。"""

    query: str
    top_k: int
    final_results: list[FusedRetrievalHit]
    debug: RetrievalDebugInfo


class HybridRetriever:
    """Phase 6 混合检索服务。"""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        vector_store: QdrantVectorStore,
        keyword_store: KeywordStore,
        reranker_service: RerankerService | None = None,
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.keyword_store = keyword_store
        self.reranker_service = reranker_service

    @classmethod
    def from_db(
        cls,
        db: Session,
        *,
        embedding_service: EmbeddingService | None = None,
        vector_store: QdrantVectorStore | None = None,
        allow_embedding_fallback: bool = False,
        allow_reranker_fallback: bool = False,
        reranker_service: RerankerService | None = None,
    ) -> "HybridRetriever":
        """按当前数据库会话构造检索服务。"""
        vector = vector_store or QdrantVectorStore.from_settings()
        embedding = embedding_service or get_embedding_service(allow_fallback=allow_embedding_fallback)
        vector.expected_embedding_identity = embedding.identity
        vector.validate_embedding_identity()
        return cls(
            embedding_service=embedding,
            vector_store=vector,
            keyword_store=KeywordStore.from_db(db),
            reranker_service=reranker_service or get_reranker_service(allow_fallback=allow_reranker_fallback),
        )

    def search(
        self,
        *,
        query: str,
        top_k: int = 5,
        filters: MetadataFilter | None = None,
        debug: bool = False,
        search_keywords: list[str] | None = None,
        sub_queries: list[str] | None = None,
    ) -> RetrievalResponse:
        """执行多查询召回、内容去重、RRF 与可选 rerank。"""
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query 不能为空")

        effective_filters = filters or MetadataFilter()
        vector_queries = _unique([normalized_query, *(sub_queries or [])])
        keyword_queries = _unique(search_keywords or [normalized_query])
        vector_results = _merge_hits(
            hit
            for vector_query in vector_queries
            for hit in self.vector_store.search(
                self.embedding_service.embed_text(vector_query), top_k=30, filters=effective_filters
            )
        )
        keyword_results = _merge_hits(
            hit
            for keyword_query in keyword_queries
            for hit in self.keyword_store.search(keyword_query, top_k=30, filters=effective_filters)
        )
        fused_results = reciprocal_rank_fusion(vector_results[:30], keyword_results[:30])[:20]
        reranked_results = self._rerank(normalized_query, fused_results)
        final_results = reranked_results[:top_k]
        return RetrievalResponse(
            query=normalized_query,
            top_k=top_k,
            final_results=final_results,
            debug=RetrievalDebugInfo(
                vector_results=vector_results if debug else [],
                keyword_results=keyword_results if debug else [],
                fused_results=fused_results,
                reranked_results=reranked_results,
            ),
        )

    def retrieve(
        self,
        *,
        query: str,
        top_k: int = 5,
        filters: MetadataFilter | None = None,
        debug: bool = False,
        search_keywords: list[str] | None = None,
        sub_queries: list[str] | None = None,
    ) -> RetrievalResponse:
        """兼容原调用名。"""
        return self.search(
            query=query,
            top_k=top_k,
            filters=filters,
            debug=debug,
            search_keywords=search_keywords,
            sub_queries=sub_queries,
        )

    def _rerank(self, query: str, candidates: list[FusedRetrievalHit]) -> list[FusedRetrievalHit]:
        if self.reranker_service is None or not candidates:
            return list(candidates)
        scored = self.reranker_service.rerank(query, [item.chunk_text for item in candidates])
        reranked: list[FusedRetrievalHit] = []
        for item, result in zip(candidates, scored, strict=True):
            source_scores = dict(item.source_scores)
            source_scores["reranker"] = result.score
            reranked.append(replace(item, score=result.score, source_scores=source_scores))
        return sorted(reranked, key=lambda item: item.score, reverse=True)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def _merge_hits(hits) -> list[RetrievalHit]:
    merged: dict[str, RetrievalHit] = {}
    for hit in hits:
        current = merged.get(hit.chunk_id)
        if current is None or hit.score > current.score:
            merged[hit.chunk_id] = hit
    return sorted(merged.values(), key=lambda hit: hit.score, reverse=True)
