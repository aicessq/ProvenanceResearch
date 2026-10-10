"""SSE v1 事件层契约（roadmap P3d 验收：顺序、终态唯一、完成订阅竞态、终态重连及回放）。

同一套语义测试跑两个后端：InMemoryEventLog 与 RedisStreamEventLog（fake Redis，
只模拟 XADD/XRANGE/EXPIRE 三个命令的真实语义）。全部无凭证、不联网。
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.sse_v1 import (
    EVENT_TYPES,
    InMemoryEventLog,
    RedisStreamEventLog,
    SseV1Error,
    format_sse,
    parse_event_sequence,
)


class FakeRedis:
    """最小 Redis Stream 模拟：XADD 显式 ID / XRANGE 开闭区间 / EXPIRE。"""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self.fail_persist = False

    async def execute_command(self, command: str, *args):
        cmd = command.upper()
        if cmd == "XADD":
            if self.fail_persist:
                raise ConnectionError("redis down")
            key, entry_id, field, value = args
            self.streams.setdefault(key, []).append((entry_id, {field: value}))
            return entry_id
        if cmd == "XRANGE":
            key, lower, upper = args

            def in_range(entry_id: str) -> bool:
                seq = int(entry_id.split("-")[0])

                def bound(raw: str, is_lower: bool) -> bool:
                    if raw in ("-", "+"):
                        return True
                    exclusive = raw.startswith("(")
                    bound_seq = int(raw.lstrip("(").split("-")[0])
                    if is_lower:
                        return seq > bound_seq if exclusive else seq >= bound_seq
                    return seq < bound_seq if exclusive else seq <= bound_seq

                return bound(lower, True) and bound(upper, False)

            return [(eid, dict(fields)) for eid, fields in self.streams.get(key, []) if in_range(eid)]
        if cmd == "EXPIRE":
            return 1
        raise AssertionError(f"unexpected redis command: {command}")


def make_log():
    return RedisStreamEventLog(FakeRedis())


LOG_FACTORIES = {"memory": InMemoryEventLog, "redis": make_log}


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_envelope_and_sequence_monotonic(backend) -> None:
    async def scenario() -> None:
        log = LOG_FACTORIES[backend]()
        first = await log.append("t1", "meta", {"question": "q"})
        second = await log.append("t1", "plan", {"round": 1})

        assert first.v == 1 and first.task_id == "t1"
        assert first.sequence == 1 and second.sequence == 2
        assert parse_event_sequence(first.event_id) == 1
        assert first.occurred_at.endswith("Z")
        assert first.payload == {"question": "q"}

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_unknown_event_type_rejected(backend) -> None:
    async def scenario() -> None:
        log = LOG_FACTORIES[backend]()
        with pytest.raises(SseV1Error):
            await log.append("t1", "unknown_type", {})

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_terminal_unique_and_last(backend) -> None:
    async def scenario() -> None:
        log = LOG_FACTORIES[backend]()
        await log.append("t1", "meta", {})
        await log.append("t1", "error", {"fatal": False, "reason": "citation_gate_failed"})  # 诊断非终态
        terminal = await log.append("t1", "done", {"task_status": "completed"})

        assert terminal.is_terminal
        with pytest.raises(SseV1Error):
            await log.append("t1", "done", {"task_status": "completed"})
        with pytest.raises(SseV1Error):
            await log.append("t1", "error", {"fatal": True})

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_replay_after_sequence_and_last_event_id(backend) -> None:
    async def scenario() -> None:
        log = LOG_FACTORIES[backend]()
        e1 = await log.append("t1", "meta", {})
        e2 = await log.append("t1", "plan", {"round": 1})
        await log.append("t1", "done", {"task_status": "completed"})

        replayed = await log.replay("t1", after_sequence=e1.sequence)
        assert [e.sequence for e in replayed] == [2, 3]

        after = await log.resolve_after_sequence("t1", e2.event_id)
        assert after == 2

        with pytest.raises(SseV1Error):
            await log.resolve_after_sequence("t1", "not-an-id")
        with pytest.raises(SseV1Error):
            await log.resolve_after_sequence("t1", "99-deadbeef")  # 不属于该任务

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_subscribe_after_completion_delivers_full_history(backend) -> None:
    """完成订阅竞态：任务已终态后才订阅，仍能拿到全部事件并以终态结束。"""

    async def scenario() -> None:
        log = LOG_FACTORIES[backend]()
        await log.append("t1", "meta", {})
        await log.append("t1", "tool_call", {"tool": "kb_search"})
        await log.append("t1", "done", {"task_status": "completed"})

        sub = log.subscribe("t1")
        events = [event async for event in sub]
        assert [e.type for e in events] == ["meta", "tool_call", "done"]
        assert sub.finished
        with pytest.raises(StopAsyncIteration):
            await sub.next_event()

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_live_delivery_order_and_no_duplicates(backend) -> None:
    async def scenario() -> None:
        log = LOG_FACTORIES[backend]()
        await log.append("t1", "meta", {})
        sub = log.subscribe("t1")
        # 回放区（meta）与直播区（其余）交叠时不得重复或乱序
        await log.append("t1", "tool_call", {"tool": "kb_search"})
        await log.append("t1", "tool_result", {"tool": "kb_search", "status": "ok"})
        await log.append("t1", "evidence", {"citation_id": "K1"})
        await log.append("t1", "done", {"task_status": "completed"})

        events = [event async for event in sub]
        assert [e.type for e in events] == ["meta", "tool_call", "tool_result", "evidence", "done"]
        assert [e.sequence for e in events] == [1, 2, 3, 4, 5]

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_reconnect_with_last_event_id_replays_only_missing(backend) -> None:
    """终态重连：断开前收到 N 个事件，重连（Last-Event-ID）只补后续，合起来无缺无重。"""

    async def scenario() -> None:
        log = LOG_FACTORIES[backend]()
        await log.append("t1", "meta", {})
        e2 = await log.append("t1", "plan", {"round": 1})
        first = await log.replay("t1", after_sequence=0)
        assert [e.type for e in first] == ["meta", "plan"]  # 断线前只看到 meta/plan

        # 断线期间继续跑完任务
        await log.append("t1", "tool_call", {"tool": "kb_search"})
        terminal = await log.append("t1", "done", {"task_status": "completed"})

        after = await log.resolve_after_sequence("t1", e2.event_id)
        sub = log.subscribe("t1", after_sequence=after)
        rest = [event async for event in sub]
        assert [e.type for e in rest] == ["tool_call", "done"]
        assert rest[-1].event_id == terminal.event_id

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_persist_failure_degrades_to_live_only(backend) -> None:
    """Redis 故障不伪造回放、不阻塞直播（与 task_state_store 容错一致）。"""

    async def scenario() -> None:
        redis = FakeRedis()
        redis.fail_persist = True
        log = RedisStreamEventLog(redis)
        sub = log.subscribe("t1")
        event = await log.append("t1", "meta", {})
        got = await asyncio.wait_for(sub.next_event(timeout=1.0), timeout=2.0)
        assert got is not None and got.event_id == event.event_id
        assert await log.replay("t1") == []

    asyncio.run(scenario())


def test_format_sse_wire_shape() -> None:
    async def scenario() -> None:
        log = InMemoryEventLog()
        event = await log.append("t1", "meta", {"question": "q"})
        wire = format_sse(event)
        assert wire.startswith(f"id: {event.event_id}\n")
        assert "event: meta\n" in wire
        assert f'"sequence":{event.sequence}' in wire.replace(" ", "")
        assert wire.endswith("\n\n")

    asyncio.run(scenario())


def test_event_types_cover_design_contract() -> None:
    assert EVENT_TYPES == {
        "meta",
        "plan",
        "tool_call",
        "tool_result",
        "source_status",
        "evidence",
        "token_delta",
        "citation",
        "done",
        "error",
    }
