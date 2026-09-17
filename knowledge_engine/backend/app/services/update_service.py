"""文档更新服务。

Phase 9 负责把知识库从“一次性上传入库”升级为“支持 replace / soft delete / chunk diff / 增量复用”。
本模块只实现当前阶段所需的更新边界，不提前实现自动同步或全库重建。
"""

from __future__ import annotations

from collections import defaultdict
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.ingest_task import IngestTask
from app.services.chunk_service import build_chunk_records, generate_chunks
from app.services.cleaner_service import clean_parsed_document
from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.services.ingest_task_service import mark_dispatch_failed, mark_dispatch_succeeded
from app.services.index_service import IndexService
from app.services.keyword_store import KeywordStore
from app.services.parser_service import parse_document
from app.services.storage_service import LocalStorageService
from app.services.upload_service import UploadValidationError, read_upload_bytes, validate_upload_file
from app.services.vector_store import QdrantVectorStore, VectorPoint
from app.utils.hash_utils import calculate_file_hash

logger = logging.getLogger(__name__)


class UpdateServiceError(RuntimeError):
    """Phase 9 更新流程异常。"""


class DocumentNotFoundError(UpdateServiceError):
    """目标文档不存在。"""


class FileUnchangedError(UpdateServiceError):
    """replace 文件内容未变化。"""


@dataclass(slots=True)
class ReplaceResult:
    """replace 接口成功后的返回结果。"""

    document_id: uuid.UUID
    version_id: uuid.UUID
    task_id: uuid.UUID
    status: str


@dataclass(slots=True)
class DeleteResult:
    """软删除接口返回结果。"""

    document_id: uuid.UUID
    status: str
    deactivated_chunk_count: int


@dataclass(slots=True)
class ChunkDiffResult:
    """child chunk diff 结果。"""

    added: list[dict[str, object]] = field(default_factory=list)
    removed: list[Chunk] = field(default_factory=list)
    unchanged: list[tuple[Chunk, dict[str, object]]] = field(default_factory=list)


async def process_replace(
    *,
    db: Session,
    document_id: str,
    upload_file: UploadFile,
    version_status: str = "active",
    change_summary: str | None = None,
    storage_service: LocalStorageService | None = None,
) -> ReplaceResult:
    """执行 replace：为已有 document 创建新版本。"""
    target_document = db.get(Document, uuid.UUID(document_id))
    if target_document is None:
        raise DocumentNotFoundError("document 不存在")
    if target_document.status != "active":
        raise UpdateServiceError("document 已删除或不可见，不能执行 replace")
    if target_document.current_version_id is None:
        raise UpdateServiceError("document 当前没有可替换的 active version")

    current_version = db.get(DocumentVersion, target_document.current_version_id)
    if current_version is None:
        raise UpdateServiceError("document current_version 不存在")

    file_bytes = await read_upload_bytes(upload_file)
    validate_upload_file(upload_file, file_bytes)
    new_file_hash = calculate_file_hash(file_bytes)
    if new_file_hash == current_version.file_hash:
        raise FileUnchangedError("新文件与当前版本内容一致，无需创建新版本")

    service = storage_service or LocalStorageService()
    new_version_id = uuid.uuid4()
    task_id = uuid.uuid4()
    file_path = service.save_file(
        document_id=target_document.id,
        version_id=new_version_id,
        original_filename=upload_file.filename or target_document.source_filename,
        file_bytes=file_bytes,
    )

    next_version_no = _get_next_version_no(db, target_document.id)
    new_version = DocumentVersion(
        id=new_version_id,
        document_id=target_document.id,
        version_no=next_version_no,
        file_hash=new_file_hash,
        file_size=len(file_bytes),
        mime_type=(upload_file.content_type or "application/octet-stream").lower(),
        storage_path=str(file_path),
        version_status=version_status,
        publish_date=current_version.publish_date,
        effective_date=current_version.effective_date,
        change_summary=change_summary,
    )
    task = IngestTask(
        id=task_id,
        document_id=target_document.id,
        version_id=new_version_id,
        task_type="replace",
        status="queued",
        dispatch_status="pending",
        progress=0,
        message="Phase 9：新版本已接收，等待增量更新任务处理",
    )
    db.add(new_version)
    db.add(task)
    db.commit()

    celery_task_id = str(uuid.uuid4())
    try:
        dispatch_update_task(
            document_id=target_document.id,
            version_id=new_version_id,
            task_id=task_id,
            file_path=str(file_path),
            celery_task_id=celery_task_id,
        )
    except Exception as exc:
        db.rollback()
        mark_dispatch_failed(
            db,
            task_id,
            exc,
            celery_task_id=celery_task_id,
            message="replace 源文件已保留，但异步任务投递失败",
        )
        new_version = db.get(DocumentVersion, new_version_id)
        if new_version is not None:
            new_version.version_status = "draft"
            db.commit()
        raise
    mark_dispatch_succeeded(db, task_id, celery_task_id)
    return ReplaceResult(
        document_id=target_document.id,
        version_id=new_version_id,
        task_id=task_id,
        status="queued",
    )


def calculate_chunk_diff(old_chunks: list[Chunk], new_child_records: list[dict[str, object]]) -> ChunkDiffResult:
    """基于 child chunk 的 chunk_hash 多重集合做增量 diff，保留重复内容 chunk。"""
    old_by_hash: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in old_chunks:
        if chunk.chunk_type == "child":
            old_by_hash[str(chunk.chunk_hash)].append(chunk)

    new_by_hash: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in new_child_records:
        if record.get("chunk_type") == "child":
            new_by_hash[str(record["chunk_hash"])].append(record)

    added: list[dict[str, object]] = []
    removed: list[Chunk] = []
    unchanged: list[tuple[Chunk, dict[str, object]]] = []
    for hash_value in old_by_hash.keys() | new_by_hash.keys():
        old_bucket = old_by_hash.get(hash_value, [])
        new_bucket = new_by_hash.get(hash_value, [])
        common_count = min(len(old_bucket), len(new_bucket))
        unchanged.extend(zip(old_bucket[:common_count], new_bucket[:common_count], strict=True))
        removed.extend(old_bucket[common_count:])
        added.extend(new_bucket[common_count:])

    return ChunkDiffResult(added=added, removed=removed, unchanged=unchanged)


def apply_incremental_update(
    *,
    db: Session,
    document_id: str,
    version_id: str,
    file_path: str,
    embedding_service: EmbeddingService | None = None,
    vector_store: QdrantVectorStore | None = None,
) -> dict[str, int | str]:
    """对 replace 的新版本执行 chunk diff、最小持久化与索引复用。"""
    document = db.get(Document, uuid.UUID(document_id))
    version = db.get(DocumentVersion, uuid.UUID(version_id))
    if document is None or version is None:
        raise UpdateServiceError("document 或 version 不存在")

    current_version = db.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    if current_version is None:
        raise UpdateServiceError("document 当前版本不存在，无法执行增量更新")

    parsed_document = parse_document(file_path, title=document.title)
    cleaned_document = clean_parsed_document(parsed_document)
    chunk_drafts = generate_chunks(
        document=cleaned_document,
        doc_type=document.doc_type,
        document_id=document_id,
        version_id=version_id,
        file_hash=version.file_hash,
        doc_title=document.title,
    )
    new_chunk_records = build_chunk_records(
        drafts=chunk_drafts,
        document_id=document.id,
        version_id=version.id,
        doc_type=document.doc_type,
        doc_title=document.title,
        security_domain=document.security_domain,
    )

    old_child_chunks = db.execute(
        select(Chunk)
        .where(Chunk.version_id == current_version.id)
        .where(Chunk.chunk_type == "child")
        .where(Chunk.is_active.is_(True))
    ).scalars().all()
    diff = calculate_chunk_diff(old_child_chunks, new_chunk_records)

    persisted_chunks: list[Chunk] = []
    for record in new_chunk_records:
        chunk = Chunk(**record)
        db.add(chunk)
        persisted_chunks.append(chunk)
    db.flush()

    added_record_ids = {id(record) for record in diff.added}
    added_chunks = [chunk for chunk, record in zip(persisted_chunks, new_chunk_records, strict=True) if id(record) in added_record_ids]
    new_chunks_by_hash: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in persisted_chunks:
        if chunk.chunk_type == "child":
            new_chunks_by_hash[str(chunk.chunk_hash)].append(chunk)
    unchanged_pairs: list[tuple[Chunk, Chunk]] = []
    for old_chunk, record in diff.unchanged:
        bucket = new_chunks_by_hash.get(str(record["chunk_hash"]), [])
        if bucket:
            unchanged_pairs.append((old_chunk, bucket.pop(0)))

    resolved_embedding = embedding_service or get_embedding_service()
    resolved_vector_store = vector_store or QdrantVectorStore.from_settings()
    resolved_vector_store.expected_embedding_identity = resolved_embedding.identity
    resolved_vector_store.validate_embedding_identity()
    keyword_store = KeywordStore.from_db(db)
    index_service = IndexService(
        embedding_service=resolved_embedding,
        vector_store=resolved_vector_store,
        keyword_store=keyword_store,
    )

    added_index_result = index_service.build_chunk_indexes(added_chunks, version=version) if added_chunks else None
    reused_count = reuse_unchanged_child_vectors(
        vector_store=resolved_vector_store,
        old_to_new=unchanged_pairs,
        version=version,
    )
    keyword_store.update_child_chunk_search_vectors([new_chunk.id for _old_chunk, new_chunk in unchanged_pairs])

    old_superseded_ids = [old_chunk.id for old_chunk, _new_chunk in unchanged_pairs]
    removed_ids = [chunk.id for chunk in diff.removed]
    old_invisible_ids = removed_ids + old_superseded_ids
    if old_invisible_ids:
        for chunk in [*diff.removed, *(old_chunk for old_chunk, _new_chunk in unchanged_pairs)]:
            chunk.is_active = False
            chunk.search_tsv = None
        keyword_store.deactivate_chunks(old_invisible_ids)
        resolved_vector_store.set_chunks_active(old_invisible_ids, is_active=False)
        resolved_vector_store.set_chunks_current_version(old_invisible_ids, is_current_version=False)

    if current_version.version_status == "active":
        current_version.version_status = "amended"
    document.current_version_id = version.id
    document.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "added": len(diff.added),
        "removed": len(diff.removed),
        "unchanged": len(diff.unchanged),
        "vector_reused": reused_count,
        "indexed_chunk_count": added_index_result.indexed_chunk_count if added_index_result else 0,
    }


def reuse_unchanged_child_vectors(
    *,
    vector_store: QdrantVectorStore,
    old_to_new: list[tuple[Chunk, Chunk]],
    version: DocumentVersion,
) -> int:
    """为 unchanged child chunk 复用旧向量，避免重新 embedding。"""
    if not old_to_new:
        return 0

    old_points = vector_store.get_chunks_by_ids([old_chunk.id for old_chunk, _new_chunk in old_to_new])
    old_point_map = {str(getattr(point, "id", "")): point for point in old_points}
    points_to_upsert: list[VectorPoint] = []
    for old_chunk, new_chunk in old_to_new:
        point = old_point_map.get(str(old_chunk.id))
        if point is None:
            continue
        payload = IndexService.build_payload(new_chunk, version=version)
        payload["chunk_text"] = new_chunk.text
        vector = list(getattr(point, "vector", []) or [])
        if not vector:
            continue
        points_to_upsert.append(
            VectorPoint(
                chunk_id=str(new_chunk.id),
                vector=vector,
                payload=payload,
            )
        )
    return vector_store.upsert_chunks(points_to_upsert)


def soft_delete_document(
    *,
    db: Session,
    document_id: str,
    vector_store: QdrantVectorStore | None = None,
) -> DeleteResult:
    """软删除 document，并同步关闭检索可见性。"""
    document = db.get(Document, uuid.UUID(document_id))
    if document is None:
        raise DocumentNotFoundError("document 不存在")
    if document.status == "deleted":
        active_chunks = db.execute(select(Chunk).where(Chunk.document_id == document.id)).scalars().all()
        return DeleteResult(document_id=document.id, status="deleted", deactivated_chunk_count=len(active_chunks))

    chunks = db.execute(
        select(Chunk).where(Chunk.document_id == document.id).where(Chunk.is_active.is_(True))
    ).scalars().all()
    chunk_ids = [chunk.id for chunk in chunks]
    indexed_child_ids = [chunk.id for chunk in chunks if chunk.chunk_type == "child"]
    for chunk in chunks:
        chunk.is_active = False
        chunk.search_tsv = None
    document.status = "deleted"
    document.updated_at = datetime.now(timezone.utc)
    db.flush()

    KeywordStore.from_db(db).deactivate_chunks(chunk_ids)
    (vector_store or QdrantVectorStore.from_settings()).set_chunks_active(indexed_child_ids, is_active=False)
    db.commit()
    return DeleteResult(
        document_id=document.id,
        status="deleted",
        deactivated_chunk_count=len(chunk_ids),
    )


def dispatch_update_task(
    *,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    task_id: uuid.UUID,
    file_path: str,
    celery_task_id: str,
) -> None:
    """使用预生成的消息 ID 投递 replace 类型异步更新任务。"""
    from app.workers.ingest_worker import replace_document_task

    replace_document_task.apply_async(
        kwargs={
            "document_id": str(document_id),
            "version_id": str(version_id),
            "task_id": str(task_id),
            "file_path": file_path,
        },
        task_id=celery_task_id,
    )


def _get_next_version_no(db: Session, document_id: uuid.UUID) -> int:
    """获取文档下一个 version_no。"""
    version_numbers = db.execute(
        select(DocumentVersion.version_no).where(DocumentVersion.document_id == document_id)
    ).scalars().all()
    return max(version_numbers, default=0) + 1
