"""安全全量重建向量索引的 Celery 任务。"""

from __future__ import annotations

from typing import Any

from app.db.session import SessionLocal
from app.services.reindex_service import ReindexService
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.reindex_worker.reindex_collection_task")
def reindex_collection_task(
    *,
    target_collection: str,
    batch_size: int = 128,
) -> dict[str, Any]:
    """用真实 embedding 将当前有效 child chunks 写入显式的新 collection。"""
    db = SessionLocal()
    try:
        service = ReindexService.from_db(db, target_collection=target_collection)
        return service.rebuild(target_collection, batch_size=batch_size)
    finally:
        db.close()
