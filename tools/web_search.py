"""web_search：Web 搜索工具（P3c，首批 Tavily）。

provider 必须是注册值（由调用方传入已启用 provider）；
失败抛结构化错误（工具层不伪造结果——P2.5 纪律）；
结果携带规范 URL 与 fetched_at。检索内容是不可信数据。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from evidence.registry import content_hash, normalize_web_url
from evidence.schema import Evidence, Extraction, Locator, Provenance, Score
from evidence.store import EvidenceStore, register_with_computed_id
from tools.base import ToolError, ToolMeta, ToolResult, validate_args

ALLOWED_ARGS = {"query": str, "top_k": int, "time_range": str}
REQUIRED_ARGS = ("query",)


class WebSearchTool:
    name = "web_search"

    def __init__(
        self,
        *,
        api_key: str,
        provider: str = "tavily",
        client: httpx.AsyncClient | None = None,
        store: EvidenceStore | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._provider = provider
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        self._store = store or EvidenceStore()

    @property
    def store(self) -> EvidenceStore:
        return self._store

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, ALLOWED_ARGS, REQUIRED_ARGS)
        if self._provider != "tavily":
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("unsupported_provider", f"未注册的搜索 provider: {self._provider}"),
                meta=ToolMeta(provider=self._provider),
            )
        if not self._api_key:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("config_missing", "TAVILY_API_KEY 未配置", retryable=False),
                meta=ToolMeta(provider=self._provider),
            )

        query = args["query"]
        top_k = int(args.get("top_k", 5))
        started = time.perf_counter()
        try:
            resp = await self._client.post(
                "https://api.tavily.com/search",
                json={"api_key": self._api_key, "query": query, "max_results": top_k},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("provider_unavailable", f"Tavily 调用失败: {type(exc).__name__}", retryable=True),
                meta=ToolMeta(provider=self._provider),
            )
        except ValueError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("invalid_response", f"Tavily 响应非法: {exc}"),
                meta=ToolMeta(provider=self._provider),
            )

        fetched_at = datetime.now(timezone.utc).isoformat()
        evidence: list[Evidence] = []
        for item in data.get("results", []) or []:
            url = str(item.get("url") or "")
            snippet = str(item.get("content") or "")[:500]
            provenance = Provenance(
                provider=self._provider,
                title=str(item.get("title") or ""),
                content_hash=content_hash(snippet),
                canonical_url=normalize_web_url(url),
                fetched_at=fetched_at,
            )
            ev = Evidence(
                citation_id="",
                source_id=f"web:{normalize_web_url(url)}",
                source_type="web",
                modality="text",
                content_scope="snippet",
                raw_text=snippet,
                provenance=provenance,
                locator=Locator(url=normalize_web_url(url)),
                extraction=Extraction(method="provider_text", provider=self._provider),
                score=Score(raw=0.0, raw_channel=self._provider),
            )
            evidence.append(register_with_computed_id(self._store, ev))

        latency = (time.perf_counter() - started) * 1000
        return ToolResult(
            call_id=call_id,
            status="ok" if evidence else "empty",
            evidence=evidence,
            meta=ToolMeta(
                provider=self._provider,
                latency_ms=round(latency, 2),
                usage={"results": len(evidence)},
                coverage=f"snippet,top_k={top_k}",
            ),
        )
