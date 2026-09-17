"""Phase 5 embedding 服务测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.embedding_service import (
    DeterministicEmbeddingModel,
    EmbeddingService,
    EmbeddingServiceError,
)


def test_embedding_service_loads_from_local_directory_with_fallback(tmp_path: Path) -> None:
    model_dir = tmp_path / "embedding-model"
    model_dir.mkdir()

    service = EmbeddingService.from_local_model(
        model_path=model_dir,
        vector_size=8,
        batch_size=2,
        allow_fallback=True,
    )

    assert isinstance(service.model, DeterministicEmbeddingModel)
    assert service.vector_size == 8


def test_embedding_service_embeds_single_text() -> None:
    service = EmbeddingService(
        DeterministicEmbeddingModel(vector_size=8),
        vector_size=8,
        batch_size=2,
    )

    vector = service.embed_text("网络安全法第一条")

    assert len(vector) == 8
    assert any(value != 0 for value in vector)


def test_embedding_service_embeds_texts_in_batch() -> None:
    service = EmbeddingService(
        DeterministicEmbeddingModel(vector_size=8),
        vector_size=8,
        batch_size=2,
    )

    vectors = service.embed_texts(["chunk one", "chunk two"])

    assert len(vectors) == 2
    assert all(len(vector) == 8 for vector in vectors)
    assert vectors[0] != vectors[1]


def test_embedding_service_exposes_stable_identity() -> None:
    first = EmbeddingService(
        DeterministicEmbeddingModel(vector_size=8), vector_size=8, batch_size=2,
        model_name="test-model",
    )
    second = EmbeddingService(
        DeterministicEmbeddingModel(vector_size=8), vector_size=8, batch_size=4,
        model_name="test-model",
    )

    assert first.identity == second.identity
    assert "dim=8" in first.identity
    assert "normalize=true" in first.identity


def test_embedding_service_raises_when_model_path_missing_without_fallback(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing-model"

    with pytest.raises(EmbeddingServiceError):
        EmbeddingService.from_local_model(
            model_path=missing_dir,
            vector_size=8,
            batch_size=2,
            allow_fallback=False,
        )
