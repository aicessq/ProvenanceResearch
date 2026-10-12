"""DeepSeek LLM Provider（OpenAI 兼容 chat/completions，真实云调用）。

P3a 的"一个真实 provider"：演示 timeout / retry / 429 / 5xx / 错误分类
在真实协议上的完整实现。api_key 只发往配置绑定的 host、不跨重定向
（2026-09-18 决策）。缺配置显式失败，不静默降级。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping, Sequence

import httpx

from providers.errors import ProviderError, ProviderErrorCode, classify_http_status
from providers.llm.base import LLMMessage, LLMResult

DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekLLMProvider:
    provider_name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_delay_seconds: float = 1.0,
        client: httpx.AsyncClient | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = model
        self._base_url = (base_url or "").strip().rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._retry_delay_seconds = retry_delay_seconds
        # 网关类端点的附加请求头（如 opencode.ai 的 x-opencode-session）；不承载凭证
        self._extra_headers = dict(extra_headers or {})
        # 测试注入 MockTransport 用；生产路径由本类自建且禁重定向
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = client is None

    async def generate(
        self,
        messages: Sequence[LLMMessage],
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResult:
        self._require_config()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if metadata:
            for key in ("temperature", "max_tokens"):
                if key in metadata:
                    payload[key] = metadata[key]

        last_error: ProviderError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}", **self._extra_headers},
                )
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    ProviderErrorCode.TIMEOUT,
                    f"DeepSeek 调用超时（{self._timeout_seconds}s）",
                    provider=self.provider_name,
                )
            except httpx.TransportError as exc:
                last_error = ProviderError(
                    ProviderErrorCode.SERVER_ERROR,
                    f"DeepSeek 传输失败: {exc}",
                    provider=self.provider_name,
                )
            else:
                if resp.status_code == 200:
                    return self._parse(resp)
                last_error = ProviderError(
                    classify_http_status(resp.status_code),
                    f"DeepSeek HTTP {resp.status_code}: {resp.text[:200]}",
                    provider=self.provider_name,
                )

            if not last_error.retryable or attempt == self._max_retries:
                raise last_error
            await asyncio.sleep(self._retry_delay_seconds * (2**attempt))

        raise last_error  # pragma: no cover - 循环内必然 raise 或 return

    def _require_config(self) -> None:
        if not self._api_key or not self._base_url:
            raise ProviderError(
                ProviderErrorCode.CONFIG_MISSING,
                "DeepSeek api_key/base_url 未配置，拒绝发起调用",
                provider=self.provider_name,
            )
        if not self._base_url.startswith("https://"):
            raise ProviderError(
                ProviderErrorCode.CONFIG_MISSING,
                f"DeepSeek base_url 必须是 https: {self._base_url}",
                provider=self.provider_name,
            )

    def _parse(self, resp: httpx.Response) -> LLMResult:
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            if not isinstance(content, str):
                raise TypeError("content 不是字符串")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                f"DeepSeek 响应结构非法: {exc}",
                provider=self.provider_name,
            ) from exc
        return LLMResult(
            text=content,
            provider=self.provider_name,
            model=str(data.get("model") or self._model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
