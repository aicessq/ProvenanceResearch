"""工具层（P3c-text）：五个 Agent 可调用工具 + 执行器。

工具：kb_search / web_search / arxiv_search / source_fetch / evidence_read。
执行器负责白名单与失败隔离：单源失败不取消健康来源；
所有产出登记进 EvidenceStore（同构 Evidence + 稳定 citation_id）。
预算/循环检测由 P3d Agent 层负责，本层只管调用契约。
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from tools.base import (
    ToolArgError,
    ToolError,
    ToolMeta,
    ToolResult,
    validate_args,
)
from tools.evidence_read import EvidenceReadTool
from tools.kb_search import KBSearchTool
from tools.source_fetch import SourceFetchTool
from tools.web_search import WebSearchTool
from tools.arxiv_search import ArxivSearchTool


class Tool(Protocol):
    name: str

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult: ...


class ToolExecutor:
    """白名单工具执行器。未注册工具名直接拒绝——模型不能调用任意函数。"""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"工具重名: {tool.name}")
            self._tools[tool.name] = tool

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        call_id = uuid.uuid4().hex[:12]
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("tool_not_allowed", f"未注册工具: {name}"),
            )
        try:
            return await tool.execute(call_id, **kwargs)
        except ToolArgError as exc:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("invalid_params", str(exc)),
            )
        except Exception as exc:  # noqa: BLE001 - 单工具崩溃不拖垮其他来源
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("tool_crashed", f"{type(exc).__name__}", retryable=True),
            )


__all__ = [
    "ArxivSearchTool",
    "EvidenceReadTool",
    "KBSearchTool",
    "SourceFetchTool",
    "Tool",
    "ToolArgError",
    "ToolError",
    "ToolExecutor",
    "ToolMeta",
    "ToolResult",
    "WebSearchTool",
    "validate_args",
]
