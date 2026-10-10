"""evidence_read：回取已登记 Evidence（P3c 文本链路）。

只接受已登记 evidence_id（citation_id）——不任意读本地路径；
返回原文与定位信息供 Reader/引用闸门核对。视觉阅读（页/region 的
vision 理解）属 P3b，本工具只回文本链路内容。
"""

from __future__ import annotations

from typing import Any

from evidence.store import EvidenceStore
from tools.base import ToolError, ToolMeta, ToolResult, validate_args

ALLOWED_ARGS = {"evidence_id": str, "page": int}
REQUIRED_ARGS = ("evidence_id",)


class EvidenceReadTool:
    name = "evidence_read"

    def __init__(self, *, store: EvidenceStore) -> None:
        self._store = store

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, ALLOWED_ARGS, REQUIRED_ARGS)
        evidence_id = args["evidence_id"]
        page = args.get("page")

        evidence = self._store.get(evidence_id)
        if evidence is None:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("evidence_not_registered", f"evidence_id 未登记: {evidence_id}"),
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
