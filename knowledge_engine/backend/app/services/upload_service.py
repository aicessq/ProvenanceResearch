"""上传领域服务。

Phase 2 负责把“上传一个新文档”落地为：
- 基础校验
- file_hash 计算
- 本地原始文件保存
- document / version / ingest_task 创建
- Celery 任务投递

本阶段不实现解析、清洗、切分、索引或问答逻辑。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.ingest_task import IngestTask
from app.services.ingest_task_service import mark_dispatch_failed, mark_dispatch_succeeded
from app.services.storage_service import LocalStorageService, StorageError
from app.utils.hash_utils import calculate_file_hash

logger = logging.getLogger(__name__)
settings = get_settings()


class UploadValidationError(ValueError):
    """上传请求不合法。"""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(slots=True)
class UploadResult:
    """上传成功后的核心返回结果。"""

    document_id: uuid.UUID
    version_id: uuid.UUID
    task_id: uuid.UUID
    status: str


def parse_string_list(raw_value: str | None) -> list[str]:
    """把逗号分隔字符串解析成列表。"""
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


async def read_upload_bytes(upload_file: UploadFile) -> bytes:
    """读取上传文件原始 bytes。"""
    return await upload_file.read()


def validate_upload_file(upload_file: UploadFile, file_bytes: bytes) -> None:
    """校验上传文件的基础合法性。"""
    filename = upload_file.filename or ""
    suffix = Path(filename).suffix.lower()
    content_type = (upload_file.content_type or "").lower()

    if not filename:
        raise UploadValidationError("invalid_request", "上传文件不能为空", {"field": "file"})
    if not file_bytes:
        raise UploadValidationError("invalid_request", "上传文件不能为空", {"field": "file"})
    if suffix not in settings.allowed_upload_extensions:
        raise UploadValidationError(
            "unsupported_file_type",
            "暂不支持该文件扩展名",
            {"filename": filename, "extension": suffix},
        )
    if content_type and content_type not in settings.allowed_upload_mime_types:
        raise UploadValidationError(
            "unsupported_file_type",
            "暂不支持该文件 MIME 类型",
            {"filename": filename, "content_type": content_type},
        )

    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(file_bytes) > max_size_bytes:
        raise UploadValidationError(
            "invalid_request",
            "上传文件超过大小限制",
            {"max_upload_size_mb": settings.max_upload_size_mb},
        )


def dispatch_ingest_task(
    *,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    task_id: uuid.UUID,
    file_path: str,
    celery_task_id: str,
) -> None:
    """使用预生成的消息 ID 投递 Celery 入库任务。"""
    from app.workers.ingest_worker import ingest_document_task

    ingest_document_task.apply_async(
        kwargs={
            "document_id": str(document_id),
            "version_id": str(version_id),
            "task_id": str(task_id),
            "file_path": file_path,
        },
        task_id=celery_task_id,
    )


async def process_upload(
    *,
    db: Session,
    upload_file: UploadFile,
    title: str,
    doc_type: str,
    security_domain: list[str] | None = None,
    tags: list[str] | None = None,
    publish_date: date | None = None,
    effective_date: date | None = None,
    version_status: str = "active",
    storage_service: LocalStorageService | None = None,
) -> UploadResult:
    """执行完整的 Phase 2 上传流程。"""
    if not title.strip():
        raise UploadValidationError("invalid_request", "title 不能为空", {"field": "title"})
    if not doc_type.strip():
        raise UploadValidationError("invalid_request", "doc_type 不能为空", {"field": "doc_type"})

    file_bytes = await read_upload_bytes(upload_file)
    validate_upload_file(upload_file, file_bytes)

    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    task_id = uuid.uuid4()

    service = storage_service or LocalStorageService()
    file_hash = calculate_file_hash(file_bytes)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:file_hash, 0))"), {"file_hash": file_hash})
    duplicate = db.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.file_hash == file_hash)
        .where(Document.status == "active")
        .limit(1)
    ).first()
    if duplicate is not None:
        existing_version, existing_document = duplicate
        raise UploadValidationError(
            "duplicate_document",
            "相同内容的文档已存在",
            {
                "document_id": str(existing_document.id),
                "version_id": str(existing_version.id),
                "title": existing_document.title,
            },
        )
    saved_path: Path | None = None
    records_committed = False

    try:
        saved_path = service.save_file(
            document_id=document_id,
            version_id=version_id,
            original_filename=upload_file.filename or "upload.bin",
            file_bytes=file_bytes,
        )

        document = Document(
            id=document_id,
            title=title.strip(),
            doc_type=doc_type.strip(),
            source_filename=service.sanitize_filename(upload_file.filename or "upload.bin"),
            storage_path=str(saved_path),
            status="active",
            security_domain=security_domain or [],
            tags=tags or [],
            current_version_id=None,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_no=1,
            file_hash=file_hash,
            file_size=len(file_bytes),
            mime_type=(upload_file.content_type or "application/octet-stream").lower(),
            storage_path=str(saved_path),
            version_status=version_status,
            publish_date=publish_date,
            effective_date=effective_date,
        )
        ingest_task = IngestTask(
            id=task_id,
            document_id=document_id,
            version_id=version_id,
            task_type="ingest",
            status="queued",
            dispatch_status="pending",
            progress=0,
            message="Phase 2：文件已接收，等待异步入库入口处理",
        )

        db.add(document)
        db.add(version)
        db.add(ingest_task)
        db.flush()
        document.current_version_id = version_id
        db.commit()
        records_committed = True

        celery_task_id = str(uuid.uuid4())
        try:
            dispatch_ingest_task(
                document_id=document_id,
                version_id=version_id,
                task_id=task_id,
                file_path=str(saved_path),
                celery_task_id=celery_task_id,
            )
        except Exception as exc:
            db.rollback()
            mark_dispatch_failed(
                db,
                task_id,
                exc,
                celery_task_id=celery_task_id,
                message="文件已保留，但异步入库任务投递失败",
            )
            document = db.get(Document, document_id)
            version = db.get(DocumentVersion, version_id)
            if document is not None and document.current_version_id == version_id:
                document.current_version_id = None
            if version is not None:
                version.version_status = "draft"
            db.commit()
            logger.exception("上传任务投递失败: task_id=%s", task_id)
            raise
        mark_dispatch_succeeded(db, task_id, celery_task_id)
        return UploadResult(
            document_id=document_id,
            version_id=version_id,
            task_id=task_id,
            status="queued",
        )
    except UploadValidationError:
        raise
    except StorageError:
        raise
    except Exception as exc:  # noqa: BLE001 - 路由层需要统一错误处理
        db.rollback()
        if saved_path is not None and not records_committed:
            service.delete_file(saved_path)
        logger.exception("上传流程失败: %s", exc)
        raise
