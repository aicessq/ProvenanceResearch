"""Phase 6 `/query/retrieve` API 测试。"""

from __future__ import annotations

import pytest

from app.services.fusion import FusedRetrievalHit, RetrievalHit

pytestmark = pytest.mark.integration


class FakeRetriever:
    def retrieve(self, *, query: str, top_k: int, filters, debug: bool):
        return type(
            "RetrievalResponse",
            (),
            {
                "query": query,
                "top_k": top_k,
                "final_results": [
                    FusedRetrievalHit(
                        chunk_id="chunk-1",
                        score=0.9,
                        source="vector",
                        chunk_text="第一条 为了规范网络安全工作，制定本法。",
                        document_id="doc-1",
                        version_id="ver-1",
                        doc_title="网络安全法样例",
                        doc_type="law",
                        page_start=1,
                        page_end=1,
                        is_active=True,
                        rrf_score=0.032,
                        source_scores={"vector": 0.9, "keyword": 0.7},
                    )
                ],
                "debug": type(
                    "DebugInfo",
                    (),
                    {
                        "vector_results": [
                            RetrievalHit(
                                chunk_id="chunk-1",
                                score=0.9,
                                source="vector",
                                chunk_text="第一条 为了规范网络安全工作，制定本法。",
                                document_id="doc-1",
                                version_id="ver-1",
                                doc_title="网络安全法样例",
                                doc_type="law",
                                page_start=1,
                                page_end=1,
                                is_active=True,
                            )
                        ],
                        "keyword_results": [
                            RetrievalHit(
                                chunk_id="chunk-1",
                                score=0.7,
                                source="keyword",
                                chunk_text="第一条 为了规范网络安全工作，制定本法。",
                                document_id="doc-1",
                                version_id="ver-1",
                                doc_title="网络安全法样例",
                                doc_type="law",
                                page_start=1,
                                page_end=1,
                                is_active=True,
                            )
                        ],
                        "fused_results": [
                            FusedRetrievalHit(
                                chunk_id="chunk-1",
                                score=0.9,
                                source="vector",
                                chunk_text="第一条 为了规范网络安全工作，制定本法。",
                                document_id="doc-1",
                                version_id="ver-1",
                                doc_title="网络安全法样例",
                                doc_type="law",
                                page_start=1,
                                page_end=1,
                                is_active=True,
                                rrf_score=0.032,
                                source_scores={"vector": 0.9, "keyword": 0.7},
                            )
                        ],
                    },
                )(),
            },
        )()


class FakeRetrieverFactory:
    def from_db(self, db, *, embedding_service=None, vector_store=None, allow_embedding_fallback=False):
        return FakeRetriever()


def test_query_retrieve_api_returns_top_k_chunks_and_debug_details(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.query.HybridRetriever", FakeRetrieverFactory())

    response = client.post(
        "/api/v1/query/retrieve",
        json={
            "query": "网络安全法 第一条",
            "top_k": 1,
            "filters": {"doc_type": ["law"]},
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "网络安全法 第一条"
    assert payload["top_k"] == 1
    assert len(payload["chunks"]) == 1
    assert payload["chunks"][0]["chunk_id"] == "chunk-1"
    assert payload["debug"] is not None
    assert len(payload["debug"]["vector_results"]) == 1
    assert len(payload["debug"]["keyword_results"]) == 1
    assert len(payload["debug"]["fused_results"]) == 1
