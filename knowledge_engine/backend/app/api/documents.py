"""文档替换与删除接口。

Phase 9 开始补齐：
- `/documents/{document_id}/replace`
- `DELETE /documents/{document_id}`
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentReplaceResponse,
    DocumentTaskResponse,
)
from app.services.crud_service import get_ingest_task as fetch_ingest_task
from app.services.storage_service import StorageError
from app.services.update_service import (
    DocumentNotFoundError,
    FileUnchangedError,
    UpdateServiceError,
    process_replace,
    soft_delete_document,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/tasks/{task_id}", response_model=DocumentTaskResponse)
def get_document_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DocumentTaskResponse:
    """查询持久化的入库或替换任务状态。"""
    task = fetch_ingest_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "任务不存在",
                    "details": {"task_id": str(task_id)},
                }
            },
        )
    return DocumentTaskResponse(
        id=str(task.id),
        document_id=str(task.document_id),
        version_id=str(task.version_id),
        task_type=task.task_type,
        status=task.status,
        message=task.message,
        error_message=task.error_message,
        progress=task.progress,
        celery_task_id=task.celery_task_id,
        dispatch_status=task.dispatch_status,
        dispatched_at=task.dispatched_at,
        attempt_count=task.attempt_count,
        recovery_count=task.recovery_count,
        worker_id=task.worker_id,
        attempt_token=str(task.attempt_token) if task.attempt_token else None,
        last_heartbeat_at=task.last_heartbeat_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        finished_at=task.finished_at,
    )


@router.post("/{document_id}/replace", response_model=DocumentReplaceResponse)
async def replace_document(
    document_id: str,
    file: UploadFile = File(...),
    version_status: str = Form(default="active"),
    change_summary: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> DocumentReplaceResponse:
    """为已有 document 创建新版本。"""
    try:
        result = await process_replace(
            db=db,
            document_id=document_id,
            upload_file=file,
            version_status=version_status,
            change_summary=change_summary,
        )
        return DocumentReplaceResponse(
            document_id=str(result.document_id),
            version_id=str(result.version_id),
            task_id=str(result.task_id),
            status=result.status,
        )
    except FileUnchangedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "file_unchanged",
                    "message": str(exc),
                    "details": {"document_id": document_id},
                }
            },
        ) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "not_found",
                    "message": str(exc),
                    "details": {"document_id": document_id},
                }
            },
        ) from exc
    except (UpdateServiceError, StorageError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_request",
                    "message": str(exc),
                    "details": {},
                }
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "internal_error",
                    "message": "replace 失败，请稍后重试",
                    "details": {"reason": str(exc)},
                }
            },
        ) from exc


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
) -> DocumentDeleteResponse:
    """软删除 document，并同步关闭检索可见性。"""
    try:
        result = soft_delete_document(db=db, document_id=document_id)
        return DocumentDeleteResponse(
            document_id=str(result.document_id),
            status=result.status,
            deactivated_chunk_count=result.deactivated_chunk_count,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "not_found",
                    "message": str(exc),
                    "details": {"document_id": document_id},
                }
            },
        ) from exc
    except UpdateServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_request",
                    "message": str(exc),
                    "details": {},
                }
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "internal_error",
                    "message": "删除失败，请稍后重试",
                    "details": {"reason": str(exc)},
                }
            },
        ) from exc
