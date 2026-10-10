"""`/api/v1` 公共接口（design.md §8）：agentic 研究任务生命周期 + 版本化 SSE。

- 旧 `/api/*` 接口在兼容期保留不动；v1 用 FastAPI schema 作为契约来源，
  错误统一 application/problem+json（见 app/api/problem.py）。
- SSE：`GET /api/v1/tasks/{id}/events`，事件信封 v1（见 app/services/sse_v1.py），
  支持 Last-Event-ID（头或 query）回放；回答结局与任务生命周期分开。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.problem import V1Problem
from app.schemas.agentic import (
    CancelTaskResponse,
    CreateTaskRequest,
    DeleteTaskResponse,
    TaskListView,
    TaskView,
)
from app.services.agentic_service import AgenticTaskService
from app.services.sse_v1 import SseV1Error, format_sse

router = APIRouter(prefix="/v1", tags=["research-v1"])

_service: AgenticTaskService | None = None

KEEPALIVE_SECONDS = 15.0


async def get_service() -> AgenticTaskService:
    global _service
    if _service is None:
        from app.services.sse_v1 import RedisStreamEventLog
        from app.services.task_state_store import TaskStateStore

        _service = AgenticTaskService(
            event_log=RedisStreamEventLog(),
            task_store=TaskStateStore(namespace="agentic"),
        )
        await _service.initialize()
    return _service


def _task_not_found(task_id: str) -> V1Problem:
    return V1Problem(status=404, code="task_not_found", detail=f"任务不存在: {task_id}")


@router.post("/tasks", response_model=TaskView, status_code=201)
async def create_task(request: CreateTaskRequest) -> TaskView:
    service = await get_service()
    overrides = request.options.as_overrides() if request.options else None
    return await service.create_task(request.query, overrides)


@router.get("/tasks", response_model=TaskListView)
async def list_tasks() -> TaskListView:
    service = await get_service()
    tasks = await service.list_tasks()
    return TaskListView(tasks=tasks, total=len(tasks))


@router.get("/tasks/{task_id}", response_model=TaskView)
async def get_task(task_id: str) -> TaskView:
    service = await get_service()
    task = await service.get_task(task_id)
    if task is None:
        raise _task_not_found(task_id)
    return task


@router.post("/tasks/{task_id}/cancel", response_model=CancelTaskResponse)
async def cancel_task(task_id: str) -> CancelTaskResponse:
    service = await get_service()
    result = await service.cancel_task(task_id)
    if result == "not_found":
        raise _task_not_found(task_id)
    if result == "not_running":
        raise V1Problem(status=409, code="task_not_running", detail=f"任务不在运行中，无法取消: {task_id}")
    return CancelTaskResponse(task_id=task_id)


@router.delete("/tasks/{task_id}", response_model=DeleteTaskResponse)
async def delete_task(task_id: str) -> DeleteTaskResponse:
    service = await get_service()
    result = await service.delete_task(task_id)
    if result == "not_found":
        raise _task_not_found(task_id)
    if result == "running":
        raise V1Problem(status=409, code="task_running", detail=f"运行中的任务不能删除，请先取消: {task_id}")
    return DeleteTaskResponse(task_id=task_id)


@router.get("/tasks/{task_id}/events")
async def stream_task_events(
    task_id: str,
    request: Request,
    last_event_id: str | None = Query(default=None, description="断线重连位点；优先取 Last-Event-ID 头"),
):
    """版本化 SSE：id=事件位点（Last-Event-ID 续传），event=事件类型，data=v1 信封。"""
    service = await get_service()
    task = await service.get_task(task_id)
    if task is None:
        raise _task_not_found(task_id)

    resume_id = request.headers.get("last-event-id") or last_event_id
    after_sequence = 0
    if resume_id:
        try:
            after_sequence = await service.resolve_after_sequence(task_id, resume_id)
        except SseV1Error as exc:
            raise V1Problem(status=400, code="invalid_last_event_id", detail=str(exc))

    async def event_generator():
        sub = service.subscribe(task_id, after_sequence=after_sequence)
        try:
            while True:
                event = await sub.next_event(timeout=KEEPALIVE_SECONDS)
                if event is None:
                    yield ": keepalive\n\n"
                    continue
                yield format_sse(event)
                if event.is_terminal:
                    break
        finally:
            await sub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
