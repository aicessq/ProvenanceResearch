"""LLM Adapter 错误分类与重试契约（P3a 验收）。

fake 传输模拟 401 / 429 / timeout / malformed response，断言：
错误码分类正确、可重试性正确、429/5xx/timeout 重试、401/malformed 不重试。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from providers.errors import ProviderError, ProviderErrorCode, classify_http_status
from providers.llm.deepseek import DeepSeekLLMProvider
from providers.llm.base import LLMMessage

MESSAGES = [LLMMessage(role="user", content="hi")]


def _provider(handler, *, max_retries: int = 2) -> DeepSeekLLMProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return DeepSeekLLMProvider(
        api_key="test-key",
        max_retries=max_retries,
        retry_delay_seconds=0.0,
        client=client,
    )


def _ok_body(text: str = "answer") -> dict:
    return {
        "model": "deepseek-chat",
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }


def test_classify_http_status_mapping() -> None:
    assert classify_http_status(401) == ProviderErrorCode.AUTH_FAILED
    assert classify_http_status(403) == ProviderErrorCode.AUTH_FAILED
    assert classify_http_status(429) == ProviderErrorCode.RATE_LIMIT
    assert classify_http_status(500) == ProviderErrorCode.SERVER_ERROR
    assert classify_http_status(503) == ProviderErrorCode.SERVER_ERROR
    assert classify_http_status(400) == ProviderErrorCode.INVALID_RESPONSE


def test_success_parses_content_and_usage() -> None:
    provider = _provider(lambda req: httpx.Response(200, json=_ok_body("hello")))
    result = asyncio.run(provider.generate(MESSAGES))
    assert result.text == "hello"
    assert result.provider == "deepseek"
    assert result.prompt_tokens == 3
    assert result.completion_tokens == 1


def test_extra_headers_sent_with_bearer() -> None:
    """网关端点契约：extra_headers 随请求发出且不承载凭证；Authorization 照旧。"""
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(200, json=_ok_body())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    provider = DeepSeekLLMProvider(
        api_key="test-key",
        client=client,
        extra_headers={"x-opencode-session": "sess-123"},
    )
    asyncio.run(provider.generate(MESSAGES))
    assert seen.get("x-opencode-session") == "sess-123"
    assert seen.get("authorization") == "Bearer test-key"


def test_401_maps_to_auth_failed_and_is_not_retried() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    provider = _provider(handler)
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.AUTH_FAILED
    assert exc.value.retryable is False
    assert len(calls) == 1


def test_429_retries_then_succeeds() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) < 3:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json=_ok_body())

    provider = _provider(handler)
    result = asyncio.run(provider.generate(MESSAGES))
    assert result.text == "answer"
    assert len(calls) == 3


def test_429_exhausts_retries_and_raises_rate_limit() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(429, text="rate limited")

    provider = _provider(handler, max_retries=2)
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.RATE_LIMIT
    assert exc.value.retryable is True
    assert len(calls) == 3  # 1 次原始 + 2 次重试


def test_5xx_maps_to_server_error_with_retry() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(500, text="boom")

    provider = _provider(handler, max_retries=1)
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.SERVER_ERROR
    assert len(calls) == 2


def test_timeout_maps_to_timeout_and_retries() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("simulated timeout")

    provider = _provider(handler, max_retries=1)
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.TIMEOUT
    assert exc.value.retryable is True
    assert len(calls) == 2


@pytest.mark.parametrize(
    "body",
    [
        "not-json{{",
        json.dumps({"choices": []}),
        json.dumps({"choices": [{"message": {}}]}),
        json.dumps({"choices": [{"message": {"content": 123}}]}),
    ],
)
def test_malformed_response_maps_to_invalid_response_without_retry(body: str) -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, text=body)

    provider = _provider(handler)
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.INVALID_RESPONSE
    assert exc.value.retryable is False
    assert len(calls) == 1


def test_missing_config_fails_without_any_request() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=_ok_body())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekLLMProvider(api_key="", client=client)
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.CONFIG_MISSING
    assert calls == []


def test_http_base_url_rejected() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    provider = DeepSeekLLMProvider(
        api_key="k", base_url="http://api.deepseek.com", client=client
    )
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(MESSAGES))
    assert exc.value.code == ProviderErrorCode.CONFIG_MISSING


def test_key_only_sent_to_bound_host() -> None:
    """密钥只发绑定主机：请求只出现在配置的 base_url 上。"""
    seen: list[str] = []

    def handler(req):
        seen.append(str(req.url))
        assert req.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=_ok_body())

    provider = _provider(handler)
    asyncio.run(provider.generate(MESSAGES))
    assert all(u.startswith("https://api.deepseek.com/") for u in seen)


def test_compatible_vendor_identity_and_token_accounting():
    async def check():
        def handler(request):
            assert str(request.url) == "https://api.agnes-ai.cn/v1/chat/completions"
            assert "x-opencode-session" not in request.headers
            body = _ok_body("OK")
            body["model"] = "agnes-3.0-flash"
            return httpx.Response(200, json=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekLLMProvider(api_key="synthetic-key", model="agnes-3.0-flash",
                base_url="https://api.agnes-ai.cn/v1", provider_name="agnes", client=client)
            result = await provider.generate(MESSAGES)
            assert result.provider == "agnes"
            assert result.model == "agnes-3.0-flash"
            assert result.prompt_tokens + result.completion_tokens == 4
    asyncio.run(check())
