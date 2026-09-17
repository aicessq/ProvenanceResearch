"""Phase 1 模型层测试。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.eval_dataset import EvalDataset
from app.models.feedback import Feedback
from app.models.query_log import QueryLog


@pytest.mark.integration
def test_document_defaults(db_session) -> None:
    """documents 的 JSONB/状态默认值应符合规格。"""
    document = Document(
        title="网络安全法",
        doc_type="law",
        source_filename="law.pdf",
        storage_path="raw/law.pdf",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    assert document.status == "active"
    assert document.security_domain == []
    assert document.tags == []
    assert document.current_version_id is None


@pytest.mark.integration
def test_document_version_unique_constraint(db_session) -> None:
    """同一 document 下 version_no 应唯一。"""
    document = Document(
        title="等级保护标准",
        doc_type="standard",
        source_filename="gbt.pdf",
        storage_path="raw/gbt.pdf",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    version1 = DocumentVersion(
        document_id=document.id,
        version_no=1,
        file_hash="hash-1",
        file_size=100,
        mime_type="application/pdf",
        storage_path="versions/v1.pdf",
    )
    version2 = DocumentVersion(
        document_id=document.id,
        version_no=1,
        file_hash="hash-2",
        file_size=200,
        mime_type="application/pdf",
        storage_path="versions/v1-dup.pdf",
    )

    db_session.add(version1)
    db_session.commit()

    db_session.add(version2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.integration
def test_feedback_foreign_key_constraint(db_session) -> None:
    """feedback.query_log_id 应受外键约束保护。"""
    feedback = Feedback(score=5, query_log_id=uuid.UUID("00000000-0000-0000-0000-000000000001"))
    db_session.add(feedback)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.integration
def test_eval_dataset_defaults(db_session) -> None:
    """评测数据集默认状态应为 active。"""
    dataset = EvalDataset(name="phase1-dataset")
    db_session.add(dataset)
    db_session.commit()
    db_session.refresh(dataset)

    assert dataset.status == "active"


@pytest.mark.integration
def test_migration_creates_core_tables_and_indexes(db_session) -> None:
    """迁移后应存在核心表与关键索引。"""
    inspector = inspect(db_session.bind)

    table_names = set(inspector.get_table_names())
    assert {"documents", "document_versions", "chunks", "ingest_tasks", "query_logs", "feedback", "eval_datasets", "eval_dataset_items", "eval_runs", "eval_run_items"}.issubset(table_names)

    document_indexes = {index["name"] for index in inspector.get_indexes("documents")}
    chunk_indexes = {index["name"] for index in inspector.get_indexes("chunks")}

    assert "idx_documents_doc_type" in document_indexes
    assert "idx_documents_current_version_id" in document_indexes
    assert "idx_chunks_chunk_hash" in chunk_indexes
    assert "idx_chunks_parent_chunk_id" in chunk_indexes

    query_log = QueryLog(user_query="什么是零信任")
    db_session.add(query_log)
    db_session.commit()
    assert query_log.id is not None
