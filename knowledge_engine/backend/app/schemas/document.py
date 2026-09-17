"""document 相关 Pydantic schema。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class DocumentTaskResponse(BaseModel):
    """数据库任务状态响应，仅包含当前模型已有字段。"""

    id: str
    document_id: str
    version_id: str
    task_type: str
    status: str
    message: str | None
    error_message: str | None
    progress: int
    celery_task_id: str | None = None
    dispatch_status: str = "pending"
    dispatched_at: dt.datetime | None = None
    attempt_count: int = 0
    recovery_count: int = 0
    worker_id: str | None = None
    attempt_token: str | None = None
    last_heartbeat_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    finished_at: dt.datetime | None


class DocumentReplaceResponse(BaseModel):
    """Phase 9 replace 接口响应。"""

    document_id: str
    version_id: str
    task_id: str
    status: str


class DocumentDeleteResponse(BaseModel):
    """Phase 9 soft delete 接口响应。"""

    document_id: str
    status: str
    deactivated_chunk_count: int
