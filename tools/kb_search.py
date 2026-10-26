"""kb_search：私库检索工具（P3c）。

通过内部 HTTP 调用 KB（固定内部地址，不能由搜索结果任意指定）；
只召回，不在工具内偷偷跨源融合；KB 结果携带 doc/version/chunk/index 身份。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from evidence.registry import content_hash
from evidence.schema import Evidence, Extraction, Locator, Provenance, Score
from evidence.store import EvidenceStore, register_with_computed_id
from tools.base import ToolMeta, ToolResult, validate_args

ALLOWED_ARGS = {
    "query": str,
    "top_k": int,
    "mode": str,
    "doc_type": list,
}
REQUIRED_ARGS = ("query",)


class KBSearchTool:
    name = "kb_search"

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        store: EvidenceStore | None = None,
        index_identity: str = "",
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        self._store = store or EvidenceStore()
        self._index_identity = index_identity

    @property
    def store(self) -> EvidenceStore:
        return self._store

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, ALLOWED_ARGS, REQUIRED_ARGS)
        query = args["query"]
        top_k = int(args.get("top_k", 5))
        mode = args.get("mode", "vector")
        if mode not in ("vector", "keyword"):
            return ToolResult(
                call_id=call_id,
                status="error",
                error=_err("invalid_params", f"mode 仅支持 vector/keyword: {mode}"),
            )
        started = time.perf_counter()
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/query/retrieve",
                json={
                    "query": query,
                    "top_k": top_k,
                    "filters": {"doc_type": args.get("doc_type") or []},
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=_err("provider_unavailable", f"KB 检索失败: {type(exc).__name__}", retryable=True),
                meta=ToolMeta(provider="knowledge_engine"),
            )
        except ValueError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=_err("invalid_response", f"KB 响应非法: {exc}"),
                meta=ToolMeta(provider="knowledge_engine"),
            )

        chunks = payload.get("chunks") or []
        identities = {str(item.get("index_identity") or self._index_identity) for item in chunks}
        if chunks and "" in identities:
            return ToolResult(call_id=call_id, status="error", error=_err("invalid_response", "KB 缺少索引身份"))
        if len(identities) > 1 or (identities and self._index_identity and identities != {self._index_identity}):
            return ToolResult(call_id=call_id, status="error", error=_err("index_identity_mismatch", "KB 索引身份与配置不一致"))
        index_identity = next(iter(identities), self._index_identity)
        evidence: list[Evidence] = []
        for item in chunks:
            text = str(item.get("chunk_text") or "")
            provenance = Provenance(
                provider="knowledge_engine",
                title=str(item.get("doc_title") or ""),
                content_hash=content_hash(text),
                doc_id=str(item.get("document_id") or ""),
                doc_title=str(item.get("doc_title") or ""),
                doc_version=str(item.get("version_id") or ""),
                chunk_id=str(item.get("chunk_id") or ""),
                index_identity=index_identity,
            )
            locator = Locator(
                page=item.get("page_start"),
                chunk=str(item.get("chunk_id") or ""),
                section=item.get("section"),
            )
            ev = Evidence(
                citation_id="",  # register_with_computed_id 重算
                source_id=f"kb:{item.get('document_id')}:{item.get('version_id')}",
                source_type="kb_chunk",
                modality="text",
                content_scope="fulltext",
                raw_text=text,
                provenance=provenance,
                locator=locator,
                extraction=Extraction(method="native_text", provider="knowledge_engine"),
                score=Score(raw=float(item.get("score") or 0.0), raw_channel=f"kb_{mode}"),
            )
            evidence.append(register_with_computed_id(self._store, ev))

        latency = (time.perf_counter() - started) * 1000
        meta = ToolMeta(
            provider="knowledge_engine",
            latency_ms=round(latency, 2),
            index_identity=index_identity,
            usage={"chunks_returned": len(evidence)},
            coverage=f"mode={mode},top_k={top_k}",
        )
        return ToolResult(
            call_id=call_id,
            status="ok" if evidence else "empty",
            evidence=evidence,
            meta=meta,
        )


def _err(code: str, message: str, retryable: bool = False):
    from tools.base import ToolError

    return ToolError(code=code, message=message, retryable=retryable)
