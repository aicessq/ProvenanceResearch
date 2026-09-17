from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from enum import Enum
from inspect import isawaitable
from typing import Any

from app.core.config import get_config
from app.schemas.state import ResearchState
from app.schemas.task import TaskSpec
from app.services.trace_service import TraceService
from app.topology.debate import DebateTopology
from app.topology.hierarchical import HierarchicalTopology
from app.topology.router import TopologyRouter
from app.utils.ids import generate_id
from app.utils.time import now_iso

logger = logging.getLogger(__name__)


class DeleteTaskResult(str, Enum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    RUNNING = "running"


class ResearchService:
    def __init__(self) -> None:
        self.topology_router = TopologyRouter()
        self._cache: dict[str, Any] = {}  # simple in-memory cache
        self.trace = TraceService()
        self._tasks: dict[str, dict] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._hierarchical = HierarchicalTopology()
        self._debate = DebateTopology()
        self._task_store = None
        self._task_status_enum = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        from app.services.task_state_store import task_state_store, TaskStatus

        self._task_store = task_state_store
        self._task_status_enum = TaskStatus
        await self._mark_orphaned_running_tasks_failed()
        self._initialized = True

    async def _mark_orphaned_running_tasks_failed(self) -> None:
        if not self._task_store or not self._task_status_enum:
            return

        running_tasks = await self._task_store.search_tasks(status=self._task_status_enum.RUNNING, limit=1000)
        for task_state in running_tasks:
            await self._task_store.update_task_status(
                task_id=task_state.task_id,
                status=self._task_status_enum.FAILED,
                error={"message": "service restarted before task completion"},
            )

    def subscribe(self, task_id: str) -> asyncio.Queue:
        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[task_id].append(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(task_id, [])
        if queue in subs:
            subs.remove(queue)

    def _emit(self, task_id: str, event: dict) -> None:
        for queue in self._subscribers.get(task_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def _build_task_record(self, task: TaskSpec, topology_name: str) -> dict:
        return {
            "task_id": task.task_id,
            "status": "running",
            "progress": 0,
            "current_stage": "init",
            "selected_topology": topology_name,
            "created_at": now_iso(),
            "result": None,
            "query": task.user_query,
            "task_type": task.task_type,
            "depth": task.depth,
        }

    async def _persist_created_task(self, task: TaskSpec, topology_name: str) -> None:
        if not self._task_store:
            return
        await self._task_store.create_task(
            task_id=task.task_id,
            input_data=task.model_dump(),
            metadata={
                "query": task.user_query,
                "task_type": task.task_type,
                "depth": task.depth,
                "budget_level": task.budget_level,
                "max_sources": task.max_sources,
                "language": task.language,
                "require_citations": task.require_citations,
            },
            topology_name=topology_name,
        )

    async def _persist_progress(self, task_id: str, progress: int | None = None, current_stage: str | None = None, current_agent: str | None = None) -> None:
        if not self._task_store or not self._task_status_enum:
            return
        await self._task_store.update_task_status(
            task_id=task_id,
            status=self._task_status_enum.RUNNING,
            progress=progress,
            current_stage=current_stage,
            current_agent=current_agent,
        )

    async def _persist_terminal_state(self, task_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
        if not self._task_store or not self._task_status_enum:
            return

        status_map = {
            "completed": self._task_status_enum.COMPLETED,
            "failed": self._task_status_enum.FAILED,
            "cancelled": self._task_status_enum.CANCELLED,
        }
        await self._task_store.update_task_status(
            task_id=task_id,
            status=status_map[status],
            progress=100 if status == "completed" else None,
            current_stage="completed" if status == "completed" else None,
            result=result,
            error={"message": error} if error else None,
        )

    def _task_from_state(self, task_state: Any) -> dict:
        metadata = task_state.metadata or {}
        error = task_state.error
        error_message = error.get("message") if isinstance(error, dict) else error
        return {
            "task_id": task_state.task_id,
            "status": task_state.status,
            "progress": task_state.progress,
            "current_stage": task_state.current_stage or "init",
            "selected_topology": task_state.topology_name or "hierarchical",
            "created_at": task_state.created_at,
            "result": task_state.result,
            "error": error_message,
            "query": metadata.get("query") or task_state.input_data.get("user_query", ""),
            "task_type": metadata.get("task_type") or task_state.input_data.get("task_type", "general"),
            "depth": metadata.get("depth") or task_state.input_data.get("depth", "standard"),
        }

    async def create_task(self, request: dict) -> dict:
        task_id = generate_id("task")
        task = TaskSpec(task_id=task_id, **request)
        topology_name, writer_template = self.topology_router.route(task.task_type)

        self._tasks[task_id] = self._build_task_record(task, topology_name)
        await self._persist_created_task(task, topology_name)

        task_handle = asyncio.create_task(self._execute(task, topology_name, writer_template))
        self._running[task_id] = task_handle
        return self._tasks[task_id]

    async def create_task_sync(self, request: dict) -> dict:
        task_id = generate_id("task")
        task = TaskSpec(task_id=task_id, **request)
        topology_name, writer_template = self.topology_router.route(task.task_type)

        self._tasks[task_id] = self._build_task_record(task, topology_name)
        await self._persist_created_task(task, topology_name)

        await self._execute(task, topology_name, writer_template)
        return self._tasks[task_id]

    async def _execute(self, task: TaskSpec, topology_name: str, writer_template: str = "writer/industry_report.zh.j2") -> dict:
        task_id = task.task_id
        state = ResearchState(task=task, selected_topology=topology_name, writer_template=writer_template)
        start_time = time.perf_counter()

        def on_topology_event(event: dict) -> None:
            event["task_id"] = task_id
            self._emit(task_id, event)
            if "progress" in event:
                self._tasks[task_id]["progress"] = event["progress"]
            if "agent" in event:
                self._tasks[task_id]["current_stage"] = event["agent"]
            persistence_task = self._persist_progress(
                task_id,
                progress=event.get("progress"),
                current_stage=event.get("agent"),
                current_agent=event.get("agent"),
            )
            if isawaitable(persistence_task):
                asyncio.create_task(persistence_task)

        try:
            await self._persist_progress(task_id, progress=0, current_stage="init")
            cache_key = hashlib.md5(task.user_query.encode()).hexdigest()
            cached = self._cache.get(cache_key)
            if cached:
                logger.info(f"Cache hit for task {task_id}")
                self._tasks[task_id].update({"status": "completed", "progress": 100, "current_stage": "completed", "result": cached})
                await self._persist_terminal_state(task_id, "completed", result=cached)
                self._emit(task_id, {"type": "done", "task_id": task_id, "result": cached, "progress": 100, "current_stage": "completed"})
                return cached

            self._emit(task_id, {"type": "start", "topology": topology_name, "progress": 0})

            if topology_name == "debate":
                state = await self._debate.execute(state, on_event=on_topology_event)
            else:
                state = await self._hierarchical.execute(state, on_event=on_topology_event)

            elapsed = (time.perf_counter() - start_time) * 1000

            result = {
                "report": state.final_report,
                "claim_graph": state.claim_graph,
                "metrics": {
                    "cost_so_far": round(state.cost_so_far, 4),
                    "latency_ms": round(elapsed, 2),
                    "model_usage": state.model_usage,
                    "token_usage": state.token_usage,
                    "total_audit_entries": len(state.audit_trail),
                },
                "audit_trail": state.audit_trail,
            }

            self._cache[cache_key] = result
            self.trace.record(task_id, state)

            self._tasks[task_id].update({
                "status": "completed",
                "progress": 100,
                "current_stage": "completed",
                "result": result,
            })
            await self._persist_terminal_state(task_id, "completed", result=result)

            self._emit(task_id, {
                "type": "done",
                "task_id": task_id,
                "result": result,
                "progress": 100,
                "current_stage": "completed",
            })

            return result

        except asyncio.CancelledError:
            logger.info(f"Task {task_id} was cancelled")
            self._tasks[task_id].update({"status": "cancelled"})
            await self._persist_terminal_state(task_id, "cancelled")
            self._emit(task_id, {"type": "cancelled", "task_id": task_id})
            return {"error": "cancelled"}
        except Exception as e:
            logger.exception(f"Task {task_id} failed: {e}")
            self._tasks[task_id].update({"status": "failed", "error": str(e)})
            await self._persist_terminal_state(task_id, "failed", error=str(e))
            self._emit(task_id, {"type": "error", "task_id": task_id, "error": str(e)})
            return {"error": str(e)}
        finally:
            self._running.pop(task_id, None)

    async def get_task(self, task_id: str) -> dict | None:
        task = self._tasks.get(task_id)
        if task:
            return task
        if not self._task_store:
            return None
        task_state = await self._task_store.get_task_state(task_id)
        if not task_state:
            return None
        return self._task_from_state(task_state)

    async def get_all_tasks(self) -> list[dict]:
        tasks = dict(self._tasks)
        if self._task_store:
            persisted_tasks = await self._task_store.search_tasks(limit=1000)
            for task_state in persisted_tasks:
                tasks.setdefault(task_state.task_id, self._task_from_state(task_state))
        return sorted(tasks.values(), key=lambda task: task.get("created_at", ""), reverse=True)

    async def delete_task(self, task_id: str) -> DeleteTaskResult:
        task_handle = self._running.get(task_id)
        if task_handle and not task_handle.done():
            return DeleteTaskResult.RUNNING

        in_memory_task = self._tasks.get(task_id)
        persisted_exists = False
        if self._task_store:
            persisted_exists = await self._task_store.get_task_state(task_id) is not None

        if not in_memory_task and not persisted_exists:
            return DeleteTaskResult.NOT_FOUND

        self._tasks.pop(task_id, None)
        self._subscribers.pop(task_id, None)
        stale_handle = self._running.get(task_id)
        if stale_handle and stale_handle.done():
            self._running.pop(task_id, None)

        if self._task_store:
            await self._task_store.delete_task(task_id)

        return DeleteTaskResult.DELETED

    def cancel_task(self, task_id: str) -> bool:
        task_handle = self._running.get(task_id)
        if task_handle and not task_handle.done():
            task_handle.cancel()
            self._tasks[task_id].update({"status": "cancelled"})
            self._emit(task_id, {"type": "cancelled", "task_id": task_id})
            return True
        return False
