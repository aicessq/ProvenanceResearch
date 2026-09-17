"""PostgreSQL FTS 关键词检索封装。

Phase 5 负责打通 child chunk 的 `search_tsv` 更新链路。
Phase 6 在此基础上补齐 FTS 检索能力，供混合检索链路复用。
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.services.fusion import RetrievalHit
from app.services.metadata_filter import MetadataFilter


class KeywordStoreError(RuntimeError):
    """关键词索引更新异常。"""


class KeywordStore:
    """基于 PostgreSQL tsvector 的关键词索引写入与检索封装。"""

    def __init__(self, db: Session, *, language_config: str) -> None:
        self.db = db
        self.language_config = language_config

    @classmethod
    def from_db(cls, db: Session) -> "KeywordStore":
        """按全局配置构造 keyword store。"""
        settings = get_settings()
        return cls(db, language_config=settings.fts_language_config)

    def update_child_chunk_search_vectors(self, chunk_ids: Sequence[str | UUID]) -> int:
        """仅对 child chunk 更新 `search_tsv` 字段。"""
        normalized_ids = [UUID(str(chunk_id)) for chunk_id in chunk_ids]
        if not normalized_ids:
            return 0

        vector_text = (
            func.coalesce(cast(Chunk.article_no, String), "")
            + " "
            + func.coalesce(cast(Chunk.chapter, String), "")
            + " "
            + func.coalesce(cast(Chunk.section, String), "")
            + " "
            + func.coalesce(cast(Chunk.doc_title, String), "")
            + " "
            + func.coalesce(cast(Chunk.normalized_text, String), "")
        )
        statement = (
            update(Chunk)
            .where(Chunk.id.in_(normalized_ids))
            .where(Chunk.chunk_type == "child")
            .where(Chunk.is_active.is_(True))
            .values(search_tsv=func.to_tsvector(self.language_config, vector_text))
        )
        result = self.db.execute(statement)
        self.db.flush()
        return int(result.rowcount or 0)

    def search(self, query: str, *, top_k: int = 30, filters: MetadataFilter | None = None) -> list[RetrievalHit]:
        """基于 PostgreSQL FTS 检索 child chunk。"""
        effective_filters = filters or MetadataFilter()
        ts_query = func.websearch_to_tsquery(self.language_config, query)
        rank = func.ts_rank_cd(Chunk.search_tsv, ts_query)
        current_version = aliased(DocumentVersion)
        statement = (
            select(Chunk, current_version.version_status, Document.current_version_id, rank.label("rank"))
            .join(Document, Document.id == Chunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .join(current_version, current_version.id == Document.current_version_id, isouter=True)
            .where(Chunk.chunk_type == "child")
            .where(Chunk.search_tsv.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(top_k)
        )
        statement = self._apply_filters(statement, effective_filters, current_version)
        rows = self.db.execute(statement).all()

        fts_hits = [self._row_to_hit(chunk, version_status, score=float(hit_rank or 0.0)) for chunk, version_status, _current_version_id, hit_rank in rows]
        fallback = self._build_ilike_fallback_query(
            query, top_k=top_k, filters=effective_filters, current_version=current_version
        )
        fallback_rows = self.db.execute(fallback).all()
        combined = [
            *fts_hits,
            *[
                self._row_to_hit(chunk, version_status, score=0.0)
                for chunk, version_status, _current_version_id in fallback_rows
            ],
        ]
        unique_hits: dict[str, RetrievalHit] = {}
        for hit in combined:
            unique_hits.setdefault(hit.chunk_id, hit)
        return list(unique_hits.values())[:top_k]

    @staticmethod
    def _row_to_hit(chunk: Chunk, version_status: str | None, *, score: float) -> RetrievalHit:
        metadata = {
            "chunk_id": str(chunk.id), "chunk_hash": chunk.chunk_hash,
            "document_id": str(chunk.document_id), "version_id": str(chunk.version_id),
            "doc_title": chunk.doc_title, "doc_type": chunk.doc_type,
            "chapter": chunk.chapter, "section": chunk.section, "article_no": chunk.article_no,
            "page_start": chunk.page_start, "page_end": chunk.page_end,
            "parent_chunk_id": str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None,
            "version_status": version_status, "security_domain": list(chunk.security_domain),
            "is_active": chunk.is_active, "chunk_type": chunk.chunk_type,
        }
        return RetrievalHit(
            chunk_id=str(chunk.id), score=score, source="keyword", chunk_text=chunk.text,
            document_id=str(chunk.document_id), version_id=str(chunk.version_id),
            doc_title=chunk.doc_title, doc_type=chunk.doc_type, chapter=chunk.chapter,
            section=chunk.section, article_no=chunk.article_no, page_start=chunk.page_start,
            page_end=chunk.page_end,
            parent_chunk_id=str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None,
            version_status=version_status, is_active=chunk.is_active,
            security_domain=list(chunk.security_domain), metadata=metadata,
        )

    def deactivate_chunks(self, chunk_ids: Sequence[str | UUID]) -> int:
        """把指定 chunk 软删除为不可检索。"""
        normalized_ids = [UUID(str(chunk_id)) for chunk_id in chunk_ids]
        if not normalized_ids:
            return 0
        statement = (
            update(Chunk)
            .where(Chunk.id.in_(normalized_ids))
            .values(is_active=False, search_tsv=None)
        )
        result = self.db.execute(statement)
        self.db.flush()
        return int(result.rowcount or 0)

    def _apply_filters(self, statement, filters: MetadataFilter, current_version_alias):
        """把显式 metadata filter 应用到 SQL 查询。"""
        statement = statement.where(Chunk.is_active.is_(filters.is_active))
        statement = statement.where(Document.status == "active")
        if filters.doc_type:
            statement = statement.where(Chunk.doc_type.in_(filters.doc_type))
        if filters.doc_title:
            statement = statement.where(Chunk.doc_title.in_(filters.doc_title))
        if filters.version_status:
            statement = statement.where(DocumentVersion.version_status.in_(filters.version_status))
        if filters.security_domain:
            statement = statement.where(Chunk.security_domain.op("?|" )(filters.security_domain))
        if filters.chapter:
            statement = statement.where(Chunk.chapter.in_(filters.chapter))
        if filters.section:
            statement = statement.where(Chunk.section.in_(filters.section))
        if filters.article_no:
            statement = statement.where(Chunk.article_no.in_(filters.article_no))
        if filters.page_start is not None:
            statement = statement.where(Chunk.page_start >= filters.page_start)
        if filters.page_end is not None:
            statement = statement.where(Chunk.page_end <= filters.page_end)
        if filters.current_version_only:
            statement = statement.where(Chunk.version_id == Document.current_version_id)
            statement = statement.where(current_version_alias.version_status == "active")
        return statement

    def _build_ilike_fallback_query(self, query: str, *, top_k: int, filters: MetadataFilter, current_version):
        """FTS 未命中时，对编号/术语类内容做保守 ILIKE 兜底。"""
        pattern = f"%{_escape_ilike(query)}%"
        statement = (
            select(Chunk, current_version.version_status, Document.current_version_id)
            .join(Document, Document.id == Chunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .join(current_version, current_version.id == Document.current_version_id, isouter=True)
            .where(Chunk.chunk_type == "child")
            .where(
                or_(
                    Chunk.normalized_text.ilike(pattern, escape="\\"),
                    Chunk.doc_title.ilike(pattern, escape="\\"),
                    Chunk.article_no.ilike(pattern, escape="\\"),
                )
            )
            .limit(top_k)
        )
        return self._apply_filters(statement, filters, current_version)


def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
