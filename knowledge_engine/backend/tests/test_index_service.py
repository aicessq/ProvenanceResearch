"""Phase 5 index_service 测试。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.chunk import Chunk
from app.models.document_version import DocumentVersion
from app.services.index_service import IndexService


@dataclass(slots=True)
class FakeEmbeddingService:
    vectors: list[list[float]]
    identity: str = "model=test;dim=4;normalize=true;preprocess=v1"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        assert texts
        return self.vectors[: len(texts)]


class FakeVectorStore:
    def __init__(self) -> None:
        self.ensure_called = False
        self.points = []

    def ensure_collection(self) -> None:
        self.ensure_called = True

    def validate_embedding_identity(self, *, allow_empty: bool = False) -> None:
        assert allow_empty is True

    def upsert_chunks(self, points):
        self.points = list(points)
        return len(self.points)


class FakeKeywordStore:
    def __init__(self) -> None:
        self.chunk_ids = []

    def update_child_chunk_search_vectors(self, chunk_ids):
        self.chunk_ids = list(chunk_ids)
        return len(self.chunk_ids)


def build_chunk(*, chunk_type: str, is_active: bool = True, parent_chunk_id=None) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        parent_chunk_id=parent_chunk_id,
        chunk_index=0,
        chunk_type=chunk_type,
        text="示例文本",
        normalized_text="示例文本",
        chunk_hash=f"hash-{chunk_type}",
        doc_type="law",
        doc_title="网络安全法样例",
        chapter="第一章 总则",
        section="第一节 适用范围",
        article_no="第一条" if chunk_type == "child" else None,
        page_start=1,
        page_end=1,
        security_domain=["compliance"],
        keywords=[],
        metadata={},
        is_active=is_active,
    )


def build_version(version_id) -> DocumentVersion:
    return DocumentVersion(
        id=version_id,
        document_id=uuid.uuid4(),
        version_no=1,
        file_hash="hash",
        file_size=128,
        mime_type="text/plain",
        storage_path="fixtures/law_sample.txt",
        version_status="active",
    )


def test_index_service_only_indexes_active_child_chunks() -> None:
    parent_chunk = build_chunk(chunk_type="parent")
    child_chunk = build_chunk(chunk_type="child", parent_chunk_id=parent_chunk.id)
    inactive_child_chunk = build_chunk(chunk_type="child", is_active=False, parent_chunk_id=parent_chunk.id)
    vector_store = FakeVectorStore()
    keyword_store = FakeKeywordStore()
    embedding_service = FakeEmbeddingService(vectors=[[0.1, 0.2, 0.3, 0.4]])
    service = IndexService(
        embedding_service=embedding_service,
        vector_store=vector_store,
        keyword_store=keyword_store,
    )

    result = service.build_chunk_indexes(
        [parent_chunk, child_chunk, inactive_child_chunk],
        version=build_version(child_chunk.version_id),
    )

    assert result.indexed_chunk_count == 1
    assert result.vector_upsert_count == 1
    assert result.keyword_updated_count == 1
    assert vector_store.ensure_called is True
    assert len(vector_store.points) == 1
    assert vector_store.points[0].payload["chunk_type"] == "child"
    assert vector_store.points[0].payload["is_active"] is True
    assert vector_store.points[0].payload["embedding_identity"] == embedding_service.identity
    assert keyword_store.chunk_ids == [child_chunk.id]


def test_index_service_builds_expected_payload() -> None:
    parent_chunk = build_chunk(chunk_type="parent")
    child_chunk = build_chunk(chunk_type="child", parent_chunk_id=parent_chunk.id)
    payload = IndexService.build_payload(
        child_chunk,
        version=build_version(child_chunk.version_id),
    )

    assert payload["chunk_id"] == str(child_chunk.id)
    assert payload["document_id"] == str(child_chunk.document_id)
    assert payload["version_id"] == str(child_chunk.version_id)
    assert payload["doc_type"] == "law"
    assert payload["doc_title"] == "网络安全法样例"
    assert payload["article_no"] == "第一条"
    assert payload["is_active"] is True
    assert payload["parent_chunk_id"] == str(parent_chunk.id)
