from __future__ import annotations

import asyncio
import json
import time

from fastapi.testclient import TestClient

from app.api import routes_research
from app.services.research_service import DeleteTaskResult
from main import create_application
from .test_hardening import auth_env
from .test_research_service import build_service


class StubResearchService:
    def __init__(self) -> None:
        self.task = {
            "task_id": "task_test",
            "status": "running",
            "progress": 0,
            "current_stage": "init",
            "selected_topology": "hierarchical",
            "created_at": "2026-07-06T00:00:00Z",
            "result": None,
        }
        self.queue: asyncio.Queue = asyncio.Queue()
        self.stream_event = {"type": "done", "task_id": "task_test", "result": {"report": {"title": "done"}}, "progress": 100, "current_stage": "completed"}

    async def initialize(self) -> None:
        return None

    async def create_task(self, request: dict) -> dict:
        return self.task

    async def create_task_sync(self, request: dict) -> dict:
        self.task = {**self.task, "status": "completed", "result": {"report": {"title": "sync"}, "claim_graph": [], "metrics": {}, "audit_trail": []}}
        return self.task

    async def get_task(self, task_id: str) -> dict | None:
        return self.task if task_id == self.task["task_id"] else None

    async def get_all_tasks(self) -> list[dict]:
        return [self.task]

    def subscribe(self, task_id: str) -> asyncio.Queue:
        self.queue = asyncio.Queue()
        self.queue.put_nowait(self.stream_event)
        return self.queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        return None

    async def cancel_task(self, task_id: str) -> bool:
        return task_id == self.task["task_id"]

    async def delete_task(self, task_id: str):
        if task_id != self.task["task_id"]:
            return DeleteTaskResult.NOT_FOUND
        if self.task["status"] == "running":
            return DeleteTaskResult.RUNNING
        return DeleteTaskResult.DELETED


def test_research_routes_preserve_response_shape(monkeypatch) -> None:
    stub = StubResearchService()
    monkeypatch.setattr(routes_research, "_service", stub)

    client = TestClient(create_application())

    response = client.post("/api/research", json={"query": "AI market", "task_type": "industry_report", "depth": "quick"})
    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 0
    assert body["data"]["task_id"] == "task_test"
    assert body["data"]["selected_topology"] == "hierarchical"


def test_research_list_returns_existing_tasks(monkeypatch) -> None:
    stub = StubResearchService()
    monkeypatch.setattr(routes_research, "_service", stub)

    client = TestClient(create_application())

    response = client.get("/api/research")
    body = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["data"][0]["task_id"] == "task_test"


def test_research_stream_emits_state_then_done(monkeypatch) -> None:
    stub = StubResearchService()
    monkeypatch.setattr(routes_research, "_service", stub)

    client = TestClient(create_application())

    with client.stream("GET", "/api/research/task_test/stream") as response:
        payload = "".join(response.iter_text())

    assert '"type": "state"' in payload
    assert '"type": "done"' in payload


def test_research_delete_returns_deleted(monkeypatch) -> None:
    stub = StubResearchService()
    stub.task = {**stub.task, "status": "completed"}
    monkeypatch.setattr(routes_research, "_service", stub)

    client = TestClient(create_application())

    response = client.delete("/api/research/task_test")
    body = response.json()

    assert response.status_code == 200
    assert body["code"] == 0
    assert body["data"]["deleted"] is True


def test_research_delete_rejects_running_task(monkeypatch) -> None:
    stub = StubResearchService()
    monkeypatch.setattr(routes_research, "_service", stub)

    client = TestClient(create_application())

    response = client.delete("/api/research/task_test")

    assert response.status_code == 409


def test_research_stream_closes_on_error(monkeypatch) -> None:
    stub = StubResearchService()
    stub.stream_event = {"type": "error", "task_id": "task_test", "error": "boom"}
    monkeypatch.setattr(routes_research, "_service", stub)

    client = TestClient(create_application())

    with client.stream("GET", "/api/research/task_test/stream") as response:
        payload = "".join(response.iter_text())

    assert '"type": "state"' in payload
    assert '"type": "error"' in payload


def test_authenticated_legacy_api_completes_real_graph_and_replays_terminal(monkeypatch):
    auth_env(monkeypatch)
    service, _ = build_service()
    monkeypatch.setattr(routes_research, "_service", service)

    with TestClient(create_application()) as client:
        path = "/api/research"
        payload = {"query": "网络安全法为何制定？"}
        assert client.post(path, json=payload).status_code == 401
        token = client.post("/api/v1/auth/token", json={
            "username": "admin", "password": "correct-horse",
        }).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 200
        task_id = response.json()["data"]["task_id"]
        task_path = f"{path}/{task_id}"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            view = client.get(task_path, headers=headers).json()["data"]
            if view["status"] != "running":
                break
            time.sleep(0.01)
        assert view["status"] == "completed"
        report = view["result"]["report"]
        assert report["title"] == payload["query"]
        assert report["sections"][0]["citations"]
        with client.stream("GET", task_path + "/stream", headers=headers) as response:
            events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
        assert [event["type"] for event in events] == ["state", "done"]
        assert events[-1]["result"]["report"] == report
