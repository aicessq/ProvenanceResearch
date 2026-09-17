"""Phase 6 RRF 融合测试。"""

from __future__ import annotations

from app.services.fusion import RetrievalHit, reciprocal_rank_fusion


def build_hit(*, chunk_id: str, score: float, source: str) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        score=score,
        source=source,
        chunk_text=f"示例文本 {chunk_id}",
        document_id="doc-1",
        version_id="ver-1",
        doc_title="网络安全法样例",
        doc_type="law",
    )


def test_rrf_fuses_two_result_lists_by_chunk_id() -> None:
    vector_hits = [
        build_hit(chunk_id="chunk-a", score=0.91, source="vector"),
        build_hit(chunk_id="chunk-b", score=0.82, source="vector"),
    ]
    keyword_hits = [
        build_hit(chunk_id="chunk-b", score=0.77, source="keyword"),
        build_hit(chunk_id="chunk-c", score=0.70, source="keyword"),
    ]

    fused = reciprocal_rank_fusion(vector_hits, keyword_hits)

    assert [item.chunk_id for item in fused] == ["chunk-b", "chunk-a", "chunk-c"]
    assert fused[0].source_scores == {"vector": 0.82, "keyword": 0.77}


def test_rrf_deduplicates_same_content_across_different_chunk_ids() -> None:
    vector_hit = build_hit(chunk_id="chunk-a", score=0.9, source="vector")
    keyword_hit = build_hit(chunk_id="chunk-copy", score=0.8, source="keyword")
    vector_hit.metadata["chunk_hash"] = "same-hash"
    keyword_hit.metadata["chunk_hash"] = "same-hash"

    fused = reciprocal_rank_fusion([vector_hit], [keyword_hit])

    assert len(fused) == 1
    assert fused[0].source_scores == {"vector": 0.9, "keyword": 0.8}


def test_rrf_preserves_source_scores_for_debugging() -> None:
    vector_hits = [build_hit(chunk_id="chunk-a", score=0.5, source="vector")]
    keyword_hits = [build_hit(chunk_id="chunk-a", score=0.3, source="keyword")]

    fused = reciprocal_rank_fusion(vector_hits, keyword_hits)

    assert len(fused) == 1
    assert fused[0].chunk_id == "chunk-a"
    assert fused[0].rrf_score > 0
    assert fused[0].source_scores["vector"] == 0.5
    assert fused[0].source_scores["keyword"] == 0.3
