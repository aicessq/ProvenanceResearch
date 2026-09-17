"""Phase 8 `/query/answer` API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.dependencies import get_db
from app.main import app
from app.models.query_log import QueryLog
from app.services.crud_service import create_chunk, create_document, create_document_version
from app.services.fusion import FusedRetrievalHit

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
                        chunk_id="child-chunk-1",
                        score=0.93,
                        source="vector",
                        chunk_text="第一条 为了保障网络安全，制定本法。",
                        document_id="doc-1",
                        version_id="ver-1",
                        doc_title="网络安全法样例",
                        doc_type="law",
                        chapter="第一章 总则",
                        article_no="第一条",
                        page_start=1,
                        page_end=1,
                        parent_chunk_id=self.parent_chunk_id,
                        version_status="active",
                        is_active=True,
                        security_domain=["governance"],
                        rrf_score=0.032,
                        source_scores={"vector": 0.93, "keyword": 0.72},
                    )
                ],
                "debug": type(
                    "DebugInfo",
                    (),
                    {"vector_results": [], "keyword_results": [], "fused_results": []},
                )(),
            },
        )()

    def __init__(self, parent_chunk_id: str) -> None:
        self.parent_chunk_id = parent_chunk_id


class FakeRetrieverFactory:
    def __init__(self, parent_chunk_id: str) -> None:
        self.parent_chunk_id = parent_chunk_id

    def from_db(self, db, *, embedding_service=None, vector_store=None, allow_embedding_fallback=False):
        return FakeRetriever(self.parent_chunk_id)


def test_query_answer_api_returns_grounded_answer_and_persists_query_log(db_session, monkeypatch) -> None:
    document = create_document(
        db_session,
        title="网络安全法样例",
        doc_type="law",
        source_filename="law.txt",
        storage_path="/tmp/law.txt",
    )
    version = create_document_version(
        db_session,
        document_id=document.id,
        version_no=1,
        file_hash="hash-1",
        file_size=100,
        mime_type="text/plain",
        storage_path="/tmp/law.txt",
    )
    parent_chunk = create_chunk(
        db_session,
        document_id=document.id,
        version_id=version.id,
        chunk_index=1,
        chunk_type="parent",
        text="第一章 总则。第一条 为了保障网络安全，制定本法。",
        normalized_text="第一章 总则 第一条 为了保障网络安全 制定本法",
        chunk_hash="parent-hash",
        doc_type="law",
        doc_title="网络安全法样例",
        chapter="第一章 总则",
        article_no="第一条",
        page_start=1,
        page_end=1,
    )

    monkeypatch.setattr("app.api.query.HybridRetriever", FakeRetrieverFactory(str(parent_chunk.id)))

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/query/answer",
                json={
                    "query": "网络安全法第一条讲了什么",
                    "top_k": 1,
                    "filters": {"doc_type": ["law"]},
                    "debug": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "网络安全法第一条讲了什么"
    assert payload["intent"]["intent"] == "law_query"
    assert payload["rewritten_query"].startswith("围绕法规条文与适用要求检索：")
    assert payload["citations"]
    assert payload["citations"][0]["doc_title"] == "网络安全法样例"
    assert payload["citations"][0]["page_start"] == 1
    assert payload["retrieved_chunks"][0]["parent_chunk_id"] == str(parent_chunk.id)
    assert payload["debug"] is not None
    assert payload["debug"]["evidence_contexts"][0]["parent_text"].startswith("第一章 总则")

    query_logs = db_session.execute(select(QueryLog)).scalars().all()
    assert len(query_logs) == 1
    assert query_logs[0].user_query == "网络安全法第一条讲了什么"
    assert query_logs[0].intent == "law_query"
    assert query_logs[0].retrieved_chunk_ids == ["child-chunk-1"]
    assert query_logs[0].answer
