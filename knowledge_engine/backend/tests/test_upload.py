"""Phase 2 上传接口测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.ingest_task import IngestTask
from app.services import upload_service
from app.dependencies import get_db
from app.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture()
def upload_client(db_session, monkeypatch, tmp_path) -> TestClient:
    """返回绑定真实数据库会话、但拦截 Celery 投递的测试客户端。"""
    settings = get_settings()
    original_storage_root = settings.storage_root
    settings.storage_root = tmp_path / "storage"

    dispatched: list[dict[str, str]] = []

    def fake_dispatch_ingest_task(**kwargs) -> None:
        dispatched.append(kwargs)

    monkeypatch.setattr(upload_service, "dispatch_ingest_task", fake_dispatch_ingest_task)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        client._dispatched_tasks = dispatched  # type: ignore[attr-defined]
        yield client
    finally:
        app.dependency_overrides.clear()
        settings.storage_root = original_storage_root


def test_upload_pdf_success(upload_client: TestClient, db_session) -> None:
    response = upload_client.post(
        "/api/v1/documents/upload",
        data={
            "title": "中华人民共和国网络安全法",
            "doc_type": "law",
            "security_domain": "compliance,law",
            "tags": "regulation,phase2",
        },
        files={"file": ("law.pdf", b"%PDF-1.4\nphase2 test pdf", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["document_id"]
    assert body["version_id"]
    assert body["task_id"]

    document = db_session.get(Document, body["document_id"])
    version = db_session.get(DocumentVersion, body["version_id"])
    ingest_task = db_session.get(IngestTask, body["task_id"])

    assert document is not None
    assert version is not None
    assert ingest_task is not None
    assert version.version_no == 1
    assert ingest_task.status == "queued"

    stored_path = Path(document.storage_path)
    assert stored_path.exists()
    assert body["document_id"] in str(stored_path)
    assert body["version_id"] in str(stored_path)

    dispatched = upload_client._dispatched_tasks  # type: ignore[attr-defined]
    assert len(dispatched) == 1
    assert str(dispatched[0]["document_id"]) == body["document_id"]
    assert str(dispatched[0]["version_id"]) == body["version_id"]
    assert str(dispatched[0]["task_id"]) == body["task_id"]


def test_upload_rejects_duplicate_file_hash_with_existing_document_info(upload_client: TestClient) -> None:
    payload = {
        "data": {"title": "重复文档", "doc_type": "law"},
        "files": {"file": ("same.txt", b"same-content", "text/plain")},
    }
    first = upload_client.post("/api/v1/documents/upload", **payload)
    second = upload_client.post("/api/v1/documents/upload", **payload)

    assert first.status_code == 200
    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "duplicate_document"
    assert error["details"]["document_id"] == first.json()["document_id"]


def test_upload_rejects_unsupported_file_type(upload_client: TestClient) -> None:
    response = upload_client.post(
        "/api/v1/documents/upload",
        data={"title": "恶意二进制", "doc_type": "other"},
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "unsupported_file_type"


def test_upload_rejects_document_id_parameter(upload_client: TestClient) -> None:
    response = upload_client.post(
        "/api/v1/documents/upload",
        data={
            "title": "测试文档",
            "doc_type": "note",
            "document_id": "123",
        },
        files={"file": ("note.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


def test_upload_requires_title(upload_client: TestClient) -> None:
    response = upload_client.post(
        "/api/v1/documents/upload",
        data={"doc_type": "note"},
        files={"file": ("note.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 422
