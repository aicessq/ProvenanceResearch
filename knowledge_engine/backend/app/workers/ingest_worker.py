"""异步文档入库与替换 Celery 任务。"""

from __future__ import annotations

import logging
import socket
from uuid import UUID

from app.db.session import SessionLocal
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.services.chunk_service import build_chunk_records, generate_chunks
from app.services.cleaner_service import clean_parsed_document
from app.services.index_service import IndexService
from app.services.ingest_task_service import claim, complete, fail, heartbeat
from app.services.parser_service import parse_document
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _worker_id(bound_task) -> str:
    request = getattr(bound_task, "request", None)
    return getattr(request, "hostname", None) or socket.gethostname()


def _heartbeat(task_id: UUID, attempt_token: UUID) -> bool:
    """使用独立事务刷新租约，避免提交正在进行的业务事务。"""
    heartbeat_db = SessionLocal()
    try:
        return heartbeat(heartbeat_db, task_id, attempt_token)
    finally:
        heartbeat_db.close()


def _failed_result(document_id: str, version_id: str, task_id: str, *, replace: bool = False) -> dict[str, str | int]:
    result: dict[str, str | int] = {
        "document_id": document_id,
        "version_id": version_id,
        "task_id": task_id,
        "status": "failed",
        "indexed_chunk_count": 0,
    }
    if replace:
        result.update(added=0, removed=0, unchanged=0)
    else:
        result.update(page_count=0, chunk_count=0)
    return result


@celery_app.task(bind=True, name="app.workers.ingest_worker.ingest_document_task")
def ingest_document_task(self, *, document_id: str, version_id: str, task_id: str, file_path: str) -> dict[str, str | int]:
    """领取并执行文档解析、切分、持久化和索引。"""
    db = SessionLocal()
    token = None
    task_uuid = None
    try:
        task_uuid = UUID(task_id)
        token = claim(db, task_uuid, _worker_id(self))
        if token is None:
            logger.info("入库任务无需执行（终态、已领取或不存在）: task_id=%s", task_id)
            return {"document_id": document_id, "version_id": version_id, "task_id": task_id, "status": "noop", "page_count": 0, "chunk_count": 0, "indexed_chunk_count": 0}

        document = db.get(Document, UUID(document_id))
        version = db.get(DocumentVersion, UUID(version_id))
        if document is None or version is None:
            raise ValueError("document 或 version 不存在，无法执行入库任务")

        parsed_document = parse_document(file_path, title=document.title)
        if not _heartbeat(task_uuid, token):
            raise RuntimeError("任务租约已失效")
        cleaned_document = clean_parsed_document(parsed_document)
        if not _heartbeat(task_uuid, token):
            raise RuntimeError("任务租约已失效")
        chunk_drafts = generate_chunks(
            document=cleaned_document,
            doc_type=document.doc_type,
            document_id=document_id,
            version_id=version_id,
            file_hash=version.file_hash,
            doc_title=document.title,
        )
        if not chunk_drafts:
            raise ValueError("切分结果为空，无法写入 chunk")
        if not _heartbeat(task_uuid, token):
            raise RuntimeError("任务租约已失效")

        existing_chunks = db.query(Chunk).filter(Chunk.version_id == UUID(version_id)).all()
        for chunk in existing_chunks:
            db.delete(chunk)
        db.flush()
        chunk_records = build_chunk_records(
            drafts=chunk_drafts,
            document_id=document.id,
            version_id=version.id,
            doc_type=document.doc_type,
            doc_title=document.title,
            security_domain=document.security_domain,
        )
        persisted_chunks = [Chunk(**record) for record in chunk_records]
        db.add_all(persisted_chunks)
        db.flush()
        if not _heartbeat(task_uuid, token):
            raise RuntimeError("任务租约已失效")

        index_result = IndexService.from_db(db).build_chunk_indexes(
            persisted_chunks, version=version
        )
        db.commit()
        if not _heartbeat(task_uuid, token):
            raise RuntimeError("任务租约已失效")
        if not complete(
            db,
            task_uuid,
            token,
            "Phase 5：解析、清洗、切分、chunk 落库与 child chunk 索引已完成",
        ):
            raise RuntimeError("任务租约已失效，完成状态未写入")
        return {
            "document_id": document_id,
            "version_id": version_id,
            "task_id": task_id,
            "status": "completed",
            "page_count": len(cleaned_document.pages),
            "chunk_count": len(chunk_records),
            "indexed_chunk_count": index_result.indexed_chunk_count,
        }
    except Exception as exc:  # noqa: BLE001 - 最外层必须补偿业务状态
        db.rollback()
        logger.exception("入库任务执行失败: task_id=%s attempt_token=%s", task_id, token)
        if task_uuid is not None and token is not None:
            fail(db, task_uuid, token, "ingest_failed", str(exc))
        return _failed_result(document_id, version_id, task_id)
    finally:
        db.close()


@celery_app.task(bind=True, name="app.workers.ingest_worker.replace_document_task")
def replace_document_task(self, *, document_id: str, version_id: str, task_id: str, file_path: str) -> dict[str, str | int]:
    """领取并执行 replace 增量更新；replace 不由 processing 恢复器自动重跑。"""
    db = SessionLocal()
    token = None
    task_uuid = None
    try:
        task_uuid = UUID(task_id)
        token = claim(db, task_uuid, _worker_id(self))
        if token is None:
            logger.info("replace 任务无需执行（终态、已领取或不存在）: task_id=%s", task_id)
            return {"document_id": document_id, "version_id": version_id, "task_id": task_id, "status": "noop", "added": 0, "removed": 0, "unchanged": 0, "indexed_chunk_count": 0}

        if not _heartbeat(task_uuid, token):
            raise RuntimeError("任务租约已失效")
        from app.services.update_service import apply_incremental_update

        result = apply_incremental_update(db=db, document_id=document_id, version_id=version_id, file_path=file_path)
        if not _heartbeat(task_uuid, token):
            raise RuntimeError("任务租约已失效")
        if not complete(db, task_uuid, token, "Phase 9：replace 增量更新已完成"):
            raise RuntimeError("任务租约已失效，完成状态未写入")
        return {
            "document_id": document_id,
            "version_id": version_id,
            "task_id": task_id,
            "status": "completed",
            "added": int(result["added"]),
            "removed": int(result["removed"]),
            "unchanged": int(result["unchanged"]),
            "indexed_chunk_count": int(result["indexed_chunk_count"]),
        }
    except Exception as exc:  # noqa: BLE001 - 最外层必须补偿业务状态
        db.rollback()
        logger.exception("replace 任务执行失败: task_id=%s attempt_token=%s", task_id, token)
        if task_uuid is not None and token is not None:
            fail(db, task_uuid, token, "replace_failed", str(exc))
        return _failed_result(document_id, version_id, task_id, replace=True)
    finally:
        db.close()
