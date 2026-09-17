"""任务状态查询接口快速测试。"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_get_document_task_returns_database_record(client: TestClient, monkeypatch) -> None:
    """接口应返回数据库任务记录中的现有字段。"""
    task_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    created_at = dt.datetime(2026, 8, 4, 1, 2, 3)
    task = SimpleNamespace(
        id=task_id,
        document_id=document_id,
        version_id=version_id,
        task_type="replace",
        status="processing",
        message="正在索引",
        error_message=None,
        progress=60,
        celery_task_id="celery-123",
        dispatch_status="dispatched",
        dispatched_at=created_at,
        attempt_count=1,
        recovery_count=0,
        worker_id="worker@example",
        attempt_token=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        last_heartbeat_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        finished_at=None,
    )
    monkeypatch.setattr("app.api.documents.fetch_ingest_task", lambda db, value: task)

    response = client.get(f"/api/v1/documents/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(task_id),
        "document_id": str(document_id),
        "version_id": str(version_id),
        "task_type": "replace",
        "status": "processing",
        "message": "正在索引",
        "error_message": None,
        "progress": 60,
        "celery_task_id": "celery-123",
        "dispatch_status": "dispatched",
        "dispatched_at": "2026-08-04T01:02:03",
        "attempt_count": 1,
        "recovery_count": 0,
        "worker_id": "worker@example",
        "attempt_token": "12345678-1234-5678-1234-567812345678",
        "last_heartbeat_at": "2026-08-04T01:02:03",
        "created_at": "2026-08-04T01:02:03",
        "updated_at": "2026-08-04T01:02:03",
        "finished_at": None,
    }


def test_get_document_task_returns_not_found(client: TestClient, monkeypatch) -> None:
    """数据库中不存在任务时应返回 404。"""
    task_id = uuid.uuid4()
    monkeypatch.setattr("app.api.documents.fetch_ingest_task", lambda db, value: None)

    response = client.get(f"/api/v1/documents/tasks/{task_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_document_task_rejects_invalid_uuid(client: TestClient) -> None:
    """非法任务 ID 应由路径参数校验拒绝。"""
    response = client.get("/api/v1/documents/tasks/not-a-uuid")

    assert response.status_code == 422
