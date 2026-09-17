"""文档上传接口（POST /api/v1/documents/upload）。

Phase 2 只负责接收新文档上传并创建异步入库入口，
不在本阶段实现真实解析、切分、索引流程。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.upload import UploadResponse
from app.services.storage_service import StorageError
from app.services.upload_service import (
    UploadValidationError,
    parse_string_list,
    process_upload,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_type: str = Form(...),
    security_domain: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    publish_date: date | None = Form(default=None),
    effective_date: date | None = Form(default=None),
    version_status: str = Form(default="active"),
    document_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """上传一个新文档并创建异步入库任务。"""
    if document_id is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_request",
                    "message": "upload 接口不允许传入 document_id；新版本创建请使用 replace 接口",
                    "details": {"field": "document_id"},
                }
            },
        )

    try:
        result = await process_upload(
            db=db,
            upload_file=file,
            title=title,
            doc_type=doc_type,
            security_domain=parse_string_list(security_domain),
            tags=parse_string_list(tags),
            publish_date=publish_date,
            effective_date=effective_date,
            version_status=version_status,
        )
        return UploadResponse(
            document_id=result.document_id,
            version_id=result.version_id,
            task_id=result.task_id,
            status=result.status,
        )
    except UploadValidationError as exc:
        if exc.code == "unsupported_file_type":
            status_code = 415
        elif exc.code == "duplicate_document":
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "internal_error",
                    "message": str(exc),
                    "details": {},
                }
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转换为结构化错误响应
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "internal_error",
                    "message": "上传失败，请稍后重试",
                    "details": {"reason": str(exc)},
                }
            },
        ) from exc
