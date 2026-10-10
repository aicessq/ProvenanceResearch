"""EmbeddingIdentity 与 collection 绑定契约（P3a 验收）。

必须记录 provider/model/dimension/preprocess_version；
禁止不同 identity 使用同 collection；向量维度必须与 identity 一致。
"""

from __future__ import annotations

import asyncio

import pytest

from providers.embedding.base import (
    CollectionBinding,
    EmbeddingIdentity,
    EmbeddingResult,
)
from providers.embedding.fake import FakeEmbeddingProvider

IDENTITY = EmbeddingIdentity(
    provider="fake",
    model="fake-embedding",
    dimension=8,
    preprocess_version="v0",
)


def test_identity_key_covers_all_four_fields() -> None:
    assert IDENTITY.key() == "fake:fake-embedding:8:v0"
    other = EmbeddingIdentity("fake", "fake-embedding", 8, "v1")
    assert other.key() != IDENTITY.key()
    dim_changed = EmbeddingIdentity("fake", "fake-embedding", 16, "v0")
    assert dim_changed.key() != IDENTITY.key()


def test_identity_rejects_incomplete_or_invalid_fields() -> None:
    with pytest.raises(ValueError):
        EmbeddingIdentity("", "m", 8, "v0").validate()
    with pytest.raises(ValueError):
        EmbeddingIdentity("p", "m", 0, "v0").validate()
    with pytest.raises(ValueError):
        EmbeddingIdentity("p", "m", 8, "").validate()


def test_result_rejects_vector_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        EmbeddingResult(vectors=[[0.1, 0.2]], identity=IDENTITY)


def test_collection_binding_forbids_rebinding_different_identity() -> None:
    binding = CollectionBinding()
    binding.register("kb_v1", IDENTITY)
    binding.register("kb_v1", IDENTITY)  # 同 identity 幂等
    other = EmbeddingIdentity("fake", "fake-embedding", 8, "v1")
    with pytest.raises(ValueError):
        binding.register("kb_v1", other)


def test_collection_binding_rejects_unregistered_or_mismatched_access() -> None:
    binding = CollectionBinding()
    with pytest.raises(ValueError):
        binding.verify("kb_v1", IDENTITY)
    binding.register("kb_v1", IDENTITY)
    other = EmbeddingIdentity("fake", "fake-embedding", 16, "v0")
    with pytest.raises(ValueError):
        binding.verify("kb_v1", other)
    binding.verify("kb_v1", IDENTITY)  # 一致则放行


def test_different_identity_maps_to_different_collection_namespace() -> None:
    """换模型/维度/预处理版本必须换 collection——由 identity.key() 进入命名。"""
    a = EmbeddingIdentity("fake", "model-a", 8, "v0")
    b = EmbeddingIdentity("fake", "model-a", 8, "v1")
    c = EmbeddingIdentity("fake", "model-b", 8, "v0")
    assert len({a.key(), b.key(), c.key()}) == 3


def test_fake_embedding_deterministic_and_dimension_matched() -> None:
    provider = FakeEmbeddingProvider(IDENTITY)
    first = asyncio.run(provider.embed(["同一文本"]))
    second = asyncio.run(provider.embed(["同一文本"]))
    assert first.vectors == second.vectors
    assert all(len(v) == IDENTITY.dimension for v in first.vectors)
    assert first.identity == IDENTITY
