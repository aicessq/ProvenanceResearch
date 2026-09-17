"""Celery 应用定义。

Phase 2 仅建立异步任务入口配置，不在这里提前实现后续解析/索引逻辑。
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "cybersec_rag_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.ingest_worker",
        "app.workers.recovery_worker",
        "app.workers.reindex_worker",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    # Phase D 幂等验收前不启用 late ack / worker-lost 重投，避免重复外部索引副作用。
    task_acks_late=False,
    task_reject_on_worker_lost=False,
    beat_schedule={
        "recover-stale-ingest-tasks": {
            "task": "app.workers.recovery_worker.recover_stale_tasks",
            "schedule": settings.task_recovery_interval_seconds,
        }
    },
)
