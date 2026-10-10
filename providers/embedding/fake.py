"""Fake Embedding Provider（测试专用，确定性向量）。

同文本同向量（hash 派生），dimension 严格遵守 identity；
用于索引身份/迁移的契约测试，不是生产 fallback。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping, Sequence

from providers.embedding.base import EmbeddingIdentity, EmbeddingResult


class FakeEmbeddingProvider:
    provider_name = "fake"

    def __init__(self, identity: EmbeddingIdentity | None = None) -> None:
        self._identity = identity or EmbeddingIdentity(
            provider="fake",
            model="fake-embedding",
            dimension=8,
            preprocess_version="v0",
        )
        self._identity.validate()

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    async def embed(
        self,
        texts: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
    ) -> EmbeddingResult:
        vectors = [self._vector(t) for t in texts]
        return EmbeddingResult(vectors=vectors, identity=self._identity)

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(f"{self._identity.key()}|{text}".encode()).digest()
        dim = self._identity.dimension
        raw = [digest[i % len(digest)] / 255.0 for i in range(dim)]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]
