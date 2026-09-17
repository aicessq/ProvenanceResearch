"""本地 Embedding 服务（Qwen Embedding 进程内加载）。

Phase 5 开始实现真正的索引输入能力：
- 从项目本地模型目录加载 embedding 模型
- 提供单条 / 批量向量化接口
- 统一返回固定维度向量
- 为 worker / index_service 屏蔽底层模型细节

说明：
- 规格要求优先加载真实本地模型；
- 为了让仓库在尚未放入模型权重时也能保持可导入、可测试，
  本模块提供“显式回退编码器”机制，仅在调用方明确允许时启用；
- 默认不自动回退，避免悄悄偏离“本地真实模型优先”的阶段要求。
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings

try:  # pragma: no cover - 是否安装依赖取决于运行环境
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None  # type: ignore[assignment]


class EmbeddingModelProtocol(Protocol):
    """统一约束底层 embedding 模型的最小能力。"""

    def encode(
        self,
        sentences: str | list[str],
        *,
        batch_size: int,
        convert_to_numpy: bool,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> object: ...


class EmbeddingServiceError(RuntimeError):
    """Embedding 服务异常。"""


class DeterministicEmbeddingModel:
    """测试 / 无模型权重场景下的确定性回退编码器。

    该编码器不试图模拟真实语义，只保证：
    - 同一输入稳定输出同一向量；
    - 输出维度固定；
    - 结果可用于单元测试编排与 payload 流程验证。
    """

    def __init__(self, vector_size: int) -> None:
        self.vector_size = vector_size

    def encode(
        self,
        sentences: str | list[str],
        *,
        batch_size: int,
        convert_to_numpy: bool,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> list[list[float]]:
        del batch_size, convert_to_numpy, show_progress_bar
        texts = [sentences] if isinstance(sentences, str) else list(sentences)
        return [self._encode_text(text, normalize_embeddings=normalize_embeddings) for text in texts]

    def _encode_text(self, text: str, *, normalize_embeddings: bool) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        seed = digest
        while len(values) < self.vector_size:
            for index in range(0, len(seed), 4):
                chunk = seed[index : index + 4]
                if len(chunk) < 4:
                    continue
                raw_value = int.from_bytes(chunk, byteorder="big", signed=False)
                values.append((raw_value / 2**32) * 2 - 1)
                if len(values) >= self.vector_size:
                    break
            seed = hashlib.sha256(seed).digest()
        if normalize_embeddings:
            norm = sum(value * value for value in values) ** 0.5
            if norm > 0:
                return [value / norm for value in values]
        return values


class EmbeddingService:
    """本地 embedding 服务封装。"""

    def __init__(
        self,
        model: EmbeddingModelProtocol,
        *,
        vector_size: int,
        batch_size: int,
        model_name: str | None = None,
    ) -> None:
        self.model = model
        self.vector_size = vector_size
        self.batch_size = batch_size
        self.model_name = model_name or model.__class__.__name__
        self.identity = (
            f"model={self.model_name};dim={vector_size};normalize=true;preprocess=v1"
        )

    @classmethod
    def from_local_model(
        cls,
        *,
        model_path: str | Path | None = None,
        vector_size: int | None = None,
        batch_size: int | None = None,
        allow_fallback: bool = False,
    ) -> "EmbeddingService":
        """从本地目录加载 embedding 模型。

        allow_fallback=False 时：
        - 模型目录不存在 / 依赖缺失 / 加载失败都会抛出明确异常；
        allow_fallback=True 时：
        - 回退到 DeterministicEmbeddingModel，便于单元测试。
        """
        settings = get_settings()
        resolved_path = Path(model_path or settings.embedding_model_path)
        resolved_vector_size = vector_size or settings.embedding_vector_size
        resolved_batch_size = batch_size or settings.embedding_batch_size

        if SentenceTransformer is None:
            if allow_fallback:
                return cls(
                    DeterministicEmbeddingModel(resolved_vector_size),
                    vector_size=resolved_vector_size,
                    batch_size=resolved_batch_size,
                )
            raise EmbeddingServiceError(
                "sentence-transformers 未安装，无法加载本地 embedding 模型"
            )

        if not resolved_path.exists() or not resolved_path.is_dir():
            if allow_fallback:
                return cls(
                    DeterministicEmbeddingModel(resolved_vector_size),
                    vector_size=resolved_vector_size,
                    batch_size=resolved_batch_size,
                )
            raise EmbeddingServiceError(f"embedding 模型目录不存在: {resolved_path}")

        try:
            model = SentenceTransformer(str(resolved_path), trust_remote_code=True)
        except Exception as exc:  # noqa: BLE001 - 需要把底层加载异常转成业务异常
            if allow_fallback:
                return cls(
                    DeterministicEmbeddingModel(resolved_vector_size),
                    vector_size=resolved_vector_size,
                    batch_size=resolved_batch_size,
                )
            raise EmbeddingServiceError(f"embedding 模型加载失败: {resolved_path}") from exc

        return cls(
            model,
            vector_size=resolved_vector_size,
            batch_size=resolved_batch_size,
            model_name=resolved_path.name,
        )

    def embed_text(self, text: str) -> list[float]:
        """生成单条文本向量。"""
        if not text.strip():
            raise EmbeddingServiceError("embedding 输入文本不能为空")
        vectors = self.embed_texts([text])
        return vectors[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量。"""
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise EmbeddingServiceError("embedding 输入列表中存在空文本")

        encoded = self.model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=False,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = [list(vector) for vector in encoded]  # type: ignore[arg-type]
        self._validate_vector_dimensions(vectors)
        return vectors

    def _validate_vector_dimensions(self, vectors: list[list[float]]) -> None:
        """校验模型输出维度，防止配置与实际模型不一致。"""
        for vector in vectors:
            if len(vector) != self.vector_size:
                raise EmbeddingServiceError(
                    f"embedding 维度不匹配，期望 {self.vector_size}，实际 {len(vector)}"
                )


@lru_cache
def get_embedding_service(*, allow_fallback: bool = False) -> EmbeddingService:
    """返回 embedding 服务单例。"""
    return EmbeddingService.from_local_model(allow_fallback=allow_fallback)
