"""异步入库任务可靠性状态机集成测试。"""

from __future__ import annotations

import uuid

import pytest

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.ingest_task import IngestTask
from app.services.ingest_task_service import claim, complete, fail, mark_dispatch_failed

pytestmark = pytest.mark.integration


def _create_task(db_session) -> IngestTask:
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    task_id = uuid.uuid4()
    document = Document(
        id=document_id,
        title="可靠性测试",
        doc_type="note",
        source_filename="source.txt",
        storage_path="storage/source.txt",
        status="active",
        security_domain=[],
        tags=[],
        current_version_id=None,
    )
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_no=1,
        file_hash="hash",
        file_size=1,
        mime_type="text/plain",
        storage_path="storage/source.txt",
        version_status="draft",
    )
    task = IngestTask(
        id=task_id,
        document_id=document_id,
        version_id=version_id,
        task_type="ingest",
        status="queued",
        dispatch_status="pending",
        progress=0,
    )
    db_session.add_all([document, version, task])
    db_session.commit()
    return task


def test_dispatch_failure_compensates_and_redacts_error(db_session) -> None:
    task = _create_task(db_session)

    mark_dispatch_failed(
        db_session,
        task.id,
        "redis://user:secret@redis:6379/0 password=hunter2",
        celery_task_id="message-id",
    )

    db_session.refresh(task)
    assert task.status == "failed"
    assert task.dispatch_status == "failed"
    assert task.celery_task_id == "message-id"
    assert task.finished_at is not None
    assert task.error_message is not None
    assert "secret" not in task.error_message
    assert "hunter2" not in task.error_message


def test_attempt_token_fences_stale_worker_and_terminal_is_noop(db_session) -> None:
    task = _create_task(db_session)
    first_token = claim(db_session, task.id, "worker-1")
    assert first_token is not None

    task.status = "queued"
    task.worker_id = None
    task.attempt_token = None
    task.last_heartbeat_at = None
    db_session.commit()
    second_token = claim(db_session, task.id, "worker-2")
    assert second_token is not None
    assert second_token != first_token

    assert complete(db_session, task.id, first_token, "旧 worker 完成") is False
    assert fail(db_session, task.id, first_token, "worker_lost", "旧 worker 失败") is False
    assert complete(db_session, task.id, second_token, "新 worker 完成") is True
    assert fail(db_session, task.id, second_token, "late_failure", "迟到失败") is False

    db_session.refresh(task)
    assert task.status == "completed"
    assert task.progress == 100
    assert task.message == "新 worker 完成"
