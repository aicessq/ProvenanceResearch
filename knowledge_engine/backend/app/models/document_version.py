"""document_versions 表 ORM 模型。

Phase 1 实现文档版本表，承载后续 replace / 增量更新所依赖的版本元数据。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.document import Document
    from app.models.ingest_task import IngestTask


class DocumentVersion(Base):
    """文档版本表。"""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_document_versions_document_id_version_no"),
        Index("idx_document_versions_document_id", "document_id"),
        Index("idx_document_versions_version_status", "version_status"),
        Index("idx_document_versions_effective_date", "effective_date"),
        Index("idx_document_versions_publish_date", "publish_date"),
        Index("idx_document_versions_file_hash", "file_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    publish_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    expire_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))

    document: Mapped["Document"] = relationship(
        back_populates="versions",
        foreign_keys=[document_id],
    )
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="version")
    ingest_tasks: Mapped[list["IngestTask"]] = relationship(back_populates="version")
