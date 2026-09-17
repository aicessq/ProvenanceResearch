"""ingest_tasks 表 ORM 模型。"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_version import DocumentVersion


class IngestTask(Base):
    """文档入库/替换任务持久化表。"""

    __tablename__ = "ingest_tasks"
    __table_args__ = (
        Index("idx_ingest_tasks_document_id", "document_id"),
        Index("idx_ingest_tasks_version_id", "version_id"),
        Index("idx_ingest_tasks_status", "status"),
        Index("idx_ingest_tasks_task_type", "task_type"),
        Index("idx_ingest_tasks_created_at", text("created_at DESC")),
        Index("idx_ingest_tasks_stale_dispatch", "status", "dispatch_status", "updated_at"),
        Index("idx_ingest_tasks_stale_processing", "status", "last_heartbeat_at"),
        Index("idx_ingest_tasks_celery_task_id", "celery_task_id"),
        CheckConstraint("attempt_count >= 0", name="ck_ingest_tasks_attempt_count_nonnegative"),
        CheckConstraint("recovery_count >= 0", name="ck_ingest_tasks_recovery_count_nonnegative"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_ingest_tasks_status",
        ),
        CheckConstraint(
            "dispatch_status IN ('pending', 'dispatched', 'failed')",
            name="ck_ingest_tasks_dispatch_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dispatch_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default=text("'pending'")
    )
    dispatched_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="ingest_tasks")
    version: Mapped["DocumentVersion"] = relationship(back_populates="ingest_tasks")
