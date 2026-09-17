"""RRF 融合服务。

Phase 6 只负责把向量检索与关键词检索结果按 RRF 合并，
不提前接入 reranker。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re


RRF_K = 60


@dataclass(slots=True)
class RetrievalHit:
    """单路检索命中的统一表达。"""

    chunk_id: str
    score: float
    source: str
    chunk_text: str
    document_id: str
    version_id: str
    doc_title: str
    doc_type: str
    chapter: str | None = None
    section: str | None = None
    article_no: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    parent_chunk_id: str | None = None
    version_status: str | None = None
    is_active: bool = True
    security_domain: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class FusedRetrievalHit(RetrievalHit):
    """融合后的命中结果，保留来源明细。"""

    rrf_score: float = 0.0
    source_scores: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(
    vector_hits: list[RetrievalHit],
    keyword_hits: list[RetrievalHit],
    *,
    k: int = RRF_K,
) -> list[FusedRetrievalHit]:
    """按内容身份对两路结果做 RRF 融合。"""
    fused: dict[str, FusedRetrievalHit] = {}

    for source_name, hits in (("vector", vector_hits), ("keyword", keyword_hits)):
        seen_in_source: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            content_key = _content_identity(hit)
            if content_key in seen_in_source:
                continue
            seen_in_source.add(content_key)
            if content_key not in fused:
                fused[content_key] = FusedRetrievalHit(
                    chunk_id=hit.chunk_id,
                    score=hit.score,
                    source=hit.source,
                    chunk_text=hit.chunk_text,
                    document_id=hit.document_id,
                    version_id=hit.version_id,
                    doc_title=hit.doc_title,
                    doc_type=hit.doc_type,
                    chapter=hit.chapter,
                    section=hit.section,
                    article_no=hit.article_no,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    parent_chunk_id=hit.parent_chunk_id,
                    version_status=hit.version_status,
                    is_active=hit.is_active,
                    security_domain=list(hit.security_domain),
                    metadata=dict(hit.metadata),
                )
            fused_hit = fused[content_key]
            fused_hit.rrf_score += 1.0 / (k + rank)
            fused_hit.source_scores[source_name] = hit.score

    return sorted(fused.values(), key=lambda item: item.rrf_score, reverse=True)


def _content_identity(hit: RetrievalHit) -> str:
    chunk_hash = str(hit.metadata.get("chunk_hash") or "").strip()
    if chunk_hash:
        return f"hash:{chunk_hash}"
    normalized = re.sub(r"\s+", "", hit.chunk_text).lower()
    if normalized:
        return f"text:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"
    return f"id:{hit.chunk_id}"
