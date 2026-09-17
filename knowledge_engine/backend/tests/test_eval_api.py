"""Phase 10 `/eval/run` API 测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class FakeEvalSummary:
    run_id = "run-1"
    dataset_name = "golden-dataset"
    total_count = 3
    recall_at_k = 0.67
    mrr = 0.5
    citation_accuracy = 1.0
    refusal_accuracy = 1.0
    average_latency_ms = 12.3
    status = "completed"


def test_eval_run_api_returns_summary(client, monkeypatch) -> None:
    def fake_run_eval(*, db, dataset_name, dataset_path=None):
        assert dataset_name == "golden-dataset"
        return FakeEvalSummary()

    monkeypatch.setattr("app.api.eval.run_eval", fake_run_eval)

    response = client.post("/api/v1/eval/run", json={"dataset_name": "golden-dataset"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-1"
    assert payload["recall_at_k"] == 0.67
    assert payload["status"] == "completed"


def test_eval_run_api_returns_bad_request_for_invalid_input(client, monkeypatch) -> None:
    def fake_run_eval(*, db, dataset_name, dataset_path=None):
        raise ValueError("dataset 不存在")

    monkeypatch.setattr("app.api.eval.run_eval", fake_run_eval)

    response = client.post("/api/v1/eval/run", json={"dataset_name": "missing-dataset"})

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "invalid_request"
