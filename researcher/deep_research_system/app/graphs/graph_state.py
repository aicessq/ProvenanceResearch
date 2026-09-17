from __future__ import annotations

from typing import Any, Callable, Awaitable, TypedDict, NotRequired

from app.schemas.state import ResearchState

EventCallback = Callable[[dict], Awaitable[None]] | Callable[[dict], None] | None


class GraphContext(TypedDict):
    state: ResearchState
    on_event: NotRequired[EventCallback]
    last_validation: NotRequired[dict]
    supplementary_result: NotRequired[dict | None]
    repair_attempt: NotRequired[int]
    supplementary_loop_count: NotRequired[int]
    last_plan_result: NotRequired[dict]
