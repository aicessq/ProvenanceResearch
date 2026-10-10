"""source_fetch：获取已登记来源的正文（P3c）。

只接受 Source Registry 已登记的 source_id（模型不能提供任意地址）；
逐跳 SSRF 校验、大小/MIME 限制（fetch_guard）；
成功获取的正文为 content_scope=fulltext——摘要不得冒充全文，
未成功获取/解析全文时标记缺口（status=error），由上层决定拒答。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from evidence.registry import SourceRegistry, content_hash
from evidence.schema import Evidence, Extraction, Locator, Provenance, Score
from evidence.store import EvidenceStore, register_with_computed_id
from tools.base import ToolError, ToolMeta, ToolResult, validate_args
from tools.fetch_guard import (
    FetchBlockedError,
    FetchPolicy,
    enforce_size,
    validate_content_type,
    validate_fetch_url,
)

ALLOWED_ARGS = {"source_id": str, "content_scope": str}
REQUIRED_ARGS = ("source_id",)


class SourceFetchTool:
    name = "source_fetch"

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        client: httpx.AsyncClient | None = None,
        store: EvidenceStore | None = None,
        policy: FetchPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        self._store = store or EvidenceStore()
        self._policy = policy or FetchPolicy()

    @property
    def store(self) -> EvidenceStore:
        return self._store

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, ALLOWED_ARGS, REQUIRED_ARGS)
        source_id = args["source_id"]
        content_scope = args.get("content_scope", "fulltext")
        if content_scope not in ("fulltext", "snippet"):
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("invalid_params", f"content_scope 仅支持 fulltext/snippet: {content_scope}"),
                meta=ToolMeta(provider="source_fetch"),
            )
        source = self._registry.get(source_id)
        if source is None:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("source_not_registered", f"source_id 未登记: {source_id}"),
                meta=ToolMeta(provider="source_fetch"),
            )

        started = time.perf_counter()
        try:
            target = validate_fetch_url(source.url)
            redirects = 0
            while True:
                resp = await self._client.get(target)
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirects += 1
                    if redirects > self._policy.max_redirects:
                        raise FetchBlockedError(f"重定向超过上限 {self._policy.max_redirects}")
                    location = resp.headers.get("location", "")
                    target = validate_fetch_url(location)  # 每一跳都重新校验
                    continue
                resp.raise_for_status()
                break
            validate_content_type(resp.headers.get("content-type", ""))
            body = resp.content
            enforce_size(len(body), self._policy)
            text = body.decode("utf-8", errors="replace")
        except FetchBlockedError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("fetch_blocked", str(exc), retryable=False),
                meta=ToolMeta(provider="source_fetch"),
            )
        except httpx.HTTPError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("provider_unavailable", f"获取正文失败: {type(exc).__name__}", retryable=True),
                meta=ToolMeta(provider="source_fetch"),
            )

        provenance = Provenance(
            provider="source_fetch",
            title=source.metadata.get("title", ""),
            content_hash=content_hash(text),
            canonical_url=source.url,
            fetched_at=source.metadata.get("fetched_at", ""),
            arxiv_id=source.metadata.get("arxiv_id"),
            arxiv_version=source.metadata.get("arxiv_version"),
        )
        source_type = "paper" if source.type == "paper" else "web"
        ev = Evidence(
            citation_id="",
            source_id=source.id,
            source_type=source_type,
            modality="text",
            content_scope=content_scope,
            raw_text=text,
            provenance=provenance,
            locator=Locator(url=source.url),
            extraction=Extraction(method="native_text", provider="source_fetch"),
            score=Score(),
        )
        registered = register_with_computed_id(self._store, ev)
        latency = (time.perf_counter() - started) * 1000
        return ToolResult(
            call_id=call_id,
            status="ok",
            evidence=[registered],
            meta=ToolMeta(
                provider="source_fetch",
                latency_ms=round(latency, 2),
                usage={"bytes": len(body)},
                coverage=content_scope,
            ),
        )
