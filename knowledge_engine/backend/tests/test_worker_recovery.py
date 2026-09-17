"""Worker 领取与周期恢复的快速测试（不依赖外部基础设施）。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.workers.ingest_worker import ingest_document_task
from app.workers.recovery_worker import recover_stale_tasks


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_worker_noops_when_task_cannot_be_claimed(monkeypatch) -> None:
    session = FakeSession()
    monkeypatch.setattr("app.workers.ingest_worker.SessionLocal", lambda: session)
    monkeypatch.setattr("app.workers.ingest_worker.claim", lambda *args, **kwargs: None)

    result = ingest_document_task.run(
        document_id=str(uuid.uuid4()),
        version_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        file_path="unused.txt",
    )

    assert result["status"] == "noop"
    assert session.closed is True


def test_stale_processing_defaults_to_failed_without_redispatch(monkeypatch) -> None:
    session = FakeSession()
    task = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        task_type="ingest",
        status="processing",
        dispatch_status="dispatched",
        worker_id="lost-worker",
        attempt_token=uuid.uuid4(),
        last_heartbeat_at=None,
        finished_at=None,
        updated_at=None,
    )
    monkeypatch.setattr("app.workers.recovery_worker.SessionLocal", lambda: session)
    monkeypatch.setattr("app.workers.recovery_worker.find_stale_queued", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.workers.recovery_worker.find_stale_processing", lambda *args, **kwargs: [task])
    monkeypatch.setattr("app.workers.recovery_worker._validate_records", lambda *args, **kwargs: (object(), object()))
    monkeypatch.setattr("app.workers.recovery_worker.settings.task_auto_recover_processing", False)

    result = recover_stale_tasks.run()

    assert result == {"queued_recovered": 0, "processing_recovered": 0, "failed": 1}
    assert task.status == "failed"
    assert task.attempt_token is None
    assert task.error_message.startswith("worker_lost:")
    assert session.commits == 2
    assert session.closed is True
