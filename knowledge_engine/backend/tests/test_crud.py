"""Phase 1 基础 CRUD 测试。"""

from __future__ import annotations

import pytest

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.eval_dataset import EvalDataset
from app.models.eval_run import EvalRun
from app.models.ingest_task import IngestTask
from app.services.crud_service import (
    create_chunk,
    create_document,
    create_document_version,
    create_eval_dataset,
    create_eval_run,
    create_ingest_task,
    get_by_id,
)

pytestmark = pytest.mark.integration


def test_create_document_and_get_by_id(db_session) -> None:
    document = create_document(
        db_session,
        title="网络安全应急响应手册",
        doc_type="manual",
        source_filename="manual.pdf",
        storage_path="raw/manual.pdf",
        security_domain=["incident-response"],
        tags=["blue-team"],
    )

    loaded = get_by_id(db_session, Document, document.id)
    assert loaded is not None
    assert loaded.title == "网络安全应急响应手册"
    assert loaded.security_domain == ["incident-response"]


def test_create_document_version_chunk_and_ingest_task(db_session) -> None:
    document = create_document(
        db_session,
        title="中华人民共和国网络安全法",
        doc_type="law",
        source_filename="law.pdf",
        storage_path="raw/law.pdf",
    )
    version = create_document_version(
        db_session,
        document_id=document.id,
        version_no=1,
        file_hash="sha256-demo",
        file_size=1024,
        mime_type="application/pdf",
        storage_path="versions/law-v1.pdf",
    )
    chunk = create_chunk(
        db_session,
        document_id=document.id,
        version_id=version.id,
        chunk_index=0,
        chunk_type="parent",
        text="第一章 总则",
        normalized_text="第一章 总则",
        chunk_hash="chunk-hash-1",
        doc_type=document.doc_type,
        doc_title=document.title,
        metadata={"article_no": "第一条"},
    )
    task = create_ingest_task(
        db_session,
        document_id=document.id,
        version_id=version.id,
        task_type="ingest",
        status="queued",
    )

    loaded_version = get_by_id(db_session, DocumentVersion, version.id)
    loaded_chunk = get_by_id(db_session, Chunk, chunk.id)
    loaded_task = get_by_id(db_session, IngestTask, task.id)

    assert loaded_version is not None and loaded_version.document_id == document.id
    assert loaded_chunk is not None and loaded_chunk.version_id == version.id
    assert loaded_task is not None and loaded_task.progress == 0


def test_create_eval_dataset_and_run(db_session) -> None:
    dataset = create_eval_dataset(
        db_session,
        name="phase1-eval-dataset",
        description="用于验证 Phase 1 的最小评测表结构",
    )
    run = create_eval_run(
        db_session,
        dataset_id=dataset.id,
        status="queued",
        total_count=10,
    )

    loaded_dataset = get_by_id(db_session, EvalDataset, dataset.id)
    loaded_run = get_by_id(db_session, EvalRun, run.id)

    assert loaded_dataset is not None
    assert loaded_run is not None
    assert loaded_run.dataset_id == dataset.id
    assert loaded_run.total_count == 10
