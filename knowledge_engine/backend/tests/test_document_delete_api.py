"""Phase 9 `DELETE /documents/{id}` API 测试。"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


class FakeDeleteResult:
    def __init__(self) -> None:
        self.document_id = uuid.uuid4()
        self.status = "deleted"
        self.deactivated_chunk_count = 3


def test_document_delete_api_returns_deleted_status(client, monkeypatch) -> None:
    def fake_soft_delete_document(*, db, document_id):
        return FakeDeleteResult()

    monkeypatch.setattr("app.api.documents.soft_delete_document", fake_soft_delete_document)

    response = client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "deleted"
    assert payload["deactivated_chunk_count"] == 3


def test_document_delete_api_returns_not_found_for_missing_document(client, monkeypatch) -> None:
    from app.services.update_service import DocumentNotFoundError

    def fake_soft_delete_document(*, db, document_id):
        raise DocumentNotFoundError("document 不存在")

    monkeypatch.setattr("app.api.documents.soft_delete_document", fake_soft_delete_document)

    response = client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "not_found"
