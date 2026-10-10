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
from app.services.cloud_config_service import (
    CAPABILITIES,
    CloudConfigService,
    ConfigValidationError,
)
from app.services.config_secrets import ConfigEncryptionError
from app.services.sse_v1 import SseV1Error, format_sse

router = APIRouter(prefix="/v1", tags=["research-v1"])

_service: AgenticTaskService | None = None
_config_service: CloudConfigService | None = None

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


def get_config_service() -> CloudConfigService:
    global _config_service
    if _config_service is None:
        _config_service = CloudConfigService()
    return _config_service


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


# ---------------- 云服务配置（P5：凭证加密存储 + 出站逐能力授权） ----------------


def _config_problem(exc: Exception) -> V1Problem:
    if isinstance(exc, ConfigEncryptionError):
        return V1Problem(status=503, code="config_encryption", detail=str(exc))
    if isinstance(exc, ConfigValidationError):
        status = 403 if exc.code == "endpoint_not_allowed" else 422
        return V1Problem(status=status, code=exc.code, detail=exc.message)
    return V1Problem(status=500, code="internal_error", detail=f"{type(exc).__name__}: {exc}"[:200])


@router.get("/config")
async def get_cloud_config():
    """云服务配置总览：凭证只回 configured/missing（密钥永不进 GET/日志）。"""
    return get_config_service().view()


@router.put("/config/{capability}")
async def update_cloud_config(capability: str, payload: dict):
    """保存运行时覆盖（先验后写：校验失败保留旧值）。api_key 只进加密库。"""
    service = get_config_service()
    try:
        return service.update_capability(capability, payload)
    except (ConfigValidationError, ConfigEncryptionError) as exc:
        raise _config_problem(exc)


@router.delete("/config/{capability}")
async def remove_cloud_config(capability: str):
    """删除运行时覆盖，恢复环境值。"""
    service = get_config_service()
    try:
        return service.remove_override(capability)
    except ConfigValidationError as exc:
        raise _config_problem(exc)


@router.post("/config/{capability}/test")
async def test_cloud_config(capability: str, payload: dict | None = None):
    """配置验证：静态校验必做；live 探测需显式 confirm_fingerprint（明确授权本次外送）。

    probe=true 且 confirm_fingerprint 与当前配置指纹一致时才发起最小 live 调用；
    凭证不等于授权——未确认指纹绝不外送（design.md §9）。
    """
    service = get_config_service()
    body = payload or {}
    try:
        cfg = service.resolve(capability)
        masked = service._mask(capability)
    except ConfigValidationError as exc:
        raise _config_problem(exc)

    if not (body.get("probe") is True):
        return {"capability": capability, "validation": "static_ok", "config": masked}

    outbound = service.outbound_view()["capabilities"][capability]
    confirm = str(body.get("confirm_fingerprint") or "")
    if confirm != outbound["fingerprint"]:
        raise V1Problem(
            status=409,
            code="cloud_upload_not_authorized",
            detail="live 探测会向云端外送数据；需 confirm_fingerprint 与当前配置指纹一致（凭证不等于授权）",
        )

    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            resp = await client.post(
                f"{cfg['base_url'].rstrip('/')}/chat/completions",
                json={"model": cfg["model"], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
        ok = resp.status_code == 200
        return {
            "capability": capability,
            "validation": "probe_ok" if ok else "probe_failed",
            "http_status": resp.status_code,
            "config": masked,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "capability": capability,
            "validation": "probe_failed",
            "error": f"{type(exc).__name__}",
            "config": masked,
        }


@router.put("/config/outbound/{capability}")
async def approve_outbound(capability: str):
    """登记当前配置指纹为该能力出站授权（provider/endpoint/model 变更后旧授权自动失效）。"""
    service = get_config_service()
    try:
        return service.approve_outbound(capability)
    except ConfigValidationError as exc:
        raise _config_problem(exc)


@router.post("/config/rotate-key")
async def rotate_master_key(payload: dict):
    """主密钥轮换：先全量重加密并验证可解再替换；失败保留旧密文。

    轮换成功后必须同步更新启动环境的 CONFIG_ENCRYPTION_KEY，否则重启后不可解。
    """
    service = get_config_service()
    new_key = str((payload or {}).get("new_key") or "")
    try:
        count = service.rotate_master_key(new_key)
    except ConfigEncryptionError as exc:
        raise V1Problem(status=503, code="config_encryption", detail=str(exc))
    return {"rotated": count, "note": "请同步更新启动环境 CONFIG_ENCRYPTION_KEY 为新主密钥"}
