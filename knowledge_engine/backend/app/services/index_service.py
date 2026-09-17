"""索引服务（embedding + Qdrant + FTS 编排层）。

Phase 5 只负责把 child chunk 建立为“可检索索引数据”：
- 过滤 child chunk
- 组织统一 payload
- 生成 embedding
- 写入 Qdrant
- 更新 PostgreSQL `search_tsv`

本模块明确不做：
- 检索查询
- RRF 融合
- reranker 接入查询链路
- answer generation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document_version import DocumentVersion
from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.services.keyword_store import KeywordStore
from app.services.vector_store import QdrantVectorStore, VectorPoint


class IndexServiceError(RuntimeError):
    """索引编排异常。"""


@dataclass(slots=True)
class IndexBuildResult:
    """一次索引构建的结果摘要。"""

    indexed_chunk_count: int
    vector_upsert_count: int
    keyword_updated_count: int


class IndexService:
    """Phase 5 索引编排服务。"""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        vector_store: QdrantVectorStore,
        keyword_store: KeywordStore,
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.keyword_store = keyword_store

    @classmethod
    def from_db(
        cls,
        db: Session,
        *,
        embedding_service: EmbeddingService | None = None,
        vector_store: QdrantVectorStore | None = None,
        allow_embedding_fallback: bool = False,
    ) -> "IndexService":
        """按当前数据库会话构造索引服务。"""
        resolved_embedding = embedding_service or get_embedding_service(allow_fallback=allow_embedding_fallback)
        resolved_vector_store = vector_store or QdrantVectorStore.from_settings()
        resolved_vector_store.expected_embedding_identity = resolved_embedding.identity
        resolved_keyword_store = KeywordStore.from_db(db)
        return cls(
            embedding_service=resolved_embedding,
            vector_store=resolved_vector_store,
            keyword_store=resolved_keyword_store,
        )

    def build_chunk_indexes(self, chunks: list[Chunk], *, version: DocumentVersion) -> IndexBuildResult:
        """为当前版本的 child chunk 建立向量与关键词索引。"""
        child_chunks = [chunk for chunk in chunks if chunk.chunk_type == "child" and chunk.is_active]
        if not child_chunks:
            return IndexBuildResult(indexed_chunk_count=0, vector_upsert_count=0, keyword_updated_count=0)

        self.vector_store.ensure_collection()
        self._validate_existing_index_identity()
        embeddings = self.embedding_service.embed_texts([chunk.normalized_text for chunk in child_chunks])
        payloads = [
            {**self.build_payload(chunk, version=version), "embedding_identity": self.embedding_service.identity}
            for chunk in child_chunks
        ]
        points = [
            VectorPoint(
                chunk_id=str(chunk.id),
                vector=vector,
                payload=payload,
            )
            for chunk, vector, payload in zip(child_chunks, embeddings, payloads, strict=True)
        ]
        vector_upsert_count = self.vector_store.upsert_chunks(points)
        keyword_updated_count = self.keyword_store.update_child_chunk_search_vectors([chunk.id for chunk in child_chunks])
        return IndexBuildResult(
            indexed_chunk_count=len(child_chunks),
            vector_upsert_count=vector_upsert_count,
            keyword_updated_count=keyword_updated_count,
        )

    def _validate_existing_index_identity(self) -> None:
        self.vector_store.validate_embedding_identity(allow_empty=True)

    @staticmethod
    def build_payload(chunk: Chunk, *, version: DocumentVersion) -> dict[str, Any]:
        """统一组装 Qdrant payload。"""
        return {
            "chunk_id": str(chunk.id),
            "document_id": str(chunk.document_id),
            "version_id": str(chunk.version_id),
            "doc_type": chunk.doc_type,
            "doc_title": chunk.doc_title,
            "chapter": chunk.chapter,
            "section": chunk.section,
            "article_no": chunk.article_no,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "security_domain": list(chunk.security_domain or []),
            "version_status": version.version_status,
            "is_active": chunk.is_active,
            "chunk_type": chunk.chunk_type,
            "parent_chunk_id": str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None,
            "chunk_hash": chunk.chunk_hash,
            "chunk_text": chunk.text,
            "text": chunk.text,
            "is_current_version": version.version_status == "active",
        }
