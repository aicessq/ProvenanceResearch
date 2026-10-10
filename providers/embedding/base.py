"""Embedding Identity 与统一接口（P3a）。

EmbeddingIdentity = provider + model + dimension + preprocess_version 四元组。
查询与入库必须同一 identity；**禁止不同 identity 使用同 collection**——
换模型/维度/预处理版本必须走新 collection + 索引迁移（2026-09-18 决策）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model: str
    dimension: int
    preprocess_version: str

    def validate(self) -> None:
        """字段完整性检查；缺失/非法即拒绝（不猜默认值）。"""
        if not self.provider or not self.model or not self.preprocess_version:
            raise ValueError(f"EmbeddingIdentity 字段不完整: {self!r}")
        if self.dimension <= 0:
            raise ValueError(f"EmbeddingIdentity.dimension 必须为正整数: {self.dimension}")

    def key(self) -> str:
        """identity 指纹，用于 collection 命名与一致性校验。"""
        self.validate()
        return f"{self.provider}:{self.model}:{self.dimension}:{self.preprocess_version}"


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    identity: EmbeddingIdentity
    prompt_tokens: int = 0

    def __post_init__(self) -> None:
        self.identity.validate()
        for vec in self.vectors:
            if len(vec) != self.identity.dimension:
                raise ValueError(
                    f"向量维度 {len(vec)} 与 identity.dimension {self.identity.dimension} 不符"
                )


class EmbeddingProvider(Protocol):
    provider_name: str

    async def embed(
        self,
        texts: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
    ) -> EmbeddingResult: ...


class CollectionBinding:
    """collection → identity 的登记表：一个 collection 只属于一个 identity。"""

    def __init__(self) -> None:
        self._bindings: dict[str, str] = {}

    def register(self, collection: str, identity: EmbeddingIdentity) -> None:
        key = identity.key()
        existing = self._bindings.get(collection)
        if existing is not None and existing != key:
            raise ValueError(
                f"collection {collection!r} 已绑定 identity {existing!r}，禁止改绑 {key!r}"
            )
        self._bindings[collection] = key

    def verify(self, collection: str, identity: EmbeddingIdentity) -> None:
        key = identity.key()
        existing = self._bindings.get(collection)
        if existing is None:
            raise ValueError(f"collection {collection!r} 未登记 identity，禁止查询/写入")
        if existing != key:
            raise ValueError(
                f"collection {collection!r} 归属 {existing!r}，拒绝以 {key!r} 访问"
            )

    def identity_key(self, collection: str) -> str | None:
        return self._bindings.get(collection)
