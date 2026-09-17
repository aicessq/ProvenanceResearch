"""Phase 9 `/documents/{id}/replace` API 测试。"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


class FakeReplaceResult:
    def __init__(self) -> None:
        self.document_id = uuid.uuid4()
        self.version_id = uuid.uuid4()
        self.task_id = uuid.uuid4()
        self.status = "queued"


@pytest.mark.anyio
async def test_document_replace_api_returns_queued_result(client, monkeypatch) -> None:
    async def fake_process_replace(*, db, document_id, upload_file, version_status="active", change_summary=None):
        return FakeReplaceResult()

    monkeypatch.setattr("app.api.documents.process_replace", fake_process_replace)

    response = client.post(
        f"/api/v1/documents/{uuid.uuid4()}/replace",
        files={"file": ("sample.txt", b"new content", "text/plain")},
        data={"version_status": "active", "change_summary": "修订版本"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["document_id"]
    assert payload["version_id"]
    assert payload["task_id"]


@pytest.mark.anyio
async def test_document_replace_api_returns_file_unchanged_error(client, monkeypatch) -> None:
    from app.services.update_service import FileUnchangedError

    async def fake_process_replace(*, db, document_id, upload_file, version_status="active", change_summary=None):
        raise FileUnchangedError("新文件与当前版本内容一致，无需创建新版本")

    monkeypatch.setattr("app.api.documents.process_replace", fake_process_replace)

    response = client.post(
        f"/api/v1/documents/{uuid.uuid4()}/replace",
        files={"file": ("sample.txt", b"same content", "text/plain")},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"]["code"] == "file_unchanged"
