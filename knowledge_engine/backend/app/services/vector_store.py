"""Qdrant 向量存储封装。

Phase 5 负责把 child chunk 的向量与 payload 写入 Qdrant。
Phase 6 在此基础上继续补齐向量检索能力。
本模块只提供“索引写入 + 检索”能力，不提前实现最终问答接口。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.config import get_settings
from app.dependencies import get_qdrant_client
from app.services.fusion import RetrievalHit
from app.services.metadata_filter import MetadataFilter, matches_payload_filters

try:  # pragma: no cover - 依赖安装与否取决于运行环境
    from qdrant_client.http.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchAny,
        MatchValue,
        PointStruct,
        Range,
        VectorParams,
    )
except ImportError:  # pragma: no cover
    Distance = None  # type: ignore[assignment]
    FieldCondition = None  # type: ignore[assignment]
    Filter = None  # type: ignore[assignment]
    MatchAny = None  # type: ignore[assignment]
    MatchValue = None  # type: ignore[assignment]
    PointStruct = None  # type: ignore[assignment]
    Range = None  # type: ignore[assignment]
    VectorParams = None  # type: ignore[assignment]


class VectorStoreError(RuntimeError):
    """Vector store 操作异常。"""


class QdrantClientProtocol(Protocol):
    """统一约束当前模块会用到的 Qdrant 客户端能力。"""

    def collection_exists(self, collection_name: str) -> bool: ...

    def get_collection(self, collection_name: str) -> object: ...

    def count(self, *, collection_name: str, exact: bool) -> object: ...

    def create_collection(self, *, collection_name: str, vectors_config: object) -> None: ...

    def upsert(self, *, collection_name: str, points: list[object], wait: bool) -> object: ...

    def retrieve(self, *, collection_name: str, ids: list[str], with_payload: bool, with_vectors: bool) -> list[object]: ...

    def query_points(self, *, collection_name: str, query: list[float], limit: int, query_filter: object | None, with_payload: bool) -> object: ...

    def scroll(
        self, *, collection_name: str, limit: int, offset: object | None,
        with_payload: bool, with_vectors: bool,
    ) -> object: ...

    def set_payload(self, *, collection_name: str, payload: dict[str, Any], points: list[str], wait: bool) -> object: ...


@dataclass(slots=True)
class VectorPoint:
    """进入 Qdrant 前的统一 point 表达。"""

    chunk_id: str
    vector: list[float]
    payload: dict[str, Any]


class QdrantVectorStore:
    """Qdrant 写入与检索封装。"""

    def __init__(
        self,
        client: QdrantClientProtocol,
        *,
        collection_name: str,
        vector_size: int,
        distance_metric: str,
        expected_embedding_identity: str | None = None,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.distance_metric = distance_metric
        self.expected_embedding_identity = expected_embedding_identity

    @classmethod
    def from_settings(cls, *, client: QdrantClientProtocol | None = None) -> "QdrantVectorStore":
        """按全局配置构造 vector store。"""
        settings = get_settings()
        resolved_client = client or get_qdrant_client()
        if resolved_client is None:
            raise VectorStoreError("Qdrant 客户端不可用，无法初始化 vector store")
        return cls(
            resolved_client,
            collection_name=settings.qdrant_collection,
            vector_size=settings.embedding_vector_size,
            distance_metric=settings.qdrant_distance_metric,
        )

    def ensure_collection(self) -> None:
        """确保 Qdrant collection 已按当前配置创建。"""
        if Distance is None or VectorParams is None:
            raise VectorStoreError("qdrant-client 未安装，无法创建 collection")
        if self.client.collection_exists(self.collection_name):
            self.validate_collection_config()
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.vector_size,
                distance=getattr(Distance, self.distance_metric, getattr(Distance, self.distance_metric.upper())),
            ),
        )

    def validate_collection_config(self) -> None:
        """拒绝复用维度或距离度量与当前 embedding 配置不一致的 collection。"""
        info = self.client.get_collection(self.collection_name)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            raise VectorStoreError("当前仅支持未命名的单向量 collection")
        actual_size = int(vectors.size)
        actual_distance = str(vectors.distance).lower()
        if actual_size != self.vector_size or actual_distance != self.distance_metric.lower():
            raise VectorStoreError(
                "collection 向量配置不一致："
                f"期望 dim={self.vector_size}, distance={self.distance_metric}；"
                f"实际 dim={actual_size}, distance={vectors.distance}"
            )

    def upsert_chunks(self, points: Sequence[VectorPoint]) -> int:
        """把 child chunk 向量写入 Qdrant。"""
        if PointStruct is None:
            raise VectorStoreError("qdrant-client 未安装，无法写入向量")
        if not points:
            return 0

        qdrant_points = [
            PointStruct(
                id=point.chunk_id,
                vector=point.vector,
                payload=dict(point.payload),
            )
            for point in points
        ]
        self.client.upsert(
            collection_name=self.collection_name,
            points=qdrant_points,
            wait=True,
        )
        return len(qdrant_points)

    def get_chunks_by_ids(self, chunk_ids: Sequence[str | UUID]) -> list[Any]:
        """按 chunk_id 回查已写入 point。"""
        normalized_ids = [str(chunk_id) for chunk_id in chunk_ids]
        if not normalized_ids:
            return []
        return self.client.retrieve(
            collection_name=self.collection_name,
            ids=normalized_ids,
            with_payload=True,
            with_vectors=True,
        )

    def validate_embedding_identity(self, *, allow_empty: bool = False) -> None:
        """扫描 collection payload，拒绝空身份、旧索引或混合向量空间。"""
        if not self.expected_embedding_identity:
            return
        offset: object | None = None
        seen_identity = False
        while True:
            response = self.client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if isinstance(response, tuple):
                points, next_offset = response
            else:
                points = getattr(response, "points", [])
                next_offset = getattr(response, "next_page_offset", None)
            for point in points:
                payload = dict(getattr(point, "payload", {}) or {})
                indexed_identity = payload.get("embedding_identity")
                if indexed_identity != self.expected_embedding_identity:
                    raise VectorStoreError(
                        "embedding 模型身份不一致，必须使用新 collection 安全重建索引"
                    )
                seen_identity = True
            if next_offset is None:
                break
            offset = next_offset
        if not seen_identity and not allow_empty:
            raise VectorStoreError("向量索引为空，无法验证 embedding 模型身份")

    def search(self, query_vector: list[float], *, top_k: int = 30, filters: MetadataFilter | None = None) -> list[RetrievalHit]:
        """按 query 向量检索 child chunk。"""
        effective_filters = filters or MetadataFilter()
        query_filter = self._build_qdrant_filter(effective_filters)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        points = getattr(response, "points", response)
        results: list[RetrievalHit] = []
        for point in points:
            payload = dict(getattr(point, "payload", {}) or {})
            indexed_identity = payload.get("embedding_identity")
            if (
                self.expected_embedding_identity
                and indexed_identity != self.expected_embedding_identity
            ):
                raise VectorStoreError(
                    "embedding 模型身份不一致，必须使用新 collection 安全重建索引"
                )
            if not matches_payload_filters(payload, effective_filters):
                continue
            results.append(
                RetrievalHit(
                    chunk_id=str(payload.get("chunk_id") or getattr(point, "id")),
                    score=float(getattr(point, "score", 0.0)),
                    source="vector",
                    chunk_text=str(payload.get("chunk_text") or payload.get("text") or ""),
                    document_id=str(payload.get("document_id") or ""),
                    version_id=str(payload.get("version_id") or ""),
                    doc_title=str(payload.get("doc_title") or ""),
                    doc_type=str(payload.get("doc_type") or ""),
                    chapter=payload.get("chapter"),
                    section=payload.get("section"),
                    article_no=payload.get("article_no"),
                    page_start=payload.get("page_start"),
                    page_end=payload.get("page_end"),
                    parent_chunk_id=payload.get("parent_chunk_id"),
                    version_status=payload.get("version_status"),
                    is_active=bool(payload.get("is_active", True)),
                    security_domain=list(payload.get("security_domain") or []),
                    metadata=payload,
                )
            )
        return results[:top_k]

    def set_chunks_active(self, chunk_ids: Sequence[str | UUID], *, is_active: bool) -> int:
        """批量更新 Qdrant payload 中的 is_active 可见性。"""
        normalized_ids = [str(chunk_id) for chunk_id in chunk_ids]
        if not normalized_ids:
            return 0
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"is_active": is_active},
            points=normalized_ids,
            wait=True,
        )
        return len(normalized_ids)

    def set_chunks_current_version(self, chunk_ids: Sequence[str | UUID], *, is_current_version: bool) -> int:
        """批量更新 Qdrant payload 中的 current version 可见性。"""
        normalized_ids = [str(chunk_id) for chunk_id in chunk_ids]
        if not normalized_ids:
            return 0
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"is_current_version": is_current_version},
            points=normalized_ids,
            wait=True,
        )
        return len(normalized_ids)

    def _build_qdrant_filter(self, filters: MetadataFilter) -> object | None:
        """把显式 metadata filter 映射到 Qdrant query_filter。"""
        if Filter is None or FieldCondition is None:
            return None

        conditions = [FieldCondition(key="chunk_type", match=MatchValue(value="child"))]
        if filters.is_active is not None:
            conditions.append(FieldCondition(key="is_active", match=MatchValue(value=filters.is_active)))
        if filters.current_version_only:
            conditions.append(FieldCondition(key="is_current_version", match=MatchValue(value=True)))
        if filters.doc_type:
            conditions.append(FieldCondition(key="doc_type", match=MatchAny(any=filters.doc_type)))
        if filters.doc_title:
            conditions.append(FieldCondition(key="doc_title", match=MatchAny(any=filters.doc_title)))
        if filters.version_status:
            conditions.append(FieldCondition(key="version_status", match=MatchAny(any=filters.version_status)))
        if filters.security_domain:
            conditions.append(FieldCondition(key="security_domain", match=MatchAny(any=filters.security_domain)))
        if filters.chapter:
            conditions.append(FieldCondition(key="chapter", match=MatchAny(any=filters.chapter)))
        if filters.section:
            conditions.append(FieldCondition(key="section", match=MatchAny(any=filters.section)))
        if filters.article_no:
            conditions.append(FieldCondition(key="article_no", match=MatchAny(any=filters.article_no)))
        if filters.page_start is not None:
            conditions.append(FieldCondition(key="page_start", range=Range(gte=filters.page_start)))
        if filters.page_end is not None:
            conditions.append(FieldCondition(key="page_end", range=Range(lte=filters.page_end)))
        return Filter(must=conditions)
