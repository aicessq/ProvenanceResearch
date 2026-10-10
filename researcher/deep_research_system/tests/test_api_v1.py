"""`/api/v1` HTTP 契约（P3d 后半：第一个可演示 Demo 的公共接口）。

覆盖：创建/查询/取消/删除任务、回答结局与任务生命周期分开、
SSE 顺序与终态、Last-Event-ID 重连回放、problem+json 错误、
旧接口错误形状与 OpenAPI 回归。
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from app.api import routes_v1
from app.services.agentic_service import AgenticTaskService
from app.services.sse_v1 import InMemoryEventLog
from main import create_application
from tests.test_agentic_service import (
    PLAN_CALL,
    PLAN_DONE,
    AutoWriter,
    FakeStoreHolder,
    NoChecker,
    ScriptLLM,
    SplitLLM,
    YesChecker,
    make_runtime,
)


def answered_factory(store):
    def factory():
        runtime = make_runtime(store.store, checker=YesChecker())
        runtime.llm = SplitLLM(ScriptLLM([PLAN_CALL, PLAN_DONE]), AutoWriter(store.store))
        return runtime

    return factory


def refused_factory(store):
    def factory():
        runtime = make_runtime(store.store)
        runtime.llm = SplitLLM(ScriptLLM([PLAN_DONE]), ScriptLLM([]))
        return runtime

    return factory


def slow_factory(store):
    def factory():
        runtime = make_runtime(store.store, checker=YesChecker())
        runtime.llm = SplitLLM(ScriptLLM([PLAN_CALL, PLAN_DONE], delay=60), AutoWriter(store.store))
        return runtime

    return factory


def make_client(monkeypatch, factory) -> TestClient:
    service = AgenticTaskService(runtime_factory=factory, event_log=InMemoryEventLog())
    monkeypatch.setattr(routes_v1, "_service", service)
    return TestClient(create_application())


def wait_task(client: TestClient, task_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = client.get(f"/api/v1/tasks/{task_id}").json()
        if view["status"] in ("completed", "failed", "cancelled"):
            return view
        time.sleep(0.02)
    raise AssertionError(f"任务未在 {timeout}s 内结束: {task_id}")


def parse_sse(body: str) -> list[dict]:
    frames = []
    for block in body.strip().split("\n\n"):
        frame: dict = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                frame["id"] = line[4:]
            elif line.startswith("event: "):
                frame["event"] = line[7:]
            elif line.startswith("data: "):
                frame["data"] = json.loads(line[6:])
        if frame:
            frames.append(frame)
    return frames


def test_create_and_complete_task_with_answered_outcome(monkeypatch) -> None:
    store = FakeStoreHolder()
    with make_client(monkeypatch, answered_factory(store)) as client:
        resp = client.post("/api/v1/tasks", json={"query": "网络安全法为何制定？"})
        assert resp.status_code == 201
        created = resp.json()
        assert created["task_id"]
        assert created["status"] in ("pending", "running")

        view = wait_task(client, created["task_id"])
        assert view["status"] == "completed"  # 生命周期
        assert view["error"] is None
        assert view["answer"]["status"] == "answered"  # 回答结局
        assert view["answer"]["text"]
        assert view["answer"]["claims"] and view["answer"]["citations"]
        assert view["answer"]["budget_report"]["tool_calls"] == 1


def test_refused_answer_is_completed_task_not_error(monkeypatch) -> None:
    """任务结果与拒答分开：拒答不进 error，任务生命周期仍是 completed。"""
    store = FakeStoreHolder()
    with make_client(monkeypatch, refused_factory(store)) as client:
        created = client.post("/api/v1/tasks", json={"query": "无据问题？"}).json()
        view = wait_task(client, created["task_id"])

        assert view["status"] == "completed"
        assert view["error"] is None
        assert view["answer"]["status"] == "refused"
        assert view["answer"]["refusal_reason"] == "no_evidence"


def test_missing_cloud_config_fails_task_explicitly(monkeypatch) -> None:
    def factory():
        from app.services.agentic_service import AgenticConfigError

        raise AgenticConfigError("config_missing", "DEEPSEEK_API_KEY 未配置")

    with make_client(monkeypatch, factory) as client:
        created = client.post("/api/v1/tasks", json={"query": "缺配置"}).json()
        view = wait_task(client, created["task_id"])

        assert view["status"] == "failed"
        assert view["answer"] is None
        assert view["error"]["code"] == "config_missing"


def test_sse_stream_event_order_and_single_terminal(monkeypatch) -> None:
    store = FakeStoreHolder()
    with make_client(monkeypatch, answered_factory(store)) as client:
        created = client.post("/api/v1/tasks", json={"query": "网络安全法为何制定？"}).json()
        wait_task(client, created["task_id"])

        resp = client.get(f"/api/v1/tasks/{created['task_id']}/events")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        frames = parse_sse(resp.text)

        types = [f["event"] for f in frames]
        assert types[0] == "meta"
        assert types[-1] == "done"
        # 工具 → 证据 → 引用 → 终态顺序（roadmap P3d 验收）
        assert types.index("tool_call") < types.index("tool_result") < types.index("evidence")
        assert types.index("evidence") < types.index("citation") < types.index("done")
        assert types.count("done") == 1
        # id 供 Last-Event-ID 续传；data 为 v1 信封
        assert all(f["id"] and f["data"]["v"] == 1 for f in frames)
        assert [f["data"]["sequence"] for f in frames] == list(range(1, len(frames) + 1))
        assert frames[-1]["data"]["payload"]["task_status"] == "completed"


def test_sse_reconnect_with_last_event_id_replays_only_missing(monkeypatch) -> None:
    store = FakeStoreHolder()
    with make_client(monkeypatch, answered_factory(store)) as client:
        created = client.post("/api/v1/tasks", json={"query": "网络安全法为何制定？"}).json()
        wait_task(client, created["task_id"])

        full = parse_sse(client.get(f"/api/v1/tasks/{created['task_id']}/events").text)
        cut = full[2]["id"]  # 断线前只收到前 3 个事件

        resumed = client.get(
            f"/api/v1/tasks/{created['task_id']}/events",
            headers={"Last-Event-ID": cut},
        )
        frames = parse_sse(resumed.text)
        assert [f["event"] for f in frames] == [f["event"] for f in full[3:]]
        assert frames[-1]["event"] == "done"
        # 合起来无缺无重
        assert [f["id"] for f in full[:3]] + [f["id"] for f in frames] == [f["id"] for f in full]

        bad = client.get(
            f"/api/v1/tasks/{created['task_id']}/events",
            headers={"Last-Event-ID": "99-nosuchid"},
        )
        assert bad.status_code == 400
        assert bad.headers["content-type"].startswith("application/problem+json")
        assert bad.json()["code"] == "invalid_last_event_id"


def test_cancel_endpoint_and_not_running_conflict(monkeypatch) -> None:
    store = FakeStoreHolder()
    with make_client(monkeypatch, slow_factory(store)) as client:
        created = client.post("/api/v1/tasks", json={"query": "取消测试"}).json()
        time.sleep(0.1)  # 任务进入 running

        resp = client.post(f"/api/v1/tasks/{created['task_id']}/cancel")
        assert resp.status_code == 200
        assert resp.json() == {"task_id": created["task_id"], "status": "cancelled"}

        view = wait_task(client, created["task_id"])
        assert view["status"] == "cancelled"

        again = client.post(f"/api/v1/tasks/{created['task_id']}/cancel")
        assert again.status_code == 200  # 幂等

        missing = client.post("/api/v1/tasks/task_missing/cancel")
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert missing.json()["code"] == "task_not_found"


def test_delete_endpoint_guards_and_success(monkeypatch) -> None:
    store = FakeStoreHolder()
    with make_client(monkeypatch, slow_factory(store)) as client:
        created = client.post("/api/v1/tasks", json={"query": "删除测试"}).json()
        time.sleep(0.1)

        running = client.delete(f"/api/v1/tasks/{created['task_id']}")
        assert running.status_code == 409
        assert running.json()["code"] == "task_running"

        client.post(f"/api/v1/tasks/{created['task_id']}/cancel")
        wait_task(client, created["task_id"])

        done = client.delete(f"/api/v1/tasks/{created['task_id']}")
        assert done.status_code == 200
        assert done.json() == {"task_id": created["task_id"], "deleted": True}

        gone = client.get(f"/api/v1/tasks/{created['task_id']}")
        assert gone.status_code == 404

        missing = client.delete("/api/v1/tasks/task_missing")
        assert missing.status_code == 404


def test_problem_json_shape_and_legacy_errors_unchanged(monkeypatch) -> None:
    store = FakeStoreHolder()
    with make_client(monkeypatch, answered_factory(store)) as client:
        # v1：problem+json
        resp = client.get("/api/v1/tasks/task_missing")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["type"] == "about:blank"
        assert body["status"] == 404
        assert body["code"] == "task_not_found"
        assert body["instance"] == "/api/v1/tasks/task_missing"
        assert body["request_id"]

        # v1 校验错误也是 problem+json
        bad = client.post("/api/v1/tasks", json={"query": ""})
        assert bad.status_code == 422
        assert bad.headers["content-type"].startswith("application/problem+json")
        assert bad.json()["code"] == "validation_error"

        # 旧接口：错误形状保持 {code,message,details}
        legacy = client.get("/api/research/task_missing")
        assert legacy.status_code == 404
        legacy_body = legacy.json()
        assert set(legacy_body) == {"code", "message", "details"}

        # 旧接口：校验错误保持 {detail:[...]}
        legacy_bad = client.post("/api/research", json={})
        assert legacy_bad.status_code == 422
        assert set(legacy_bad.json()) == {"detail"}


def test_openapi_covers_v1_and_legacy_paths(monkeypatch) -> None:
    store = FakeStoreHolder()
    with make_client(monkeypatch, answered_factory(store)) as client:
        spec = client.get("/openapi.json").json()
        paths = spec["paths"]
        assert "/api/v1/tasks" in paths
        assert "/api/v1/tasks/{task_id}" in paths
        assert "/api/v1/tasks/{task_id}/events" in paths
        assert "/api/v1/tasks/{task_id}/cancel" in paths
        # 旧接口兼容期仍在
        assert "/api/research" in paths
        assert "/api/research/{task_id}/stream" in paths
