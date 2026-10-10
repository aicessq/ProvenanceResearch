"""Agentic RAG Core（P3d）：有界 Agent Loop + Reader + Citation Gate。

垂直切片闭环：Question → Agent → Tool → Evidence → Reader →
Citation Gate → Answer / Refusal。Agent 只决定下一动作；
工具白名单、预算、RRF、引用验证由确定性代码执行（design.md §5）。
"""

from agent.budget import AgentState, Budget, StopReason
from agent.citation_gate import (
    CitationGate,
    Claim,
    ClaimCheck,
    GateReport,
    parse_claims,
)
from agent.loop import AgentAnswer, AgentLoop, SemanticVerifier
from agent.reader import fuse

__all__ = [
    "AgentAnswer",
    "AgentLoop",
    "AgentState",
    "Budget",
    "CitationGate",
    "Claim",
    "ClaimCheck",
    "GateReport",
    "SemanticVerifier",
    "StopReason",
    "fuse",
    "parse_claims",
]
