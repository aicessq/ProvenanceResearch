"""云模型 Provider 统一适配层（P3a）。

所有 AI 能力（llm/embedding/reranker/ocr/vision）经此层访问云端；
生产路径不下载/加载本地权重（AGENTS.md），缺配置显式失败。
mock/fake 实现仅限测试。
"""

from providers.errors import (
    RETRYABLE_CODES,
    ProviderError,
    ProviderErrorCode,
    classify_http_status,
)
from providers.embedding.base import (
    CollectionBinding,
    EmbeddingIdentity,
    EmbeddingProvider,
    EmbeddingResult,
)
from providers.llm.base import LLMMessage, LLMProvider, LLMProviderConfig, LLMResult

__all__ = [
    "RETRYABLE_CODES",
    "CollectionBinding",
    "EmbeddingIdentity",
    "EmbeddingProvider",
    "EmbeddingResult",
    "LLMMessage",
    "LLMProvider",
    "LLMProviderConfig",
    "LLMResult",
    "ProviderError",
    "ProviderErrorCode",
    "classify_http_status",
]
