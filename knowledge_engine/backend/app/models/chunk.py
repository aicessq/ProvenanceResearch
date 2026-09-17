"""chunks 表 ORM 模型。

Phase 1 仅定义 chunk 持久化结构与索引，不提前实现切分、索引或检索逻辑。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_version import DocumentVersion


class Chunk(Base):
    """文档 chunk 表。"""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="uq_chunks_version_id_chunk_index"),
        Index("idx_chunks_document_id", "document_id"),
        Index("idx_chunks_version_id", "version_id"),
        Index("idx_chunks_doc_type", "doc_type"),
        Index("idx_chunks_chunk_type", "chunk_type"),
        Index("idx_chunks_is_active", "is_active"),
        Index("idx_chunks_chunk_hash", "chunk_hash"),
        Index("idx_chunks_parent_chunk_id", "parent_chunk_id"),
        Index("idx_chunks_article_no", "article_no"),
        Index("idx_chunks_page_start", "page_start"),
        Index("idx_chunks_page_end", "page_end"),
        Index("idx_chunks_metadata_gin", "metadata", postgresql_using="gin"),
        Index("idx_chunks_security_domain_gin", "security_domain", postgresql_using="gin"),
        Index("idx_chunks_keywords_gin", "keywords", postgresql_using="gin"),
        Index("idx_chunks_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_title: Mapped[str] = mapped_column(String(512), nullable=False)
    chapter: Mapped[str | None] = mapped_column(String(512), nullable=True)
    section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    article_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security_domain: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb"))
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb"))
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_text("TRUE"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("NOW()"))

    document: Mapped["Document"] = relationship(back_populates="chunks")
    version: Mapped["DocumentVersion"] = relationship(back_populates="chunks")
    parent_chunk: Mapped["Chunk | None"] = relationship("Chunk", remote_side=[id], back_populates="child_chunks")
    child_chunks: Mapped[list["Chunk"]] = relationship("Chunk", back_populates="parent_chunk")
