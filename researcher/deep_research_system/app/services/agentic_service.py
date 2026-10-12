"""Agentic 任务桥（P3d 后半）：把顶层 agent.AgentLoop 接到 researcher 任务生命周期。

生命周期语义与 ResearchService 一致：pending → running → completed/failed/cancelled，
可取消、可删除、重启孤儿任务标记失败；回答结果（answered/refused）与任务生命周期
分开——拒答是成功的任务结局，不是任务失败（design.md §8）。

SSE v1：Agent trace 经 sink 翻译为版本化事件写入 SseEventLog（回放 + 直播）；
终态由本服务统一发出（done 带回答结局 / error{fatal} 带失败），保证终态唯一。

生产运行时全部云端能力：缺 DEEPSEEK_API_KEY 显式失败（任务 failed +
error{fatal}），绝不降级本地/模拟模型（AGENTS.md）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from typing import Any, Callable

from agent.budget import Budget, DEFAULT_DEADLINE_SECONDS, DEFAULT_MAX_ROUNDS, DEFAULT_MAX_MODEL_TOKENS, DEFAULT_MAX_TOOL_CALLS
from agent.citation_gate import CitationGate
from agent.loop import AgentLoop, SemanticVerifier
from app.services.sse_v1 import InMemoryEventLog
from app.services.task_state_store import TaskStatus
from app.utils.ids import generate_id
from app.utils.time import now_iso

logger = logging.getLogger(__name__)

BUDGET_KEYS = ("max_rounds", "max_tool_calls", "max_tokens", "deadline_seconds")

RUNNING_STATUS = "running"
TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class AgenticConfigError(Exception):
    """云配置缺失/非法：显式失败，不降级。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class AgenticRuntime:
    """一次任务所需的全部执行件。semantic_checker 为 None 时由服务建云语义复检。"""

    def __init__(
        self,
        *,
        llm: Any,
        executor: Any,
        store: Any,
        budget: Budget,
        semantic_checker: Any = None,
    ) -> None:
        self.llm = llm
        self.executor = executor
        self.store = store
        self.budget = budget
        self.semantic_checker = semantic_checker


RuntimeFactory = Callable[[], AgenticRuntime]


def build_cloud_runtime() -> AgenticRuntime:
    """生产运行时：DeepSeek（providers 适配层）+ 五工具。缺配置抛 AgenticConfigError。"""
    from evidence.registry import SourceRegistry
    from evidence.store import EvidenceStore
    from providers.llm.deepseek import DeepSeekLLMProvider
    from tools import (
        ArxivSearchTool,
        EvidenceReadTool,
        KBSearchTool,
        SourceFetchTool,
        ToolExecutor,
        WebSearchTool,
    )

    from app.services.cloud_config_service import CloudConfigService

    config = CloudConfigService()
    cfg = config.resolve("llm")
    # 凭证：配置面（LLM_API_KEY / 加密覆盖）优先；DEEPSEEK_API_KEY 为兼容回退（P4 冻结契约）
    api_key = (cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise AgenticConfigError(
            "config_missing",
            "LLM_API_KEY/DEEPSEEK_API_KEY 未配置；生产路径不使用本地/模拟模型，任务显式失败",
        )

    # 出站门（design.md §9）：凭证不等于授权——LLM/搜索外送问题与证据前逐能力检查；
    # 总开关关闭或未授权 → 显式失败，绝不"先跑起来再说"
    for capability in ("llm", "search:web", "search:arxiv"):
        allowed, reason = config.check_outbound(capability)
        if not allowed:
            raise AgenticConfigError(
                "cloud_upload_not_authorized",
                f"出站未授权（{capability}: {reason}）；请在设置面板/环境完成 CLOUD_DATA_UPLOAD_ALLOWED 与逐能力授权",
            )
    llm_kwargs: dict = {
        "api_key": api_key,
        "model": (cfg.get("model") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip(),
    }
    if cfg.get("base_url"):
        llm_kwargs["base_url"] = cfg["base_url"].strip()
    # 网关端点要求 x-opencode-session 稳定会话 ID（路由/缓存用，不承载凭证）
    from uuid import uuid4

    session_id = (os.environ.get("LLM_SESSION_ID") or "").strip()
    llm_kwargs["extra_headers"] = {"x-opencode-session": session_id or f"runtime-{uuid4().hex}"}
    llm = DeepSeekLLMProvider(**llm_kwargs)
    store = EvidenceStore()
    registry = SourceRegistry()
    executor = ToolExecutor(
        tools=[
            KBSearchTool(
                base_url=(os.environ.get("KB_INTERNAL_BASE_URL") or "http://127.0.0.1:8000").strip(),
                store=store,
            ),
            WebSearchTool(api_key=(os.environ.get("TAVILY_API_KEY") or "").strip(), store=store),
            ArxivSearchTool(store=store),
            SourceFetchTool(registry=registry, store=store),
            EvidenceReadTool(store=store),
        ]
    )
    return AgenticRuntime(llm=llm, executor=executor, store=store, budget=Budget())


class AgenticTaskService:
    """agentic 任务生命周期 + SSE v1 事件流。"""

    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory | None = None,
        event_log: Any = None,
        task_store: Any = None,
    ) -> None:
        self._runtime_factory = runtime_factory or build_cloud_runtime
        self._event_log = event_log if event_log is not None else InMemoryEventLog()
        self._task_store = task_store
        self._tasks: dict[str, dict] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._initialized = False

    # ---------- 生命周期 ----------

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._task_store is not None:
            running = await self._task_store.search_tasks(status=TaskStatus.RUNNING, limit=1000)
            for task_state in running:
                await self._task_store.update_task_status(
                    task_id=task_state.task_id,
                    status=TaskStatus.FAILED,
                    error={"message": "service restarted before task completion"},
                )
        self._initialized = True

    async def create_task(self, query: str, budget_overrides: dict[str, Any] | None = None) -> dict:
        task_id = generate_id("task")
        record = {
            "task_id": task_id,
            "status": "pending",
            "query": query,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "completed_at": None,
            "answer": None,
            "error": None,
        }
        self._tasks[task_id] = record
        await self._persist_created(task_id, query, budget_overrides or {})
        handle = asyncio.create_task(self._run(task_id, query, budget_overrides or {}))
        self._running[task_id] = handle
        return self._view(record)

    async def get_task(self, task_id: str) -> dict | None:
        record = self._tasks.get(task_id)
        if record:
            return self._view(record)
        return await self._load_persisted(task_id)

    async def list_tasks(self) -> list[dict]:
        views = [self._view(r) for r in self._tasks.values()]
        if self._task_store is not None:
            seen = set(self._tasks)
            for task_state in await self._task_store.search_tasks(limit=1000):
                if task_state.task_id not in seen:
                    loaded = await self._load_persisted(task_state.task_id)
                    if loaded:
                        views.append(loaded)
        return sorted(views, key=lambda v: v.get("created_at", ""), reverse=True)

    async def cancel_task(self, task_id: str) -> str:
        """返回 cancelled / not_running / not_found。幂等：重复取消不二次打断收尾。"""
        record = self._tasks.get(task_id)
        handle = self._running.get(task_id)
        if record is None:
            return "not_found"
        if record.get("cancel_requested"):
            return "cancelled"
        if handle is None or handle.done() or record["status"] in TERMINAL_STATUSES:
            return "not_running"
        record["cancel_requested"] = True
        handle.cancel()
        # 取消可能发生在 _run 首个 await 之前（协程从未启动、不会自补终态）；
        # 等它落下后若仍无终态事件，由这里补唯一终态，订阅方不会挂死
        try:
            await handle
        except asyncio.CancelledError:
            pass
        if not record.get("finalized"):
            await self._finish_cancelled(task_id)
        return "cancelled"

    async def delete_task(self, task_id: str) -> str:
        """返回 deleted / running / not_found。"""
        record = self._tasks.get(task_id)
        handle = self._running.get(task_id)
        if handle is not None and not handle.done():
            return "running"
        persisted = await self._load_persisted(task_id) if self._task_store else None
        if record is None and persisted is None:
            return "not_found"
        self._tasks.pop(task_id, None)
        if self._task_store is not None:
            await self._task_store.delete_task(task_id)
        await self._event_log.drop(task_id)
        return "deleted"

    def subscribe(self, task_id: str, after_sequence: int = 0):
        return self._event_log.subscribe(task_id, after_sequence)

    async def resolve_after_sequence(self, task_id: str, last_event_id: str) -> int:
        return await self._event_log.resolve_after_sequence(task_id, last_event_id)

    # ---------- 任务执行 ----------

    async def _run(self, task_id: str, query: str, overrides: dict[str, Any]) -> None:
        log = self._event_log
        record = self._tasks[task_id]
        budget = Budget(**{k: overrides[k] for k in BUDGET_KEYS if k in overrides})
        started = time.perf_counter()
        try:
            record["status"] = RUNNING_STATUS
            record["updated_at"] = now_iso()
            await self._persist_progress(task_id, "planning")
            await log.append(
                task_id,
                "meta",
                {
                    "question": query,
                    "budget": {
                        "max_rounds": budget.max_rounds,
                        "max_tool_calls": budget.max_tool_calls,
                        "max_tokens": budget.max_tokens,
                        "deadline_seconds": budget.deadline_seconds,
                    },
                },
            )

            async def sink(entry: dict) -> None:
                await self._forward(task_id, entry)

            try:
                runtime = self._runtime_factory()
            except AgenticConfigError as exc:
                await self._finish_failed(task_id, exc.code, exc.message)
                return
            runtime.budget = budget  # 请求级预算覆盖运行时默认预算

            checker = runtime.semantic_checker
            if checker is None:
                checker = SemanticVerifier(runtime.llm, budget=budget, on_event=sink)
            gate = CitationGate(semantic_checker=checker)
            loop = AgentLoop(
                planner=runtime.llm,
                writer=runtime.llm,
                executor=runtime.executor,
                store=runtime.store,
                gate=gate,
                budget=budget,
                on_event=sink,
            )

            answer = await loop.run(query)
            outcome = self._answer_outcome(answer)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            outcome["latency_ms"] = latency_ms

            await self._persist_terminal(task_id, "completed", result=outcome)
            await log.append(task_id, "done", {"task_status": "completed", "answer": outcome})
            from app.core.metrics import metrics as _metrics

            _metrics.inc_task_terminal("completed")
            # 内存记录最后落：观察者看到终态时，持久化与终态事件已就绪
            record.update(
                status="completed",
                answer=outcome,
                updated_at=now_iso(),
                completed_at=now_iso(),
                finalized=True,
            )

        except asyncio.CancelledError:
            await self._finish_cancelled(task_id)
        except Exception as exc:  # noqa: BLE001 —— 任务级失败隔离
            logger.exception("agentic task %s failed", task_id)
            await self._finish_failed(task_id, "internal_error", f"{type(exc).__name__}: {exc}"[:200])
        finally:
            self._running.pop(task_id, None)

    async def _finish_cancelled(self, task_id: str) -> None:
        record = self._tasks[task_id]
        await self._persist_terminal(task_id, "cancelled")
        await self._event_log.append(task_id, "done", {"task_status": "cancelled"})
        from app.core.metrics import metrics as _metrics

        _metrics.inc_task_terminal("cancelled")
        record.update(status="cancelled", updated_at=now_iso(), completed_at=now_iso(), finalized=True)

    async def _finish_failed(self, task_id: str, code: str, message: str) -> None:
        record = self._tasks[task_id]
        await self._persist_terminal(task_id, "failed", error=message)
        await self._event_log.append(
            task_id,
            "error",
            {"fatal": True, "task_status": "failed", "error": {"code": code, "message": message}},
        )
        from app.core.metrics import metrics as _metrics

        _metrics.inc_task_terminal("failed")
        record.update(
            status="failed",
            error={"code": code, "message": message},
            updated_at=now_iso(),
            completed_at=now_iso(),
            finalized=True,
        )

    async def _forward(self, task_id: str, entry: dict) -> None:
        """Agent trace → SSE v1 事件：终态由 _run 统一发，此处只发过程事件。"""
        event_type = entry.get("type", "")
        payload = {k: v for k, v in entry.items() if k != "type"}
        if event_type in ("done", "meta"):
            # done 由 _run 统一发终态；meta 由 _run 发带预算的权威版本（loop 的 meta 只有问题文本）
            return
        if event_type == "error":
            await self._event_log.append(task_id, "error", {"fatal": False, **payload})
            return
        if event_type not in ("meta", "plan", "tool_call", "tool_result", "evidence", "token_delta", "citation"):
            return
        await self._event_log.append(task_id, event_type, payload)
        if event_type == "tool_result":
            # source_status 由工具结果派生（provider/健康），紧随其后
            await self._event_log.append(
                task_id,
                "source_status",
                {
                    "source": payload.get("tool", ""),
                    "provider": payload.get("provider", ""),
                    "status": payload.get("status", ""),
                    "error_code": payload.get("error", ""),
                },
            )

    # ---------- 结果与视图 ----------

    def _answer_outcome(self, answer: Any) -> dict:
        base = {
            "stop_reason": getattr(answer.stop_reason, "value", str(answer.stop_reason)),
            "budget_report": dict(answer.budget_report),
            "evidence": [dataclasses.asdict(ev) for ev in answer.evidence],
        }
        if answer.status == "answered":
            return {
                "status": "answered",
                "text": answer.answer,
                "claims": [
                    {"claim": c.claim, "citations": list(c.citations), "scope": c.scope}
                    for c in answer.claims
                ],
                "citations": list(answer.citations),
                **base,
            }
        return {
            "status": "refused",
            "refusal_reason": answer.refusal_reason,
            **base,
        }

    def _view(self, record: dict) -> dict:
        return {
            "task_id": record["task_id"],
            "status": record["status"],
            "query": record["query"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "completed_at": record.get("completed_at"),
            "answer": record.get("answer"),
            "error": record.get("error"),
        }

    # ---------- 持久化（与 ResearchService 相同的任务状态存储） ----------

    async def _persist_created(self, task_id: str, query: str, overrides: dict[str, Any]) -> None:
        if self._task_store is None:
            return
        await self._task_store.create_task(
            task_id=task_id,
            input_data={"query": query, "budget": overrides},
            metadata={"query": query, "mode": "agentic", **overrides},
            topology_name="agentic",
        )

    async def _persist_progress(self, task_id: str, stage: str) -> None:
        if self._task_store is None:
            return
        await self._task_store.update_task_status(
            task_id=task_id,
            status=TaskStatus.RUNNING,
            current_stage=stage,
            current_agent="agent_loop",
        )

    async def _persist_terminal(self, task_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
        if self._task_store is None:
            return
        status_map = {
            "completed": TaskStatus.COMPLETED,
            "failed": TaskStatus.FAILED,
            "cancelled": TaskStatus.CANCELLED,
        }
        await self._task_store.update_task_status(
            task_id=task_id,
            status=status_map[status],
            progress=100 if status == "completed" else None,
            current_stage=status,
            result=result,
            error={"message": error} if error else None,
        )

    async def _load_persisted(self, task_id: str) -> dict | None:
        if self._task_store is None:
            return None
        task_state = await self._task_store.get_task_state(task_id)
        if task_state is None:
            return None
        metadata = task_state.metadata or {}
        error = task_state.error
        error_message = error.get("message") if isinstance(error, dict) else error
        return self._view(
            {
                "task_id": task_state.task_id,
                "status": task_state.status,
                "query": metadata.get("query") or task_state.input_data.get("query", ""),
                "created_at": task_state.created_at,
                "updated_at": task_state.updated_at,
                "completed_at": task_state.completed_at,
                "answer": task_state.result,
                "error": {"code": "internal_error", "message": error_message} if error_message else None,
            }
        )
