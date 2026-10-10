"""Agentic 任务桥契约（P3d 后半：Agent 接到 researcher 任务生命周期）。

覆盖：fake LLM 驱动真实 loop/executor/store 走通任务生命周期；
回答结果（answered/refused）与任务生命周期（completed/failed/cancelled）分开；
取消生效、缺云配置显式失败、SSE 事件顺序与终态唯一；
完成后再订阅可拿全量事件（完成订阅竞态）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.budget import Budget  # noqa: E402
from app.services.agentic_service import (  # noqa: E402
    AgenticConfigError,
    AgenticRuntime,
    AgenticTaskService,
)
from app.services.sse_v1 import InMemoryEventLog  # noqa: E402
from tools import KBSearchTool, ToolExecutor  # noqa: E402

KB_PAYLOAD = {
    "chunks": [
        {
            "chunk_id": "chunk-1",
            "score": 0.9,
            "source": "vector",
            "chunk_text": "第一条 为了保障网络安全，制定本法。",
            "document_id": "doc-1",
            "version_id": "ver-1",
            "doc_title": "网络安全法",
            "doc_type": "law",
            "page_start": 1,
        }
    ]
}

PLAN_CALL = json.dumps(
    {"tool_calls": [{"tool": "kb_search", "args": {"query": "网络安全法 第一条"}}]},
    ensure_ascii=False,
)
PLAN_DONE = json.dumps({"tool_calls": []}, ensure_ascii=False)


class ScriptLLM:
    def __init__(self, responses: list[str], *, delay: float = 0.0) -> None:
        self._responses = list(responses)
        self._delay = delay

    async def generate(self, messages, metadata=None):
        if self._delay:
            await asyncio.sleep(self._delay)
        text = self._responses.pop(0) if self._responses else "{}"

        class R:
            pass

        r = R()
        r.text = text
        r.prompt_tokens = 1
        r.completion_tokens = 1
        return r


class AutoWriter(ScriptLLM):
    """引用 store 里真实 citation_id，闸门可过的确定性 writer。"""

    def __init__(self, store, *, passed: bool = True) -> None:
        super().__init__([])
        self._store = store
        self._passed = passed

    async def generate(self, messages, metadata=None):
        cid = next((ev.citation_id for ev in self._store.all()), "KX")
        self._responses = [
            json.dumps(
                {
                    "answer": "为保障网络安全而制定。",
                    "claims": [{"claim": "为了保障网络安全而制定本法", "citations": [cid], "scope": "fulltext"}],
                },
                ensure_ascii=False,
            )
        ]
        return await super().generate(messages, metadata)


class YesChecker:
    async def check(self, claim, evidence):
        return True


class NoChecker:
    async def check(self, claim, evidence):
        return False


class SlowChecker:
    """卡住执行以便测试取消。"""

    async def check(self, claim, evidence):
        await asyncio.sleep(60)


def make_runtime(store, *, checker=None) -> AgenticRuntime:
    kb = KBSearchTool(
        base_url="http://kb.internal",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=KB_PAYLOAD)),
            follow_redirects=False,
        ),
        store=store,
        index_identity="idx",
    )
    return AgenticRuntime(
        llm=ScriptLLM([]),  # 由 factory 替换为 _SplitLLM（planner/writer 分脚本）
        executor=ToolExecutor(tools=[kb]),
        store=store,
        budget=Budget(),
        semantic_checker=checker,
    )


def service_with(runtime_factory) -> AgenticTaskService:
    return AgenticTaskService(runtime_factory=runtime_factory, event_log=InMemoryEventLog())


async def wait_terminal(service: AgenticTaskService, task_id: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = await service.get_task(task_id)
        if view["status"] in ("completed", "failed", "cancelled"):
            return view
        await asyncio.sleep(0.01)
    raise AssertionError(f"任务未在 {timeout}s 内结束: {task_id}")


async def collect_events(service: AgenticTaskService, task_id: str):
    sub = service.subscribe(task_id)
    try:
        return [event async for event in sub]
    finally:
        await sub.aclose()


def run_scenario(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=10.0))


def test_answered_task_lifecycle_and_event_order() -> None:
    async def scenario() -> None:
        store = FakeStoreHolder()
        planner = ScriptLLM([PLAN_CALL, PLAN_DONE])

        def factory():
            runtime = make_runtime(store.store, checker=YesChecker())
            runtime.llm = _SplitLLM(planner, AutoWriter(store.store))
            return runtime

        service = service_with(factory)
        created = await service.create_task("网络安全法为何制定？")
        view = await wait_terminal(service, created["task_id"])

        assert view["status"] == "completed"  # 生命周期
        assert view["error"] is None
        answer = view["answer"]
        assert answer["status"] == "answered"  # 回答结局
        assert answer["text"] and answer["citations"]
        assert answer["stop_reason"] == "sufficient_evidence"
        assert answer["budget_report"]["tool_calls"] == 1

        events = await collect_events(service, created["task_id"])
        types = [e.type for e in events]
        assert types[0] == "meta"
        assert types[-1] == "done"
        # 工具 → 证据 → 引用 → 终态 顺序（roadmap P3d 验收）
        assert types.index("tool_call") < types.index("tool_result") < types.index("evidence")
        assert types.index("evidence") < types.index("citation") < types.index("done")
        assert types.count("done") == 1  # 终态唯一
        assert "source_status" in types
        assert sum(1 for t in types if t == "error") == 0
        assert events[-1].payload["task_status"] == "completed"
        assert events[-1].payload["answer"]["status"] == "answered"

    run_scenario(scenario())


def test_refusal_is_answer_outcome_not_task_failure() -> None:
    """拒答：任务生命周期 completed，answer.status=refused，error 为空。"""

    async def scenario() -> None:
        store = FakeStoreHolder()

        def factory():
            runtime = make_runtime(store.store)
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_DONE]), ScriptLLM([]))
            return runtime

        service = service_with(factory)
        created = await service.create_task("没有任何证据的问题？")
        view = await wait_terminal(service, created["task_id"])

        assert view["status"] == "completed"
        assert view["error"] is None
        assert view["answer"]["status"] == "refused"
        assert view["answer"]["refusal_reason"] == "no_evidence"

        events = await collect_events(service, created["task_id"])
        terminal = events[-1]
        assert terminal.type == "done"
        assert terminal.payload["task_status"] == "completed"
        assert terminal.payload["answer"]["status"] == "refused"

    run_scenario(scenario())


def test_citation_gate_failure_refuses_after_regeneration() -> None:
    async def scenario() -> None:
        store = FakeStoreHolder()

        def factory():
            runtime = make_runtime(store.store, checker=NoChecker())
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_CALL, PLAN_DONE]), AutoWriter(store.store))
            return runtime

        service = service_with(factory)
        created = await service.create_task("网络安全法为何制定？")
        view = await wait_terminal(service, created["task_id"])

        assert view["status"] == "completed"
        assert view["answer"]["status"] == "refused"
        assert view["answer"]["refusal_reason"] == "citation_gate_failed"

        events = await collect_events(service, created["task_id"])
        assert events[-1].type == "done"
        diagnostics = [e for e in events if e.type == "error" and e.payload.get("fatal") is False]
        assert any(d.payload.get("reason") == "citation_gate_failed" for d in diagnostics)

    run_scenario(scenario())


def test_cancel_stops_task_with_single_terminal_event() -> None:
    async def scenario() -> None:
        store = FakeStoreHolder()

        def factory():
            runtime = make_runtime(store.store, checker=YesChecker())
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_CALL, PLAN_DONE], delay=60), AutoWriter(store.store))
            return runtime

        service = service_with(factory)
        created = await service.create_task("取消测试")
        await asyncio.sleep(0.05)  # 让任务进入 running
        assert service.cancel_task(created["task_id"]) == "cancelled"
        view = await wait_terminal(service, created["task_id"])

        assert view["status"] == "cancelled"
        events = await collect_events(service, created["task_id"])
        terminals = [e for e in events if e.is_terminal]
        assert len(terminals) == 1
        assert events[-1].type == "done"
        assert events[-1].payload["task_status"] == "cancelled"

    run_scenario(scenario())


def test_cancel_non_running_task_reports_not_running() -> None:
    async def scenario() -> None:
        store = FakeStoreHolder()

        def factory():
            runtime = make_runtime(store.store, checker=YesChecker())
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_DONE]), ScriptLLM([]))
            return runtime

        service = service_with(factory)
        created = await service.create_task("快速任务")
        await wait_terminal(service, created["task_id"])
        assert service.cancel_task(created["task_id"]) == "not_running"
        assert service.cancel_task("task_missing") == "not_found"

    run_scenario(scenario())


def test_missing_cloud_config_fails_explicitly_without_mock_answer() -> None:
    def factory():
        raise AgenticConfigError("config_missing", "DEEPSEEK_API_KEY 未配置")

    async def scenario() -> None:
        service = service_with(factory)
        created = await service.create_task("缺配置任务")
        view = await wait_terminal(service, created["task_id"])

        assert view["status"] == "failed"  # 显式失败，不是伪装成功
        assert view["error"]["code"] == "config_missing"
        assert view["answer"] is None

        events = await collect_events(service, created["task_id"])
        assert events[-1].type == "error"
        assert events[-1].payload["fatal"] is True
        assert events[-1].payload["error"]["code"] == "config_missing"

    run_scenario(scenario())


def test_subscribe_after_completion_replays_full_stream() -> None:
    """完成订阅竞态：任务跑完后才订阅，事件齐全、终态唯一。"""

    async def scenario() -> None:
        store = FakeStoreHolder()

        def factory():
            runtime = make_runtime(store.store, checker=YesChecker())
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_CALL, PLAN_DONE]), AutoWriter(store.store))
            return runtime

        service = service_with(factory)
        created = await service.create_task("网络安全法为何制定？")
        await wait_terminal(service, created["task_id"])

        events = await collect_events(service, created["task_id"])
        assert [e.sequence for e in events] == list(range(1, len(events) + 1))
        assert events[-1].is_terminal

    run_scenario(scenario())


def test_meta_carries_budget_overrides() -> None:
    async def scenario() -> None:
        store = FakeStoreHolder()

        def factory():
            runtime = make_runtime(store.store, checker=YesChecker())
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_DONE]), ScriptLLM([]))
            return runtime

        service = service_with(factory)
        created = await service.create_task("预算覆盖", {"max_rounds": 2, "deadline_seconds": 30.0})
        await wait_terminal(service, created["task_id"])

        events = await collect_events(service, created["task_id"])
        meta = events[0]
        assert meta.type == "meta"
        assert meta.payload["budget"] == {
            "max_rounds": 2,
            "max_tool_calls": 12,
            "max_tokens": 20000,
            "deadline_seconds": 30.0,
        }

    run_scenario(scenario())


def test_delete_running_rejected_and_completed_deletes_with_events() -> None:
    async def scenario() -> None:
        store = FakeStoreHolder()
        log = InMemoryEventLog()

        def factory():
            runtime = make_runtime(store.store, checker=YesChecker())
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_CALL, PLAN_DONE], delay=60), AutoWriter(store.store))
            return runtime

        service = AgenticTaskService(runtime_factory=factory, event_log=log)
        created = await service.create_task("删除测试")
        await asyncio.sleep(0.05)
        assert await service.delete_task(created["task_id"]) == "running"

        service.cancel_task(created["task_id"])
        await wait_terminal(service, created["task_id"])
        assert await service.delete_task(created["task_id"]) == "deleted"
        assert await service.get_task(created["task_id"]) is None
        assert await log.replay(created["task_id"]) == []

    run_scenario(scenario())


class StubTaskStore:
    """记录生命周期写入（与 ResearchService 共用同一任务状态存储契约）。"""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.deleted: list[str] = []

    async def create_task(self, task_id=None, input_data=None, metadata=None, topology_name=None):
        self.created.append({"task_id": task_id, "input_data": input_data, "metadata": metadata, "topology_name": topology_name})

    async def update_task_status(self, task_id, status, progress=None, current_stage=None, current_agent=None, result=None, error=None):
        self.updated.append({"task_id": task_id, "status": status, "result": result, "error": error})

    async def get_task_state(self, task_id):
        return None

    async def search_tasks(self, **kwargs):
        return []

    async def delete_task(self, task_id):
        self.deleted.append(task_id)


def test_lifecycle_persists_to_task_state_store() -> None:
    """接到 researcher 任务生命周期：同一状态存储记录 created → running → completed。"""

    async def scenario() -> None:
        store = FakeStoreHolder()
        stub = StubTaskStore()

        def factory():
            runtime = make_runtime(store.store, checker=YesChecker())
            runtime.llm = _SplitLLM(ScriptLLM([PLAN_CALL, PLAN_DONE]), AutoWriter(store.store))
            return runtime

        service = AgenticTaskService(runtime_factory=factory, event_log=InMemoryEventLog(), task_store=stub)
        created = await service.create_task("持久化测试")
        await wait_terminal(service, created["task_id"])

        assert stub.created and stub.created[0]["topology_name"] == "agentic"
        assert stub.created[0]["metadata"]["query"] == "持久化测试"
        statuses = [u["status"] for u in stub.updated]
        assert statuses[0] == "running"
        assert statuses[-1] == "completed"
        assert stub.updated[-1]["result"]["status"] == "answered"

    run_scenario(scenario())


class _SplitLLM:
    """planner / writer 分别喂脚本（真实 loop 中两者是同一个 LLM 对象）。"""

    def __init__(self, planner: ScriptLLM, writer: ScriptLLM) -> None:
        self._planner = planner
        self._writer = writer

    async def generate(self, messages, metadata=None):
        stage = (metadata or {}).get("stage", "")
        if stage == "plan":
            return await self._planner.generate(messages, metadata)
        return await self._writer.generate(messages, metadata)


class FakeStoreHolder:
    """每任务独立 EvidenceStore 的容器（factory 闭包需要在任务运行时持有）。"""

    def __init__(self) -> None:
        from evidence.store import EvidenceStore

        self.store = EvidenceStore()
