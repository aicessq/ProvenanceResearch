"""Phase 5 入库 worker 测试。"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.ingest_task import IngestTask
from app.workers.ingest_worker import ingest_document_task

pytestmark = pytest.mark.integration


class FakeIndexService:
    """worker 测试中的索引服务替身。"""

    def __init__(self) -> None:
        self.received_chunks = []
        self.received_version = None

    def build_chunk_indexes(self, chunks, *, version):
        self.received_chunks = list(chunks)
        self.received_version = version
        child_count = len([chunk for chunk in chunks if chunk.chunk_type == "child"])
        return type(
            "IndexResult",
            (),
            {
                "indexed_chunk_count": child_count,
                "vector_upsert_count": child_count,
                "keyword_updated_count": child_count,
            },
        )()


class FakeIndexServiceFactory:
    """为 monkeypatch 提供 from_db 接口。"""

    def __init__(self, fake_service: FakeIndexService) -> None:
        self.fake_service = fake_service

    def from_db(self, db, *, allow_embedding_fallback=False):
        assert allow_embedding_fallback is False
        return self.fake_service


def create_ingest_task_records(
    db_session,
    *,
    file_path: Path,
    title: str,
    doc_type: str,
    mime_type: str,
    file_hash: str = "hash",
) -> tuple[Document, DocumentVersion, IngestTask]:
    """创建 worker 测试所需的 document/version/task 记录。"""
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    task_id = uuid.uuid4()

    document = Document(
        id=document_id,
        title=title,
        doc_type=doc_type,
        source_filename=file_path.name,
        storage_path=str(file_path),
        status="active",
        security_domain=["compliance"],
        tags=[],
        current_version_id=None,
    )
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_no=1,
        file_hash=file_hash,
        file_size=file_path.stat().st_size,
        mime_type=mime_type,
        storage_path=str(file_path),
        version_status="active",
    )
    task = IngestTask(
        id=task_id,
        document_id=document_id,
        version_id=version_id,
        task_type="ingest",
        status="queued",
        progress=0,
        message="等待处理",
    )

    db_session.add(document)
    db_session.add(version)
    db_session.add(task)
    db_session.flush()
    document.current_version_id = version_id
    db_session.commit()
    return document, version, task


def test_ingest_worker_persists_chunks_and_builds_indexes_for_child_chunks(db_session, monkeypatch) -> None:
    sample_path = Path(__file__).parent / "fixtures" / "law_sample.txt"
    fake_index_service = FakeIndexService()
    monkeypatch.setattr(
        "app.workers.ingest_worker.IndexService",
        FakeIndexServiceFactory(fake_index_service),
    )
    document, version, task = create_ingest_task_records(
        db_session,
        file_path=sample_path,
        title="网络安全法样例",
        doc_type="law",
        mime_type="text/plain",
    )

    result = ingest_document_task(
        document_id=str(document.id),
        version_id=str(version.id),
        task_id=str(task.id),
        file_path=str(sample_path),
    )

    db_session.expire_all()
    refreshed_task = db_session.get(IngestTask, task.id)
    persisted_chunks = db_session.query(Chunk).filter(Chunk.version_id == version.id).order_by(Chunk.chunk_index).all()

    assert result["status"] == "completed"
    assert result["chunk_count"] >= 2
    assert result["indexed_chunk_count"] >= 1
    assert refreshed_task is not None
    assert refreshed_task.status == "completed"
    assert "child chunk 索引已完成" in (refreshed_task.message or "")
    assert persisted_chunks
    assert any(chunk.chunk_type == "parent" for chunk in persisted_chunks)
    assert any(chunk.chunk_type == "child" for chunk in persisted_chunks)
    assert len(fake_index_service.received_chunks) == len(persisted_chunks)
    assert fake_index_service.received_version is not None


def test_ingest_worker_marks_failed_when_index_build_raises(db_session, monkeypatch) -> None:
    sample_path = Path(__file__).parent / "fixtures" / "plain_note.txt"

    class FailingIndexService:
        def build_chunk_indexes(self, chunks, *, version):
            raise RuntimeError("索引建立失败")

    class FailingIndexServiceFactory:
        def from_db(self, db, *, allow_embedding_fallback=False):
            return FailingIndexService()

    monkeypatch.setattr(
        "app.workers.ingest_worker.IndexService",
        FailingIndexServiceFactory(),
    )
    document, version, task = create_ingest_task_records(
        db_session,
        file_path=sample_path,
        title="普通说明",
        doc_type="other",
        mime_type="text/plain",
    )

    result = ingest_document_task(
        document_id=str(document.id),
        version_id=str(version.id),
        task_id=str(task.id),
        file_path=str(sample_path),
    )

    db_session.expire_all()
    refreshed_task = db_session.get(IngestTask, task.id)

    assert result["status"] == "failed"
    assert refreshed_task is not None
    assert refreshed_task.status == "failed"
    assert refreshed_task.error_message == "索引建立失败"
    assert "索引建立失败" in (refreshed_task.error_message or "")
