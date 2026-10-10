"""Agent 预算与停止原因（execution-plan Phase 3 / design.md §4）。

默认：max_round=3、max_tool_calls=12（含 retry/fetch/read）、
max_tokens=20000、deadline=180s。执行前预留、超出即停止，
不重置、不放宽容忍——预算约束是"有界 Agent"的硬边界。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class AgentState(str, Enum):
    PLAN = "PLAN"
    TOOL_CALL = "TOOL_CALL"
    EVIDENCE_UPDATE = "EVIDENCE_UPDATE"
    GAP_CHECK = "GAP_CHECK"
    GENERATE = "GENERATE"
    VERIFY = "VERIFY"
    DONE = "DONE"


class StopReason(str, Enum):
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    NO_PROGRESS = "no_progress"
    CITATION_GATE_FAILED = "citation_gate_failed"


DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_TOOL_CALLS = 12
DEFAULT_MAX_MODEL_TOKENS = 20000
DEFAULT_DEADLINE_SECONDS = 180.0


@dataclass
class Budget:
    """有界执行的计数器。clock 可注入以便测试 deadline。"""

    max_rounds: int = DEFAULT_MAX_ROUNDS
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    max_tokens: int = DEFAULT_MAX_MODEL_TOKENS
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    clock: Callable[[], float] = time.monotonic
    started_at: float = field(default_factory=time.monotonic)
    rounds: int = 0
    tool_calls: int = 0
    tokens: int = 0

    def elapsed(self) -> float:
        return self.clock() - self.started_at

    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.tokens)

    def remaining_tool_calls(self) -> int:
        return max(0, self.max_tool_calls - self.tool_calls)

    def remaining_rounds(self) -> int:
        return max(0, self.max_rounds - self.rounds)

    def charge_tokens(self, amount: int) -> None:
        if amount > 0:
            self.tokens += amount

    def charge_tool_call(self) -> None:
        self.tool_calls += 1

    def begin_round(self) -> None:
        self.rounds += 1

    def exceeded(self) -> StopReason | None:
        """预算/时限是否已超：超时优先于超量报告。"""
        if self.elapsed() > self.deadline_seconds:
            return StopReason.DEADLINE_EXCEEDED
        if (
            self.tool_calls >= self.max_tool_calls
            or self.tokens >= self.max_tokens
            or self.rounds > self.max_rounds
        ):
            return StopReason.BUDGET_EXHAUSTED
        return None

    def report(self) -> dict:
        return {
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "tokens": self.tokens,
            "elapsed_seconds": round(self.elapsed(), 3),
            "max_rounds": self.max_rounds,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "deadline_seconds": self.deadline_seconds,
        }
