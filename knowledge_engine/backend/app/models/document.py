"""documents 表 ORM 模型。

Phase 1 实现逻辑文档主表：只承载持久化结构，不在模型中提前写后续业务流程。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.document_version import DocumentVersion
    from app.models.ingest_task import IngestTask


class Document(Base):
    """逻辑文档主表。"""

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_doc_type", "doc_type"),
        Index("idx_documents_status", "status"),
        Index("idx_documents_created_at", text("created_at DESC")),
        Index("idx_documents_current_version_id", "current_version_id"),
        Index("idx_documents_security_domain_gin", "security_domain", postgresql_using="gin"),
        Index("idx_documents_tags_gin", "tags", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default=text("'active'"))
    security_domain: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
    )
    current_version: Mapped["DocumentVersion | None"] = relationship(
        "DocumentVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document")
    ingest_tasks: Mapped[list["IngestTask"]] = relationship(back_populates="document")
