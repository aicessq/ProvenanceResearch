from __future__ import annotations

import logging
import os

import httpx

from app.core.errors import ProviderUnavailableError

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """搜索 Web 来源；失败/缺配置一律抛 ProviderUnavailableError（P2.5-0.2）。

        禁止返回 mock 结果——由上层决定 retry / fallback / refusal。
        """
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            raise ProviderUnavailableError("TAVILY_API_KEY 未配置，Web 搜索不可用")
        return await self._tavily_search(query, max_results, api_key)

    async def _tavily_search(self, query: str, max_results: int, api_key: str) -> list[dict]:
        try:
            resp = await self._client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:500],
                    "source_type": "unknown",
                    "publish_date": r.get("published_date"),
                    "credibility_score": 0.6,
                })
            return results
        except ProviderUnavailableError:
            raise
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            raise ProviderUnavailableError(f"Tavily 搜索失败: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()
