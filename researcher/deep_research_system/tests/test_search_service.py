"""P2.5-0.2 搜索服务不得返回 mock 结果（fake success）测试。"""

from __future__ import annotations

import pytest

from app.core.errors import ProviderUnavailableError
from app.services.search_service import SearchService


@pytest.fixture
def service() -> SearchService:
    return SearchService()


@pytest.mark.asyncio
async def test_search_raises_when_api_key_missing(monkeypatch, service: SearchService) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailableError):
        await service.search("any query")
    await service.close()


@pytest.mark.asyncio
async def test_search_raises_when_tavily_fails(monkeypatch, service: SearchService) -> None:
    """Tavily 调用失败不得回退 mock 结果，必须抛 ProviderUnavailableError。"""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    class FailingResponse:
        def raise_for_status(self):
            raise RuntimeError("HTTP 500")

    class FailingClient:
        async def post(self, *args, **kwargs):
            return FailingResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr(service, "_client", FailingClient())
    with pytest.raises(ProviderUnavailableError):
        await service.search("any query")
    await service.close()


@pytest.mark.asyncio
async def test_search_returns_real_results_on_success(monkeypatch, service: SearchService) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    class OkResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": "T1", "url": "https://example.org/a", "content": "text", "published_date": "2026-01-01"}
                ]
            }

    class OkClient:
        async def post(self, *args, **kwargs):
            return OkResponse()

        async def aclose(self):
            return None

    monkeypatch.setattr(service, "_client", OkClient())
    results = await service.search("q")
    assert results and results[0]["url"] == "https://example.org/a"
    assert all("example.com/result" not in r["url"] for r in results)
    await service.close()
