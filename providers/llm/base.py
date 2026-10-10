"""LLM Provider 统一接口（P3a）。

所有生成模型能力走同一协议：`async def generate(messages, metadata)`。
新增 provider 不修改调用方；错误统一为 providers.errors.ProviderError。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(Protocol):
    """生成模型统一协议。实现方必须：缺配置显式失败、失败不伪造结果。"""

    provider_name: str

    async def generate(
        self,
        messages: Sequence[LLMMessage],
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResult: ...


@dataclass(frozen=True)
class LLMProviderConfig:
    """LLM 连接配置（对应 .env.example 的 LLM_* 字段）。"""

    provider: str
    model: str
    api_key: str
    base_url: str
    model_version: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    extra: dict[str, Any] = field(default_factory=dict)
