"""异步入库任务的数据库状态机与恢复原语。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from app.models.ingest_task import IngestTask

TERMINAL_STATUSES = frozenset({"completed", "failed"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def safe_error_message(error: object, *, fallback: str = "异步任务处理失败") -> str:
    """生成适合持久化和对外展示的脱敏错误信息。"""
    message = str(error).replace("\r", " ").replace("\n", " ").strip() or fallback
    message = re.sub(r"(?i)(password|passwd|pwd|token|secret)=([^\s&;]+)", r"\1=***", message)
    message = re.sub(r"(?i)(redis|postgres(?:ql)?|amqp)://[^\s]+", r"\1://***", message)
    return message[:1000]


def mark_dispatch_succeeded(db: Session, task_id: uuid.UUID, celery_task_id: str) -> IngestTask | None:
    task = db.get(IngestTask, task_id)
    if task is None or task.status in TERMINAL_STATUSES:
        return task
    now = _now()
    task.celery_task_id = celery_task_id
    task.dispatch_status = "dispatched"
    task.dispatched_at = now
    task.error_message = None
    task.updated_at = now
    db.commit()
    return task


def mark_dispatch_failed(
    db: Session,
    task_id: uuid.UUID,
    error: object,
    *,
    celery_task_id: str | None = None,
    message: str = "异步任务投递失败",
) -> IngestTask | None:
    task = db.get(IngestTask, task_id)
    if task is None or task.status in TERMINAL_STATUSES:
        return task
    now = _now()
    task.status = "failed"
    task.dispatch_status = "failed"
    task.celery_task_id = celery_task_id or task.celery_task_id
    task.message = message
    task.error_message = safe_error_message(error, fallback=message)
    task.worker_id = None
    task.attempt_token = None
    task.last_heartbeat_at = None
    task.finished_at = now
    task.updated_at = now
    db.commit()
    return task


def claim(db: Session, task_id: uuid.UUID, worker_id: str) -> uuid.UUID | None:
    """以行锁原子领取 queued 任务，返回本次 fencing token。"""
    task = db.execute(
        select(IngestTask).where(IngestTask.id == task_id).with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if task is None or task.status != "queued":
        db.rollback()
        return None
    now = _now()
    token = uuid.uuid4()
    task.status = "processing"
    task.worker_id = worker_id
    task.attempt_token = token
    task.last_heartbeat_at = now
    task.attempt_count += 1
    task.error_message = None
    task.finished_at = None
    task.updated_at = now
    db.commit()
    return token


def heartbeat(db: Session, task_id: uuid.UUID, attempt_token: uuid.UUID) -> bool:
    now = _now()
    result = db.execute(
        update(IngestTask)
        .where(IngestTask.id == task_id)
        .where(IngestTask.status == "processing")
        .where(IngestTask.attempt_token == attempt_token)
        .values(last_heartbeat_at=now, updated_at=now)
    )
    db.commit()
    return result.rowcount == 1


def complete(
    db: Session, task_id: uuid.UUID, attempt_token: uuid.UUID, message: str | None = None
) -> bool:
    now = _now()
    result = db.execute(
        update(IngestTask)
        .where(IngestTask.id == task_id)
        .where(IngestTask.status == "processing")
        .where(IngestTask.attempt_token == attempt_token)
        .values(
            status="completed",
            progress=100,
            message=message,
            error_message=None,
            worker_id=None,
            attempt_token=None,
            last_heartbeat_at=None,
            finished_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return result.rowcount == 1


def fail(
    db: Session,
    task_id: uuid.UUID,
    attempt_token: uuid.UUID,
    error_code: str,
    safe_message: str,
) -> bool:
    now = _now()
    error = f"{error_code}: {safe_error_message(safe_message)}"
    result = db.execute(
        update(IngestTask)
        .where(IngestTask.id == task_id)
        .where(IngestTask.status == "processing")
        .where(IngestTask.attempt_token == attempt_token)
        .values(
            status="failed",
            message="异步任务执行失败",
            error_message=error,
            worker_id=None,
            attempt_token=None,
            last_heartbeat_at=None,
            finished_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return result.rowcount == 1


def _locked_stale_query(statement: Select[tuple[IngestTask]], batch_size: int) -> Select[tuple[IngestTask]]:
    return statement.order_by(IngestTask.updated_at).limit(batch_size).with_for_update(skip_locked=True)


def find_stale_queued(
    db: Session,
    *,
    now: datetime,
    queued_stale_seconds: int,
    dispatched_stale_seconds: int,
    batch_size: int,
) -> list[IngestTask]:
    queued_cutoff = now - timedelta(seconds=queued_stale_seconds)
    dispatched_cutoff = now - timedelta(seconds=dispatched_stale_seconds)
    statement = select(IngestTask).where(
        IngestTask.status == "queued",
        ((IngestTask.dispatch_status != "dispatched") & (IngestTask.updated_at < queued_cutoff))
        | ((IngestTask.dispatch_status == "dispatched") & (IngestTask.updated_at < dispatched_cutoff)),
    )
    return list(db.execute(_locked_stale_query(statement, batch_size)).scalars())


def prepare_queued_recovery(
    task: IngestTask, *, celery_task_id: str, max_recovery_count: int, now: datetime
) -> bool:
    """在 stale 扫描持有的行锁内登记一次重派；调用方随后投递并提交结果。"""
    if task.status != "queued":
        return False
    if task.recovery_count >= max_recovery_count:
        task.status = "failed"
        task.dispatch_status = "failed"
        task.error_message = "attempts_exhausted: 任务恢复次数已达上限"
        task.finished_at = now
        task.updated_at = now
        return False
    task.recovery_count += 1
    task.celery_task_id = celery_task_id
    task.dispatch_status = "pending"
    task.error_message = None
    task.updated_at = now
    return True


def find_stale_processing(
    db: Session, *, now: datetime, lease_timeout_seconds: int, batch_size: int
) -> list[IngestTask]:
    cutoff = now - timedelta(seconds=lease_timeout_seconds)
    statement = select(IngestTask).where(
        IngestTask.status == "processing",
        IngestTask.last_heartbeat_at < cutoff,
    )
    return list(db.execute(_locked_stale_query(statement, batch_size)).scalars())


def fail_locked_task(
    task: IngestTask, *, now: datetime, error_code: str, safe_message: str
) -> None:
    """在恢复扫描持有行锁时将任务收敛为失败。"""
    task.status = "failed"
    task.dispatch_status = "failed"
    task.message = "异步任务恢复失败"
    task.error_message = f"{error_code}: {safe_error_message(safe_message)}"
    task.worker_id = None
    task.attempt_token = None
    task.last_heartbeat_at = None
    task.finished_at = now
    task.updated_at = now


def requeue_stale_processing(task: IngestTask, *, now: datetime, max_recovery_count: int) -> bool:
    """在 stale 扫描行锁内撤销旧租约；旧 token 随即失效。"""
    if task.status != "processing":
        return False
    task.worker_id = None
    task.attempt_token = None
    task.last_heartbeat_at = None
    task.updated_at = now
    if task.recovery_count >= max_recovery_count:
        task.status = "failed"
        task.dispatch_status = "failed"
        task.error_message = "attempts_exhausted: 任务恢复次数已达上限"
        task.finished_at = now
        return False
    task.status = "queued"
    task.dispatch_status = "pending"
    task.error_message = "worker_lost: worker 心跳超时，等待恢复"
    task.finished_at = None
    return True


def get_task(db: Session, task_id: uuid.UUID) -> IngestTask | None:
    return db.get(IngestTask, task_id)
