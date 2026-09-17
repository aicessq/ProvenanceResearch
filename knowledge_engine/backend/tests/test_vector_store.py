"""Phase 5 vector store 测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.vector_store import QdrantVectorStore, VectorPoint, VectorStoreError


class FakeQdrantClient:
    """最小可用的 Qdrant 测试替身。"""

    def __init__(self) -> None:
        self.exists = False
        self.created = []
        self.upserted = []
        self.points_by_id: dict[str, object] = {}

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(self, *, collection_name: str, vectors_config: object) -> None:
        self.created.append((collection_name, vectors_config))
        self.exists = True

    def upsert(self, *, collection_name: str, points: list[object], wait: bool) -> object:
        self.upserted.append((collection_name, points, wait))
        for point in points:
            self.points_by_id[str(point.id)] = point
        return {"status": "ok"}

    def retrieve(self, *, collection_name: str, ids: list[str], with_payload: bool, with_vectors: bool) -> list[object]:
        del collection_name, with_payload, with_vectors
        return [self.points_by_id[item_id] for item_id in ids if item_id in self.points_by_id]

    def query_points(self, **kwargs) -> object:
        del kwargs
        return SimpleNamespace(points=[])

    def scroll(self, **kwargs) -> object:
        del kwargs
        return [], None


def test_vector_store_creates_collection_and_upserts_child_chunk() -> None:
    client = FakeQdrantClient()
    store = QdrantVectorStore(
        client,
        collection_name="cybersec_chunks",
        vector_size=4,
        distance_metric="Cosine",
    )

    store.ensure_collection()
    count = store.upsert_chunks(
        [
            VectorPoint(
                chunk_id="chunk-1",
                vector=[0.1, 0.2, 0.3, 0.4],
                payload={
                    "chunk_id": "chunk-1",
                    "chunk_type": "child",
                    "doc_title": "网络安全法",
                    "is_active": True,
                },
            )
        ]
    )

    assert client.created
    assert count == 1
    assert client.upserted
    written_point = client.upserted[0][1][0]
    assert written_point.payload["chunk_id"] == "chunk-1"
    assert written_point.payload["chunk_type"] == "child"
    assert written_point.payload["is_active"] is True


def test_vector_store_rejects_embedding_identity_mismatch() -> None:
    client = FakeQdrantClient()
    client.query_points = lambda **kwargs: SimpleNamespace(points=[SimpleNamespace(
        id="chunk-id", score=0.9,
        payload={
            "chunk_id": "chunk-id", "chunk_type": "child", "is_active": True,
            "is_current_version": True, "embedding_identity": "old-model",
        },
    )])
    store = QdrantVectorStore(
        client, collection_name="chunks", vector_size=3, distance_metric="Cosine",
        expected_embedding_identity="new-model",
    )

    with pytest.raises(VectorStoreError, match="embedding 模型身份不一致"):
        store.search([0.1, 0.2, 0.3])


def test_vector_store_rejects_embedding_identity_mismatch_in_any_returned_point() -> None:
    client = FakeQdrantClient()
    client.query_points = lambda **kwargs: SimpleNamespace(points=[
        SimpleNamespace(
            id="chunk-current", score=0.9,
            payload={
                "chunk_id": "chunk-current", "chunk_type": "child", "is_active": True,
                "is_current_version": True, "embedding_identity": "new-model",
            },
        ),
        SimpleNamespace(
            id="chunk-old", score=0.8,
            payload={
                "chunk_id": "chunk-old", "chunk_type": "child", "is_active": True,
                "is_current_version": True, "embedding_identity": "old-model",
            },
        ),
    ])
    store = QdrantVectorStore(
        client, collection_name="chunks", vector_size=3, distance_metric="Cosine",
        expected_embedding_identity="new-model",
    )

    with pytest.raises(VectorStoreError, match="embedding 模型身份不一致"):
        store.search([0.1, 0.2, 0.3])


def test_vector_store_allows_empty_results_with_expected_identity() -> None:
    client = FakeQdrantClient()
    store = QdrantVectorStore(
        client, collection_name="chunks", vector_size=3, distance_metric="Cosine",
        expected_embedding_identity="new-model",
    )

    assert store.search([0.1, 0.2, 0.3]) == []


def test_vector_store_rejects_empty_collection_during_identity_validation() -> None:
    client = FakeQdrantClient()
    store = QdrantVectorStore(
        client, collection_name="chunks", vector_size=3, distance_metric="Cosine",
        expected_embedding_identity="new-model",
    )

    with pytest.raises(VectorStoreError, match="向量索引为空"):
        store.validate_embedding_identity()


def test_vector_store_validates_all_identity_pages() -> None:
    client = FakeQdrantClient()
    pages = {
        None: ([SimpleNamespace(payload={"embedding_identity": "new-model"})], "next"),
        "next": ([SimpleNamespace(payload={"embedding_identity": "old-model"})], None),
    }
    client.scroll = lambda **kwargs: pages[kwargs["offset"]]
    store = QdrantVectorStore(
        client, collection_name="chunks", vector_size=3, distance_metric="Cosine",
        expected_embedding_identity="new-model",
    )

    with pytest.raises(VectorStoreError, match="embedding 模型身份不一致"):
        store.validate_embedding_identity()


def test_vector_store_can_retrieve_by_chunk_id() -> None:
    client = FakeQdrantClient()
    store = QdrantVectorStore(
        client,
        collection_name="cybersec_chunks",
        vector_size=4,
        distance_metric="Cosine",
    )
    point = SimpleNamespace(
        id="chunk-2",
        payload={"chunk_id": "chunk-2", "doc_title": "等保标准", "is_active": True},
        vector=[0.9, 0.1, 0.2, 0.3],
    )
    client.points_by_id["chunk-2"] = point

    results = store.get_chunks_by_ids(["chunk-2"])

    assert len(results) == 1
    assert results[0].payload["chunk_id"] == "chunk-2"
