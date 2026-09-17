"""周期扫描并恢复卡住的异步入库任务。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.services.ingest_task_service import (
    fail_locked_task,
    find_stale_processing,
    find_stale_queued,
    prepare_queued_recovery,
    requeue_stale_processing,
    safe_error_message,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()
_ALLOWED_TASK_TYPES = frozenset({"ingest", "replace"})


def _source_path(version: DocumentVersion) -> Path | None:
    root = settings.storage_root.resolve()
    candidate = Path(version.storage_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _dispatch(task, version: DocumentVersion, celery_task_id: str) -> None:
    kwargs = {
        "document_id": str(task.document_id),
        "version_id": str(task.version_id),
        "task_id": str(task.id),
        "file_path": str(version.storage_path),
    }
    if task.task_type == "ingest":
        from app.workers.ingest_worker import ingest_document_task

        ingest_document_task.apply_async(kwargs=kwargs, task_id=celery_task_id)
    else:
        from app.workers.ingest_worker import replace_document_task

        replace_document_task.apply_async(kwargs=kwargs, task_id=celery_task_id)


def _validate_records(db, task, now: datetime) -> tuple[Document, DocumentVersion] | None:
    if task.task_type not in _ALLOWED_TASK_TYPES:
        fail_locked_task(task, now=now, error_code="unsupported_task_type", safe_message="任务类型不在恢复白名单")
        return None
    document = db.get(Document, task.document_id)
    version = db.get(DocumentVersion, task.version_id)
    if document is None or version is None or version.document_id != task.document_id:
        fail_locked_task(task, now=now, error_code="record_missing", safe_message="document 或 version 记录不存在")
        return None
    if _source_path(version) is None:
        fail_locked_task(task, now=now, error_code="source_file_missing", safe_message="源文件不存在或不在共享存储目录")
        return None
    return document, version


def _redispatch_locked(db, task, version: DocumentVersion, now: datetime) -> bool:
    celery_task_id = str(uuid.uuid4())
    if not prepare_queued_recovery(
        task,
        celery_task_id=celery_task_id,
        max_recovery_count=settings.task_max_recovery_count,
        now=now,
    ):
        return False
    try:
        _dispatch(task, version, celery_task_id)
    except Exception as exc:  # noqa: BLE001 - 保留 queued 供下轮恢复
        task.dispatch_status = "pending"
        task.error_message = f"dispatch_unavailable: {safe_error_message(exc)}"
        task.updated_at = now
        logger.exception("恢复任务重派失败: task_id=%s celery_task_id=%s", task.id, celery_task_id)
        return False
    task.dispatch_status = "dispatched"
    task.dispatched_at = now
    task.error_message = None
    logger.info("恢复任务已重派: task_id=%s celery_task_id=%s", task.id, celery_task_id)
    return True


@celery_app.task(name="app.workers.recovery_worker.recover_stale_tasks")
def recover_stale_tasks() -> dict[str, int]:
    """使用 SKIP LOCKED 批量处理 stale queued/processing。"""
    db = SessionLocal()
    stats = {"queued_recovered": 0, "processing_recovered": 0, "failed": 0}
    try:
        now = datetime.now(timezone.utc)
        queued = find_stale_queued(
            db,
            now=now,
            queued_stale_seconds=settings.queued_stale_seconds,
            dispatched_stale_seconds=settings.dispatched_queue_stale_seconds,
            batch_size=settings.task_recovery_batch_size,
        )
        for task in queued:
            records = _validate_records(db, task, now)
            if records is None:
                stats["failed"] += 1
                continue
            if _redispatch_locked(db, task, records[1], now):
                stats["queued_recovered"] += 1
        db.commit()

        processing = find_stale_processing(
            db,
            now=now,
            lease_timeout_seconds=settings.processing_lease_timeout_seconds,
            batch_size=settings.task_recovery_batch_size,
        )
        for task in processing:
            records = _validate_records(db, task, now)
            if records is None:
                stats["failed"] += 1
                continue
            if not settings.task_auto_recover_processing or task.task_type != "ingest":
                fail_locked_task(task, now=now, error_code="worker_lost", safe_message="worker 心跳超时，已停止自动执行")
                stats["failed"] += 1
                logger.warning("processing 任务租约过期并标记失败: task_id=%s task_type=%s", task.id, task.task_type)
                continue
            if requeue_stale_processing(task, now=now, max_recovery_count=settings.task_max_recovery_count):
                if _redispatch_locked(db, task, records[1], now):
                    stats["processing_recovered"] += 1
            else:
                stats["failed"] += 1
        db.commit()
        return stats
    except Exception:  # noqa: BLE001 - 周期任务必须回滚并留下日志
        db.rollback()
        logger.exception("stale 异步任务恢复扫描失败")
        raise
    finally:
        db.close()
