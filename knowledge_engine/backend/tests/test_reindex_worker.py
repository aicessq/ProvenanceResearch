from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.embedding_service import EmbeddingServiceError
from app.services.reindex_service import ReindexService, ReindexServiceError


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def partitions(self, size):
        for start in range(0, len(self._rows), size):
            yield self._rows[start : start + size]


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return FakeScalarResult(self.rows)


class FakeClient:
    def __init__(
        self,
        *,
        exists=False,
        count=0,
        reported_count=None,
        payload_identity=None,
        vector_size=3,
        distance="Cosine",
    ):
        self.exists = exists
        self.point_count = count
        self.reported_count = reported_count
        self.payload_identity = payload_identity
        self.vector_size = vector_size
        self.distance = distance
        self.created = []
        self.upserts = []
        self.upsert_batches = []

    def collection_exists(self, collection_name):
        return self.exists

    def get_collection(self, collection_name):
        vectors = SimpleNamespace(size=self.vector_size, distance=self.distance)
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)))

    def count(self, *, collection_name, exact):
        count = self.reported_count if self.reported_count is not None else self.point_count
        return SimpleNamespace(count=count)

    def create_collection(self, *, collection_name, vectors_config):
        self.created.append(collection_name)
        self.exists = True

    def upsert(self, *, collection_name, points, wait):
        self.upsert_batches.append(list(points))
        self.upserts.extend(points)
        self.point_count += len(points)

    def scroll(self, *, collection_name, limit, offset, with_payload, with_vectors):
        points = []
        for point in self.upserts:
            payload = dict(point.payload)
            if self.payload_identity is not None:
                payload["embedding_identity"] = self.payload_identity
            points.append(SimpleNamespace(payload=payload))
        return points, None


class FakeEmbedding:
    vector_size = 3
    identity = "model=safe-model;dim=3;normalize=true;preprocess=v1"
    model_name = "safe-model"

    def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def make_chunk(*, active=True, chunk_type="child"):
    version_id = uuid4()
    return SimpleNamespace(
        id=uuid4(), document_id=uuid4(), version_id=version_id,
        parent_chunk_id=None, chunk_type=chunk_type, is_active=active,
        normalized_text="安全文本", text="安全文本", chunk_hash="hash",
        doc_type="standard", doc_title="规范", chapter=None, section=None,
        article_no=None, page_start=1, page_end=1, security_domain=["security"],
    ), SimpleNamespace(id=version_id, version_status="active")


def make_service(*, rows=(), current_collection="current", client=None, embedding=None):
    return ReindexService(
        db=FakeDb(list(rows)),
        embedding_service=embedding or FakeEmbedding(),
        qdrant_client=client or FakeClient(),
        current_collection=current_collection,
        distance_metric="COSINE",
    )


def test_reindex_rejects_current_collection_without_touching_qdrant():
    client = FakeClient()
    service = make_service(client=client)

    with pytest.raises(ReindexServiceError, match="必须不同"):
        service.rebuild("current")

    assert client.created == []
    assert client.upserts == []


def test_reindex_rejects_nonempty_target_collection_without_writing():
    client = FakeClient(exists=True, count=1)
    service = make_service(client=client)

    with pytest.raises(ReindexServiceError, match="非空"):
        service.rebuild("new-safe-index")

    assert client.upserts == []


def test_reindex_rejects_empty_target_with_incompatible_vector_config():
    client = FakeClient(exists=True, vector_size=4)
    service = make_service(client=client)

    with pytest.raises(ReindexServiceError, match="配置不一致"):
        service.rebuild("new-safe-index")

    assert client.upserts == []


def test_reindex_empty_source_creates_and_verifies_empty_collection():
    client = FakeClient()
    service = make_service(client=client)

    result = service.rebuild("new-safe-index")

    assert client.created == ["new-safe-index"]
    assert client.upserts == []
    assert result["selected_count"] == 0
    assert result["verified_point_count"] == 0
    assert result["identity_verified"] is True


def test_reindex_only_writes_active_current_version_child_chunks():
    chunk, version = make_chunk()
    client = FakeClient()
    service = make_service(rows=[(chunk, version)], client=client)

    result = service.rebuild("new-safe-index")

    sql = str(service.db.statement)
    assert "chunks.is_active" in sql
    assert "chunks.chunk_type" in sql
    assert "documents.current_version_id = chunks.version_id" in sql
    assert len(client.upserts) == 1
    payload = client.upserts[0].payload
    assert payload["embedding_identity"] == FakeEmbedding.identity
    assert result == {
        "processed_count": 1,
        "selected_count": 1,
        "embedded_count": 1,
        "upserted_count": 1,
        "verified_point_count": 1,
        "identity_verified": True,
        "batch_count": 1,
        "target_collection": "new-safe-index",
        "embedding_identity": FakeEmbedding.identity,
        "embedding_model": "safe-model",
        "vector_size": 3,
    }


def test_reindex_batches_rows_and_returns_auditable_counts():
    rows = [make_chunk() for _ in range(5)]
    client = FakeClient()
    service = make_service(rows=rows, client=client)

    result = service.rebuild("new-safe-index", batch_size=2)

    assert [len(batch) for batch in client.upsert_batches] == [2, 2, 1]
    assert result["selected_count"] == 5
    assert result["embedded_count"] == 5
    assert result["upserted_count"] == 5
    assert result["verified_point_count"] == 5
    assert result["identity_verified"] is True
    assert result["batch_count"] == 3


def test_reindex_rejects_when_target_point_count_does_not_match_selection():
    chunk, version = make_chunk()
    client = FakeClient(reported_count=0)
    service = make_service(rows=[(chunk, version)], client=client)

    with pytest.raises(ReindexServiceError, match="点数校验失败"):
        service.rebuild("new-safe-index")


def test_reindex_rejects_when_written_payload_identity_is_inconsistent():
    chunk, version = make_chunk()
    client = FakeClient(payload_identity="different-model")
    service = make_service(rows=[(chunk, version)], client=client)

    with pytest.raises(ReindexServiceError, match="身份校验失败"):
        service.rebuild("new-safe-index")


def test_celery_app_discovers_reindex_task():
    from app.workers.celery_app import celery_app
    from app.workers.reindex_worker import reindex_collection_task

    assert "app.workers.reindex_worker" in celery_app.conf.include
    assert reindex_collection_task.name in celery_app.tasks


def test_reindex_worker_uses_public_service_seam(monkeypatch):
    from app.workers.reindex_worker import reindex_collection_task

    session = SimpleNamespace(close=lambda: None)
    expected = {"target_collection": "new-safe-index", "upserted_count": 7}
    service = SimpleNamespace(rebuild=lambda target_collection, batch_size: expected)
    monkeypatch.setattr("app.workers.reindex_worker.SessionLocal", lambda: session)
    monkeypatch.setattr(
        "app.workers.reindex_worker.ReindexService.from_db",
        lambda db, target_collection: service,
    )

    result = reindex_collection_task.run(
        target_collection="new-safe-index", batch_size=64
    )

    assert result == expected


def test_reindex_propagates_real_model_loading_failure(monkeypatch):
    def fail_strict_load(*, allow_fallback=False):
        assert allow_fallback is False
        raise EmbeddingServiceError("真实模型加载失败")

    monkeypatch.setattr(
        "app.services.reindex_service.get_embedding_service", fail_strict_load
    )

    with pytest.raises(EmbeddingServiceError, match="真实模型加载失败"):
        ReindexService.from_db(FakeDb([]), target_collection="new-safe-index")
