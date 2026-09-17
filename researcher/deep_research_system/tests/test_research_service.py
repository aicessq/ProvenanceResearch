from __future__ import annotations

import asyncio
from enum import Enum

from app.schemas.state import ResearchState
from app.services.research_service import DeleteTaskResult, ResearchService


class StubTopology:
    def __init__(self, report_title: str) -> None:
        self.report_title = report_title
        self.calls = 0

    async def execute(self, state: ResearchState, on_event=None) -> ResearchState:
        self.calls += 1
        if on_event:
            on_event({"type": "stage_start", "agent": "planner", "progress": 10})
            on_event({"type": "report_update", "agent": "writer", "progress": 97, "output": {"title": self.report_title}})
        state.final_report = {"title": self.report_title}
        state.claim_graph = [{"claim_id": "clm_001"}]
        state.current_stage = "completed"
        state.progress = 100
        return state


class StubTaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StubTaskState:
    def __init__(self, task_id: str, status: str = "completed") -> None:
        self.task_id = task_id
        self.status = status
        self.progress = 100 if status == "completed" else 0
        self.current_stage = "completed" if status == "completed" else "init"
        self.topology_name = "hierarchical"
        self.created_at = "2026-07-07T00:00:00Z"
        self.result = {"report": {"title": "persisted-report"}, "claim_graph": [], "metrics": {}, "audit_trail": []}
        self.error = {"message": "persisted-error"} if status == "failed" else None
        self.metadata = {"query": "Persisted query", "task_type": "industry_report", "depth": "standard"}
        self.input_data = {"user_query": "Persisted query", "task_type": "industry_report", "depth": "standard"}


class StubTaskStore:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.persisted_task: StubTaskState | None = None
        self.running_tasks: list[StubTaskState] = []

    async def create_task(self, task_id=None, input_data=None, metadata=None, topology_name=None):
        self.created.append({
            "task_id": task_id,
            "input_data": input_data,
            "metadata": metadata,
            "topology_name": topology_name,
        })
        return None

    async def update_task_status(self, **kwargs):
        self.updated.append(kwargs)
        return None

    async def get_task_state(self, task_id: str):
        if self.persisted_task and self.persisted_task.task_id == task_id:
            return self.persisted_task
        return None

    async def search_tasks(self, status=None, limit=1000):
        if status == StubTaskStatus.RUNNING:
            return self.running_tasks
        return [self.persisted_task] if self.persisted_task else []

    async def delete_task(self, task_id: str):
        if self.persisted_task and self.persisted_task.task_id == task_id:
            self.persisted_task = None
            return True
        return False


def build_service() -> tuple[ResearchService, StubTaskStore]:
    service = ResearchService()
    store = StubTaskStore()
    service._task_store = store
    service._task_status_enum = StubTaskStatus
    return service, store


def test_create_task_sync_uses_hierarchical_topology() -> None:
    service, store = build_service()
    service._hierarchical = StubTopology("sync-report")

    result = asyncio.run(service.create_task_sync({"user_query": "AI market", "task_type": "industry_report"}))

    assert result["status"] == "completed"
    assert result["selected_topology"] == "hierarchical"
    assert result["result"]["report"]["title"] == "sync-report"
    assert store.created[0]["metadata"]["query"] == "AI market"
    assert any(update["status"] == StubTaskStatus.COMPLETED for update in store.updated)


def test_create_task_emits_done_event_to_subscribers() -> None:
    service, _ = build_service()
    service._hierarchical = StubTopology("async-report")

    async def scenario():
        task_meta = await service.create_task({"user_query": "AI market", "task_type": "industry_report"})
        queue = service.subscribe(task_meta["task_id"])
        try:
            done_event = None
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                if event.get("type") == "done":
                    done_event = event
                    break
            assert done_event is not None
            assert done_event["result"]["report"]["title"] == "async-report"
        finally:
            service.unsubscribe(task_meta["task_id"], queue)

    asyncio.run(scenario())


def test_get_task_falls_back_to_persisted_state() -> None:
    service, store = build_service()
    store.persisted_task = StubTaskState("task_persisted")

    task = asyncio.run(service.get_task("task_persisted"))

    assert task is not None
    assert task["task_id"] == "task_persisted"
    assert task["result"]["report"]["title"] == "persisted-report"
    assert task["query"] == "Persisted query"


def test_delete_task_rejects_running_tasks() -> None:
    service, _ = build_service()

    async def scenario():
        task_meta = await service.create_task({"user_query": "AI market", "task_type": "industry_report"})
        assert await service.delete_task(task_meta["task_id"]) == DeleteTaskResult.RUNNING
        service.cancel_task(task_meta["task_id"])

    asyncio.run(scenario())


async def _delete_persisted_task(service: ResearchService, task_id: str):
    return await service.delete_task(task_id)


def test_delete_task_removes_persisted_state() -> None:
    service, store = build_service()
    store.persisted_task = StubTaskState("task_delete")

    result = asyncio.run(_delete_persisted_task(service, "task_delete"))

    assert result == DeleteTaskResult.DELETED
    assert asyncio.run(service.get_task("task_delete")) is None


def test_initialize_marks_orphaned_running_tasks_failed() -> None:
    service, store = build_service()
    store.running_tasks = [StubTaskState("task_orphaned", status="running")]

    asyncio.run(service._mark_orphaned_running_tasks_failed())

    assert store.updated[-1]["task_id"] == "task_orphaned"
    assert store.updated[-1]["status"] == StubTaskStatus.FAILED
    assert store.updated[-1]["error"]["message"] == "service restarted before task completion"
