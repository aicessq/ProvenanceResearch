"""evidence_read：回取已登记 Evidence（P3c 文本链路）。

只接受已登记 evidence_id（citation_id），或已抓取来源的 source_id 和页码；
返回原文与定位信息供 Reader/引用闸门核对。视觉阅读（页/region 的
vision 理解）属 P3b，本工具只回文本链路内容。
"""

from __future__ import annotations

from typing import Any

from evidence.store import EvidenceStore
from tools.base import ToolError, ToolMeta, ToolResult, validate_args

ALLOWED_ARGS = {"evidence_id": str, "source_id": str, "page": int}


class EvidenceReadTool:
    name = "evidence_read"

    def __init__(self, *, store: EvidenceStore) -> None:
        self._store = store

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, ALLOWED_ARGS)
        evidence_id, source_id = args.get("evidence_id"), args.get("source_id")
        page = args.get("page")

        if bool(evidence_id) == bool(source_id) or (source_id and (page is None or page < 1)):
            return ToolResult(
                call_id=call_id, status="error",
                error=ToolError("invalid_params", "请提供 evidence_id，或同时提供 source_id 和页码"),
                meta=ToolMeta(provider="evidence_read"),
            )
        if source_id:
            evidence = next((item for item in self._store.by_source(source_id)
                             if item.locator.page == page and item.content_scope == "fulltext"), None)
        else:
            evidence = self._store.get(evidence_id)
        if evidence is None:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("evidence_not_registered", "指定证据或来源页未登记"),
                meta=ToolMeta(provider="evidence_read"),
            )
        if page is not None and evidence.locator.page is not None and evidence.locator.page != page:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError(
                    "page_mismatch",
                    f"证据 {evidence_id} 位于第 {evidence.locator.page} 页，非第 {page} 页",
                ),
                meta=ToolMeta(provider="evidence_read"),
            )

        return ToolResult(
            call_id=call_id,
            status="ok",
            evidence=[evidence],
            meta=ToolMeta(
                provider="evidence_read",
                coverage=evidence.content_scope,
                usage={"chars": len(evidence.raw_text or "")},
            ),
        )
