from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.routes_v1 import rate_limit, require_auth
from app.core.errors import TaskNotFoundError
from app.schemas.agentic import ClarificationRequest
from app.schemas.response import success_response
from app.schemas.task import ResearchRequest
from app.services.research_service import DeleteTaskResult, ResearchService

router = APIRouter(tags=["research"], dependencies=[Depends(require_auth), Depends(rate_limit("default"))])

_service: ResearchService | None = None


async def get_service() -> ResearchService:
    global _service
    if _service is None:
        _service = ResearchService()
        await _service.initialize()
    return _service


@router.post("/research", dependencies=[Depends(rate_limit("query"))])
async def create_research(request: ResearchRequest):
    service = await get_service()
    data = request.model_dump()
    data["user_query"] = data.pop("query", "")
    task = await service.create_task(data)
    return success_response(task)


@router.post("/research/sync", dependencies=[Depends(rate_limit("query"))])
async def create_research_sync(request: ResearchRequest):
    service = await get_service()
    data = request.model_dump()
    data["user_query"] = data.pop("query", "")
    task = await service.create_task_sync(data)
    return success_response(task)


@router.get("/research")
async def list_research():
    service = await get_service()
    return success_response(await service.get_all_tasks())


@router.get("/research/{task_id}")
async def get_research(task_id: str):
    service = await get_service()
    task = await service.get_task(task_id)
    if not task:
        raise TaskNotFoundError(task_id)
    return success_response(task)


@router.post("/research/{task_id}/clarification", dependencies=[Depends(rate_limit("query"))])
async def clarify_research(task_id: str, request: ClarificationRequest):
    service = await get_service()
    result = await service.submit_clarification(task_id, request.round, request.answer)
    if result == "not_found":
        raise TaskNotFoundError(task_id)
    if result != "accepted":
        raise HTTPException(status_code=409, detail="任务当前没有等待这一轮补充")
    return success_response({"task_id": task_id, "status": result})


@router.post("/research/{task_id}/cancel")
async def cancel_research(task_id: str):
    service = await get_service()
    success = await service.cancel_task(task_id)
    if not success:
        raise TaskNotFoundError(task_id)
    return success_response({"task_id": task_id, "status": "cancelled"})


@router.delete("/research/{task_id}")
async def delete_research(task_id: str):
    service = await get_service()
    result = await service.delete_task(task_id)
    if result == DeleteTaskResult.NOT_FOUND:
        raise TaskNotFoundError(task_id)
    if result == DeleteTaskResult.RUNNING:
        raise HTTPException(status_code=409, detail="running task cannot be deleted")
    return success_response({"task_id": task_id, "deleted": True})


@router.get("/research/{task_id}/stream")
async def stream_research(task_id: str):
    service = await get_service()
    task = await service.get_task(task_id)
    if not task:
        raise TaskNotFoundError(task_id)

    async def event_generator():
        queue = service.subscribe(task_id)
        try:
            # Subscribe before reading the snapshot so completion cannot fall between them.
            snapshot = await service.get_task(task_id) or task
            yield f"data: {json.dumps({'type': 'state', 'data': snapshot}, ensure_ascii=False)}\n\n"
            status = snapshot["status"]
            terminal = {"completed": "done", "cancelled": "cancelled", "failed": "error"}.get(status)
            if terminal:
                event = {"type": terminal, "task_id": task_id}
                if status == "completed":
                    event.update(result=snapshot.get("result"), progress=100, current_stage="completed")
                elif status == "failed":
                    event["error"] = snapshot.get("error")
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") in {"done", "cancelled", "error"}:
                        break
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": keepalive\n\n"
        finally:
            service.unsubscribe(task_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
