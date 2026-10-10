"""SSE v1 事件层（design.md §8 / execution-plan Phase 3）。

事件信封：`v / task_id / event_id / sequence / type / occurred_at / payload`；
类型：`meta / plan / tool_call / tool_result / source_status / evidence /
token_delta / citation / done / error`。

- 终态唯一：`done` 或 `error{fatal:true}` 至多一个，且必须是最后一个事件；
  `error{fatal:false}` 是过程诊断（引用闸门失败、重复无进展等），不是终态。
- 回放：Redis Stream **只负责 event replay**（不做 Agent crash recovery）；
  测试/单机默认内存实现。直播分发走进程内队列（单实例部署裁决见
  decisions.md 2026-10-10 多实例边界）。
- 订阅竞态安全：先注册直播队列、再读持久化回放，按 sequence 去重——
  完成后再订阅、断线重连（Last-Event-ID）都不会丢事件或重复事件。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger(__name__)

EVENT_TYPES = frozenset(
    {
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
)


class SseV1Error(Exception):
    """SSE v1 事件层契约违规（未知事件类型、重复终态、非法 Last-Event-ID 等）。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SseEvent(BaseModel):
    v: int = 1
    task_id: str
    event_id: str
    sequence: int
    type: str
    occurred_at: str = Field(default_factory=_now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.type == "done" or (self.type == "error" and self.payload.get("fatal") is True)


def parse_event_sequence(event_id: str) -> int | None:
    """event_id 形如 `<sequence>-<hex>`；取前缀还原 sequence。"""
    head = event_id.split("-", 1)[0]
    if not head.isdigit():
        return None
    return int(head)


class SseSubscription:
    """任务事件订阅：回放 + 直播，按 sequence 去重，终态后结束。"""

    def __init__(self, log: "SseEventLog", task_id: str, after_sequence: int = 0) -> None:
        self._log = log
        self._task_id = task_id
        self._after = after_sequence
        self._queue: asyncio.Queue[SseEvent] = asyncio.Queue()
        self._replay: list[SseEvent] | None = None
        self._last_yielded = after_sequence
        self._finished = False
        self._closed = False
        # 先注册直播队列再读回放：注册前的事件在持久化里，注册后的在队列里，去重兜底交叠
        self._log._attach(task_id, self._queue)

    @property
    def finished(self) -> bool:
        return self._finished

    async def next_event(self, timeout: float | None = None) -> SseEvent | None:
        """下一个事件；timeout 到返回 None（调用方发 keepalive）；已结束抛 StopAsyncIteration。"""
        if self._finished:
            raise StopAsyncIteration
        if self._replay is None:
            self._replay = await self._log.replay(self._task_id, self._after)

        while True:
            if self._replay:
                event = self._replay.pop(0)
            else:
                try:
                    if timeout is None:
                        event = await self._queue.get()
                    else:
                        event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    return None
            if event.sequence <= self._last_yielded:
                continue  # 回放与直播交叠区去重
            self._last_yielded = event.sequence
            if event.is_terminal:
                self._finished = True
            return event

    def __aiter__(self) -> "SseSubscription":
        return self

    async def __anext__(self) -> SseEvent:
        event = await self.next_event()
        if event is None:
            raise StopAsyncIteration
        return event

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._log._detach(self._task_id, self._queue)


class SseEventLog(Protocol):
    async def append(self, task_id: str, event_type: str, payload: dict[str, Any]) -> SseEvent: ...

    async def replay(self, task_id: str, after_sequence: int = 0) -> list[SseEvent]: ...

    def subscribe(self, task_id: str, after_sequence: int = 0) -> SseSubscription: ...

    async def resolve_after_sequence(self, task_id: str, last_event_id: str) -> int: ...


class _BaseEventLog:
    """共用：sequence 分配、终态唯一、进程内直播分发。子类只管持久化与回放读取。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sequences: dict[str, int] = {}
        self._terminal: dict[str, SseEvent] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}

    # ---- 子类实现 ----
    async def _persist(self, event: SseEvent) -> bool:
        raise NotImplementedError

    async def _load(self, task_id: str, after_sequence: int) -> list[SseEvent]:
        raise NotImplementedError

    async def _find(self, task_id: str, sequence: int) -> SseEvent | None:
        raise NotImplementedError

    # ---- 公共语义 ----
    async def append(self, task_id: str, event_type: str, payload: dict[str, Any]) -> SseEvent:
        if event_type not in EVENT_TYPES:
            raise SseV1Error(f"未知事件类型: {event_type}")
        async with self._lock:
            existing = self._terminal.get(task_id)
            if existing is not None:
                raise SseV1Error(
                    f"任务已有终态事件 {existing.event_id}，不得再追加 {event_type}"
                )
            is_terminal = event_type == "done" or (event_type == "error" and payload.get("fatal") is True)
            sequence = self._sequences.get(task_id, 0) + 1
            event = SseEvent(
                task_id=task_id,
                event_id=f"{sequence}-{uuid.uuid4().hex[:12]}",
                sequence=sequence,
                type=event_type,
                payload=dict(payload),
            )
            persisted = await self._persist(event)
            if not persisted:
                logger.warning(f"SSE 事件持久化失败（回放将缺失）: {task_id} #{sequence} {event_type}")
            self._sequences[task_id] = sequence
            if is_terminal:
                self._terminal[task_id] = event
            self._fanout(task_id, event)
            return event

    async def replay(self, task_id: str, after_sequence: int = 0) -> list[SseEvent]:
        return await self._load(task_id, after_sequence)

    def subscribe(self, task_id: str, after_sequence: int = 0) -> SseSubscription:
        return SseSubscription(self, task_id, after_sequence)

    async def resolve_after_sequence(self, task_id: str, last_event_id: str) -> int:
        sequence = parse_event_sequence(last_event_id)
        if sequence is None:
            raise SseV1Error(f"非法 Last-Event-ID: {last_event_id}")
        event = await self._find(task_id, sequence)
        if event is None or event.event_id != last_event_id:
            raise SseV1Error(f"Last-Event-ID 不属于该任务或已过期: {last_event_id}")
        return sequence

    def _attach(self, task_id: str, queue: asyncio.Queue) -> None:
        self._subs.setdefault(task_id, []).append(queue)

    def _detach(self, task_id: str, queue: asyncio.Queue) -> None:
        subs = self._subs.get(task_id, [])
        if queue in subs:
            subs.remove(queue)

    def _fanout(self, task_id: str, event: SseEvent) -> None:
        for queue in list(self._subs.get(task_id, [])):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"SSE 订阅队列已满，丢弃事件 {event.event_id}")


class InMemoryEventLog(_BaseEventLog):
    """单机/测试实现：事件保存在内存，进程内直播分发。"""

    def __init__(self) -> None:
        super().__init__()
        self._streams: dict[str, list[SseEvent]] = {}

    async def _persist(self, event: SseEvent) -> bool:
        self._streams.setdefault(event.task_id, []).append(event)
        return True

    async def _load(self, task_id: str, after_sequence: int) -> list[SseEvent]:
        return [e for e in self._streams.get(task_id, []) if e.sequence > after_sequence]

    async def _find(self, task_id: str, sequence: int) -> SseEvent | None:
        for event in self._streams.get(task_id, []):
            if event.sequence == sequence:
                return event
        return None


class RedisStreamEventLog(_BaseEventLog):
    """生产实现：Redis Stream 存事件用于回放（XADD + XRANGE）。

    直播分发仍在进程内（单实例部署）。Redis 故障时事件降级为仅直播并告警——
    与 task_state_store 的容错一致；回放缺失不会伪造事件。
    """

    def __init__(self, redis: Any = None, *, namespace: str = "sse:v1", ttl_seconds: int = 86400 * 3) -> None:
        super().__init__()
        if redis is None:
            from app.core.redis_client import redis_client as default_redis

            redis = default_redis
        self._redis = redis
        self._namespace = namespace
        self._ttl_seconds = ttl_seconds

    def _key(self, task_id: str) -> str:
        return f"{self._namespace}:task:{task_id}"

    async def _persist(self, event: SseEvent) -> bool:
        key = self._key(event.task_id)
        try:
            # 显式 ID `<sequence>-0`：Last-Event-ID 即回放位置，与 sequence 一一对应
            await self._redis.execute_command("XADD", key, f"{event.sequence}-0", "data", event.model_dump_json())
            await self._redis.execute_command("EXPIRE", key, self._ttl_seconds)
            return True
        except Exception as exc:
            logger.warning(f"Redis Stream XADD 失败: {key} - {type(exc).__name__}")
            return False

    async def _load(self, task_id: str, after_sequence: int) -> list[SseEvent]:
        key = self._key(task_id)
        lower = f"({after_sequence}-0" if after_sequence > 0 else "-"
        try:
            rows = await self._redis.execute_command("XRANGE", key, lower, "+")
        except Exception as exc:
            logger.warning(f"Redis Stream XRANGE 失败: {key} - {type(exc).__name__}")
            return []
        events: list[SseEvent] = []
        for _entry_id, fields in rows or []:
            raw = fields.get("data") if isinstance(fields, dict) else None
            if not raw:
                continue
            try:
                events.append(SseEvent.model_validate_json(raw))
            except Exception as exc:
                logger.warning(f"SSE 事件解析失败（跳过）: {key} - {type(exc).__name__}")
        return events

    async def _find(self, task_id: str, sequence: int) -> SseEvent | None:
        key = self._key(task_id)
        try:
            rows = await self._redis.execute_command("XRANGE", key, f"{sequence}-0", f"{sequence}-0")
        except Exception as exc:
            logger.warning(f"Redis Stream XRANGE 失败: {key} - {type(exc).__name__}")
            return None
        for _entry_id, fields in rows or []:
            raw = fields.get("data") if isinstance(fields, dict) else None
            if not raw:
                continue
            try:
                return SseEvent.model_validate_json(raw)
            except Exception:
                return None
        return None


def format_sse(event: SseEvent) -> str:
    """SSE 报文：id 供 Last-Event-ID 续传，event 名即类型，data 为完整信封。"""
    return f"id: {event.event_id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
