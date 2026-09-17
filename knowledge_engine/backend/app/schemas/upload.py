"""upload 相关 Pydantic schema。"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """上传成功响应。"""

    document_id: UUID
    version_id: UUID
    task_id: UUID
    status: str = Field(default="queued")


class UploadRequestMeta(BaseModel):
    """上传请求中的结构化元数据。"""

    title: str
    doc_type: str
    security_domain: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    publish_date: date | None = None
    effective_date: date | None = None
    version_status: str = Field(default="active")
