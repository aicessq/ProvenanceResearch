"""安全重建全量向量索引的编排服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_qdrant_client
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.services.index_service import IndexService
from app.services.vector_store import (
    QdrantClientProtocol,
    QdrantVectorStore,
    VectorPoint,
    VectorStoreError,
)


class ReindexServiceError(RuntimeError):
    """安全重建前置条件不满足。"""


class ReindexService:
    """将 PostgreSQL 当前有效 child chunks 写入显式的新 collection。"""

    def __init__(
        self,
        *,
        db: Session,
        embedding_service: EmbeddingService,
        qdrant_client: QdrantClientProtocol,
        current_collection: str,
        distance_metric: str,
    ) -> None:
        self.db = db
        self.embedding_service = embedding_service
        self.qdrant_client = qdrant_client
        self.current_collection = current_collection
        self.distance_metric = distance_metric

    @classmethod
    def from_db(
        cls,
        db: Session,
        *,
        target_collection: str,
    ) -> "ReindexService":
        """使用严格真实 embedding 配置构造服务，不允许 fallback。"""
        del target_collection
        settings = get_settings()
        client = get_qdrant_client()
        if client is None:
            raise ReindexServiceError("Qdrant 客户端不可用，无法安全重建索引")
        embedding_service = get_embedding_service(allow_fallback=False)
        return cls(
            db=db,
            embedding_service=embedding_service,
            qdrant_client=client,
            current_collection=settings.qdrant_collection,
            distance_metric=settings.qdrant_distance_metric,
        )

    def rebuild(
        self,
        target_collection: str,
        *,
        batch_size: int = 128,
    ) -> dict[str, Any]:
        """分批重建至空的新 collection；绝不修改当前 collection。"""
        target_collection = target_collection.strip()
        if not target_collection:
            raise ReindexServiceError("必须显式指定目标 collection")
        if target_collection == self.current_collection:
            raise ReindexServiceError("目标 collection 必须不同于当前 collection")
        if batch_size <= 0:
            raise ReindexServiceError("batch_size 必须大于 0")

        target_exists = self.qdrant_client.collection_exists(target_collection)
        if target_exists:
            count_result = self.qdrant_client.count(
                collection_name=target_collection,
                exact=True,
            )
            if int(getattr(count_result, "count", 0)) > 0:
                raise ReindexServiceError("目标 collection 已非空，拒绝混写")

        vector_store = QdrantVectorStore(
            self.qdrant_client,
            collection_name=target_collection,
            vector_size=self.embedding_service.vector_size,
            distance_metric=self.distance_metric,
            expected_embedding_identity=self.embedding_service.identity,
        )
        try:
            vector_store.ensure_collection()
        except VectorStoreError as exc:
            raise ReindexServiceError(f"目标 collection 配置校验失败：{exc}") from exc

        selected_count = 0
        embedded_count = 0
        upserted_count = 0
        batch_count = 0
        result = self.db.execute(self._active_current_child_query())
        for rows in result.partitions(batch_size):
            chunks = [row[0] for row in rows]
            versions = [row[1] for row in rows]
            vectors = self.embedding_service.embed_texts(
                [chunk.normalized_text for chunk in chunks]
            )
            points = [
                VectorPoint(
                    chunk_id=str(chunk.id),
                    vector=vector,
                    payload={
                        **IndexService.build_payload(chunk, version=version),
                        "embedding_identity": self.embedding_service.identity,
                    },
                )
                for chunk, version, vector in zip(chunks, versions, vectors, strict=True)
            ]
            selected_count += len(chunks)
            embedded_count += len(vectors)
            upserted_count += vector_store.upsert_chunks(points)
            batch_count += 1

        count_result = self.qdrant_client.count(
            collection_name=target_collection,
            exact=True,
        )
        verified_point_count = int(getattr(count_result, "count", 0))
        if verified_point_count != selected_count:
            raise ReindexServiceError(
                "目标 collection 点数校验失败："
                f"期望 {selected_count}，实际 {verified_point_count}"
            )
        try:
            vector_store.validate_embedding_identity(allow_empty=selected_count == 0)
        except VectorStoreError as exc:
            raise ReindexServiceError(f"目标 collection 身份校验失败：{exc}") from exc

        return {
            "processed_count": selected_count,
            "selected_count": selected_count,
            "embedded_count": embedded_count,
            "upserted_count": upserted_count,
            "verified_point_count": verified_point_count,
            "identity_verified": True,
            "batch_count": batch_count,
            "target_collection": target_collection,
            "embedding_identity": self.embedding_service.identity,
            "embedding_model": self.embedding_service.model_name,
            "vector_size": self.embedding_service.vector_size,
        }

    @staticmethod
    def _active_current_child_query():
        return (
            select(Chunk, DocumentVersion)
            .join(Document, Document.id == Chunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .where(
                Chunk.is_active.is_(True),
                Chunk.chunk_type == "child",
                Document.status == "active",
                Document.current_version_id == Chunk.version_id,
                DocumentVersion.version_status == "active",
            )
            .order_by(Chunk.id)
        )
