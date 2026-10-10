"""Fake LLM Provider：无凭证的脚本化实现（测试专用）。

用途：P3d 让 fake LLM 驱动真实 graph/executor，以及本层契约测试。
行为完全由脚本决定——成功文本或带错误码的 ProviderError；
它绝不是生产 fallback（AGENTS.md：mock 仅限测试）。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from providers.errors import ProviderError
from providers.llm.base import LLMMessage, LLMResult


class FakeLLMProvider:
    """按脚本逐次响应的 LLM provider。

    responses 每项为 str（成功文本）或 ProviderError（抛出该错误）；
    脚本耗尽后继续调用会抛 RuntimeError 让测试尽早失败。
    每次调用的 messages 被记录到 self.calls 供断言。
    """

    provider_name = "fake"

    def __init__(self, responses: Sequence[str | ProviderError], *, model: str = "fake-model") -> None:
        self._responses = list(responses)
        self._model = model
        self.calls: list[list[LLMMessage]] = []

    async def generate(
        self,
        messages: Sequence[LLMMessage],
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResult:
        self.calls.append(list(messages))
        if not self._responses:
            raise RuntimeError("FakeLLMProvider 脚本已耗尽")
        item = self._responses.pop(0)
        if isinstance(item, ProviderError):
            raise item
        return LLMResult(text=item, provider=self.provider_name, model=self._model)
