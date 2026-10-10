"""arxiv_search：arXiv 论文检索工具（P3c）。

官方元数据接口无需 API key——不编造必须凭证；
记录论文 ID、明确版本与摘要范围（content_scope=abstract），
摘要不得冒充全文（全文断言须经 source_fetch 成功获取正文）；
按官方使用限制节流（默认请求间隔 3 秒，可注入时钟用于测试）。
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable

import httpx

from evidence.registry import content_hash
from evidence.schema import Evidence, Extraction, Locator, Provenance, Score
from evidence.store import EvidenceStore, register_with_computed_id
from tools.base import ToolError, ToolMeta, ToolResult, validate_args

ARXIV_API = "https://export.arxiv.org/api/query"
MIN_REQUEST_INTERVAL_SECONDS = 3.0

ALLOWED_ARGS = {"query": str, "top_k": int, "category": str}
REQUIRED_ARGS = ("query",)

_ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.DOTALL)
_ID_RE = re.compile(r"<id>\s*http://arxiv\.org/abs/(\d{4}\.\d{4,5}(v\d+)?)\s*</id>", re.DOTALL)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)


class ArxivSearchTool:
    name = "arxiv_search"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        store: EvidenceStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        self._store = store or EvidenceStore()
        self._sleep = sleep
        self._min_interval = min_interval_seconds
        self._last_request_at: float | None = None

    @property
    def store(self) -> EvidenceStore:
        return self._store

    async def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._min_interval:
                await self._sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, ALLOWED_ARGS, REQUIRED_ARGS)
        query = args["query"]
        top_k = int(args.get("top_k", 5))
        started = time.perf_counter()
        try:
            await self._throttle()
            resp = await self._client.get(
                ARXIV_API,
                params={"search_query": f"all:{query}", "max_results": top_k},
            )
            resp.raise_for_status()
            body = resp.text
        except httpx.HTTPError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("provider_unavailable", f"arXiv 调用失败: {type(exc).__name__}", retryable=True),
                meta=ToolMeta(provider="arxiv"),
            )

        evidence: list[Evidence] = []
        for entry in _ENTRY_RE.findall(body):
            id_match = _ID_RE.search(entry)
            summary_match = _SUMMARY_RE.search(entry)
            if not id_match or not summary_match:
                continue
            arxiv_raw = id_match.group(1)          # 如 2304.09848v1
            version_match = re.search(r"(v\d+)$", arxiv_raw)
            version = version_match.group(1) if version_match else "v1"
            base_id = arxiv_raw[: -len(version)] if version_match else arxiv_raw
            summary = " ".join(summary_match.group(1).split())
            title_match = _TITLE_RE.search(entry)
            title = " ".join(title_match.group(1).split()) if title_match else ""
            if not summary:
                continue
            abs_url = f"http://arxiv.org/abs/{arxiv_raw}"
            provenance = Provenance(
                provider="arxiv",
                title=title,
                content_hash=content_hash(summary),
                arxiv_id=base_id,
                arxiv_version=version,
                fulltext_url=abs_url,
            )
            ev = Evidence(
                citation_id="",
                source_id=f"paper:arxiv:{base_id}:{version}",
                source_type="paper",
                modality="text",
                content_scope="abstract",
                raw_text=summary,
                provenance=provenance,
                locator=Locator(url=abs_url),
                extraction=Extraction(method="provider_text", provider="arxiv"),
                score=Score(raw=0.0, raw_channel="arxiv"),
            )
            evidence.append(register_with_computed_id(self._store, ev))

        latency = (time.perf_counter() - started) * 1000
        return ToolResult(
            call_id=call_id,
            status="ok" if evidence else "empty",
            evidence=evidence,
            meta=ToolMeta(
                provider="arxiv",
                latency_ms=round(latency, 2),
                usage={"papers": len(evidence)},
                coverage=f"abstract,top_k={top_k}",
            ),
        )
