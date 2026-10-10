"""`/api/v1` 公共契约（design.md §8）：FastAPI schema 即 HTTP/OpenAPI 契约来源。

回答结局（answered/refused）与任务生命周期（pending/running/completed/failed/
cancelled）是两个维度：拒答是 completed 任务的回答结局，error 只描述任务失败。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from agent.budget import (
    DEFAULT_DEADLINE_SECONDS,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MAX_MODEL_TOKENS,
    DEFAULT_MAX_TOOL_CALLS,
)


class TaskBudgetOptions(BaseModel):
    """任务级预算（覆盖 agent.budget 默认值；循环有界是硬边界）。"""

    max_rounds: int = Field(DEFAULT_MAX_ROUNDS, ge=1, le=10)
    max_tool_calls: int = Field(DEFAULT_MAX_TOOL_CALLS, ge=1, le=50)
    max_tokens: int = Field(DEFAULT_MAX_MODEL_TOKENS, ge=100, le=200000)
    deadline_seconds: float = Field(DEFAULT_DEADLINE_SECONDS, ge=5.0, le=1800.0)

    def as_overrides(self) -> dict[str, Any]:
        return {
            "max_rounds": self.max_rounds,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "deadline_seconds": self.deadline_seconds,
        }


class CreateTaskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000, description="研究问题")
    options: TaskBudgetOptions | None = Field(default=None, description="预算覆盖；缺省用默认预算")


class ClaimView(BaseModel):
    claim: str
    citations: list[str]
    scope: Literal["snippet", "abstract", "fulltext", "region"]


class AnsweredOutcome(BaseModel):
    """回答结局=已回答：文本与逐条 claims 均经引用闸门验证。"""

    status: Literal["answered"] = "answered"
    text: str
    claims: list[ClaimView]
    citations: list[str]
    stop_reason: str
    budget_report: dict[str, Any]
    evidence: list[dict[str, Any]]
    latency_ms: float | None = None


class RefusedOutcome(BaseModel):
    """回答结局=拒答：无登记证据/引用闸门未过/预算耗尽等，附明确原因。"""

    status: Literal["refused"] = "refused"
    refusal_reason: str
    stop_reason: str
    budget_report: dict[str, Any]
    evidence: list[dict[str, Any]]
    latency_ms: float | None = None


AnswerView = Annotated[Union[AnsweredOutcome, RefusedOutcome], Field(discriminator="status")]


class TaskErrorView(BaseModel):
    code: str
    message: str


class TaskView(BaseModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    query: str
    created_at: str
    updated_at: str
    completed_at: str | None = None
    answer: AnswerView | None = None
    error: TaskErrorView | None = None


class TaskListView(BaseModel):
    tasks: list[TaskView]
    total: int


class CancelTaskResponse(BaseModel):
    task_id: str
    status: Literal["cancelled"] = "cancelled"


class DeleteTaskResponse(BaseModel):
    task_id: str
    deleted: bool = True


class Problem(BaseModel):
    """application/problem+json（RFC 7807）+ request_id + 稳定机器码。"""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    request_id: str | None = None
    code: str
