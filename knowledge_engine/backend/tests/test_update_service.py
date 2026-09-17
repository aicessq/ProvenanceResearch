"""Phase 9 update_service 测试。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.chunk import Chunk
from app.models.document_version import DocumentVersion
from app.services.update_service import calculate_chunk_diff, reuse_unchanged_child_vectors


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserted_points = []

    def get_chunks_by_ids(self, chunk_ids):
        return [SimpleNamespace(id=str(chunk_ids[0]), vector=[0.1, 0.2, 0.3])]

    def upsert_chunks(self, points):
        self.upserted_points.extend(points)
        return len(points)


def build_chunk(*, chunk_hash: str, chunk_type: str = "child") -> Chunk:
    chunk = Chunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        chunk_index=1,
        chunk_type=chunk_type,
        text="示例文本",
        normalized_text="示例文本",
        chunk_hash=chunk_hash,
        doc_type="law",
        doc_title="网络安全法样例",
        is_active=True,
    )
    return chunk


def test_calculate_chunk_diff_classifies_added_removed_and_unchanged() -> None:
    old_chunks = [
        build_chunk(chunk_hash="hash-keep"),
        build_chunk(chunk_hash="hash-remove"),
    ]
    new_child_records = [
        {"chunk_type": "child", "chunk_hash": "hash-keep"},
        {"chunk_type": "child", "chunk_hash": "hash-add"},
    ]

    diff = calculate_chunk_diff(old_chunks, new_child_records)

    assert [record["chunk_hash"] for record in diff.added] == ["hash-add"]
    assert [chunk.chunk_hash for chunk in diff.removed] == ["hash-remove"]
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0][0].chunk_hash == "hash-keep"
    assert diff.unchanged[0][1]["chunk_hash"] == "hash-keep"


def test_reuse_unchanged_child_vectors_copies_existing_vectors_without_reembedding() -> None:
    old_chunk = build_chunk(chunk_hash="hash-keep")
    new_chunk = build_chunk(chunk_hash="hash-keep")
    new_chunk.id = uuid.uuid4()
    new_chunk.version_id = uuid.uuid4()
    version = DocumentVersion(
        id=new_chunk.version_id,
        document_id=new_chunk.document_id,
        version_no=2,
        file_hash="file-hash-2",
        file_size=123,
        mime_type="text/plain",
        storage_path="/tmp/file.txt",
        version_status="active",
    )
    vector_store = FakeVectorStore()

    reused_count = reuse_unchanged_child_vectors(
        vector_store=vector_store,
        old_to_new=[(old_chunk, new_chunk)],
        version=version,
    )

    assert reused_count == 1
    assert len(vector_store.upserted_points) == 1
    assert vector_store.upserted_points[0].chunk_id == str(new_chunk.id)
    assert vector_store.upserted_points[0].vector == [0.1, 0.2, 0.3]
