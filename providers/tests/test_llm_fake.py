"""Fake LLM Provider 行为契约（脚本化成功/故障，仅限测试）。"""

from __future__ import annotations

import asyncio

import pytest

from providers.errors import ProviderError, ProviderErrorCode
from providers.llm.base import LLMMessage
from providers.llm.fake import FakeLLMProvider

MESSAGES = [LLMMessage(role="user", content="hi")]


def test_fake_returns_scripted_text_in_order() -> None:
    provider = FakeLLMProvider(["first", "second"])
    assert asyncio.run(provider.generate(MESSAGES)).text == "first"
    assert asyncio.run(provider.generate(MESSAGES)).text == "second"


def test_fake_raises_scripted_provider_error() -> None:
    err = ProviderError(ProviderErrorCode.RATE_LIMIT, "scripted 429", provider="fake")
    provider = FakeLLMProvider([err])
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.RATE_LIMIT


def test_fake_records_calls_for_assertion() -> None:
    provider = FakeLLMProvider(["ok"])
    asyncio.run(provider.generate(MESSAGES))
    assert provider.calls[0][0].content == "hi"


def test_fake_fails_loudly_when_script_exhausted() -> None:
    provider = FakeLLMProvider([])
    with pytest.raises(RuntimeError):
        asyncio.run(provider.generate(MESSAGES))
