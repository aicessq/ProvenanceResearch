"""有界 Agent Loop（execution-plan Phase 3 / design.md §5）。

状态机：PLAN → TOOL_CALL → EVIDENCE_UPDATE → GAP_CHECK → GENERATE → VERIFY → DONE。

- Planner 每轮依据 Question、Observations、Evidence gaps 与剩余预算动态选择
  0..N 个工具或停止；工具顺序不写死，但循环有界（budget.py 硬边界）。
- Gap Detection 明确停止原因：sufficient_evidence / budget_exhausted /
  deadline_exceeded / no_progress / citation_gate_failed。
- 循环检测：规范化工具+参数形成检测键，没有新 Evidence 的重复调用不无限重试。
- 工具执行走 tools.ToolExecutor（白名单+参数校验+失败隔离）；
  产出登记 EvidenceStore；Reader RRF 融合 top8 → GENERATE → Citation Gate 验证。
- 拒答条件：无登记引用、引用不足、闸门一次重生成后仍失败、无证据。
- on_event 旁路与 trace 同构（事件名即 SSE v1 类型）；token_delta 记账
  plan/generate/verify 三阶段；done/error 终态语义由上层（SSE 层）裁决。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.budget import AgentState, Budget, StopReason
from agent.citation_gate import CitationGate, Claim, parse_claims
from agent.reader import fuse
from evidence.schema import Evidence
from evidence.store import EvidenceStore
from tools.base import ToolResult


class PlannerLLM(Protocol):
    """Planner/Writer/Verifier 共用的 LLM 能力（经 providers.LLMProvider）。"""

    async def generate(self, messages: list[Any], metadata: Any = None) -> Any: ...


class SemanticVerifier:
    """Citation Gate 第 4 步：LLM 语义复检（可注入 fake）。

    验证调用计入共享 Budget（design.md §8：验证/重生成使用剩余任务预算），
    并可选发 token_delta 事件（stage=verify）。
    """

    def __init__(self, llm: PlannerLLM, *, budget: Any = None, on_event: Any = None) -> None:
        self._llm = llm
        self._budget = budget
        self._on_event = on_event

    async def check(self, claim: Claim, evidence: list[Evidence]) -> bool:
        payload = {
            "claim": claim.claim,
            "citations": list(claim.citations),
            "evidence": [{"citation_id": ev.citation_id, "text": (ev.raw_text or "")[:2000]} for ev in evidence],
        }
        result = await self._llm.generate(
            [{"role": "user", "content": f"判断 claim 是否被证据支撑，只答 yes/no：{json.dumps(payload, ensure_ascii=False)}"}],
            {"stage": "verify"},
        )
        if self._budget is not None:
            self._budget.charge_tokens(result.prompt_tokens + result.completion_tokens)
        if self._on_event is not None:
            dispatched = self._on_event(
                {
                    "type": "token_delta",
                    "stage": "verify",
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }
            )
            if inspect.isawaitable(dispatched):
                await dispatched
        return "yes" in result.text.lower()


@dataclass
class AgentAnswer:
    """最终产出：answer 与 refusal 严格分开（SSE 终态唯一）。"""

    status: str                      # "answered" | "refused"
    stop_reason: StopReason
    answer: str = ""
    claims: tuple[Claim, ...] = field(default_factory=tuple)
    citations: tuple[str, ...] = field(default_factory=tuple)
    refusal_reason: str = ""
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    trace: tuple[dict, ...] = field(default_factory=tuple)
    budget_report: dict = field(default_factory=dict)


def _call_key(tool_name: str, args: dict) -> str:
    """规范化工具+参数 → 循环检测键。"""
    material = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode()).hexdigest()[:16]


class AgentLoop:
    def __init__(
        self,
        *,
        planner: PlannerLLM,
        writer: PlannerLLM,
        executor: Any,
        store: EvidenceStore,
        gate: CitationGate,
        budget: Budget | None = None,
        on_event: Any = None,
    ) -> None:
        self._planner = planner
        self._writer = writer
        self._executor = executor
        self._store = store
        self._gate = gate
        self._budget = budget or Budget()
        # 事件 sink（SSE/trace 旁路）：可为同步或异步 callable；事件与 trace 同构。
        self._on_event = on_event

    async def _dispatch(self, entry: dict) -> None:
        if self._on_event is None:
            return
        dispatched = self._on_event(dict(entry))
        if inspect.isawaitable(dispatched):
            await dispatched

    async def run(self, question: str) -> AgentAnswer:
        budget = self._budget
        trace: list[dict] = []
        seen_call_keys: set[str] = set()
        registered_before = {ev.citation_id for ev in self._store.all()}
        stop_reason: StopReason | None = None

        async def emit(entry: dict) -> None:
            trace.append(entry)
            await self._dispatch(entry)

        await emit({"type": "meta", "question": question})

        # ---- 有界检索循环 ----
        while budget.remaining_rounds() > 0 and stop_reason is None:
            budget.begin_round()
            await emit({"type": "plan", "round": budget.rounds})

            plan = await self._call_planner(question, emit)
            tool_calls = plan.get("tool_calls") or []
            if not tool_calls:
                stop_reason = StopReason.SUFFICIENT_EVIDENCE
                break

            made_progress = False
            for call in tool_calls:
                budget_exceeded = budget.exceeded()
                if budget_exceeded is not None:
                    stop_reason = budget_exceeded
                    break
                name = str(call.get("tool", ""))
                args = dict(call.get("args") or {})
                key = _call_key(name, args)
                await emit({"type": "tool_call", "tool": name, "args": args})

                budget.charge_tool_call()
                result: ToolResult = await self._executor.execute(name, **args)
                await emit(
                    {
                        "type": "tool_result",
                        "tool": name,
                        "status": result.status,
                        "call_id": result.call_id,
                        "error": result.error.code if result.error else "",
                        "provider": result.meta.provider,
                        "coverage": result.meta.coverage,
                        "latency_ms": result.meta.latency_ms,
                    }
                )

                new_evidence = [
                    ev for ev in result.evidence if ev.citation_id not in registered_before
                ]
                for ev in new_evidence:
                    registered_before.add(ev.citation_id)
                    await emit({"type": "evidence", "citation_id": ev.citation_id, "call_id": result.call_id})

                if new_evidence:
                    made_progress = True
                elif key in seen_call_keys:
                    # 重复调用且无新 Evidence → 不无限重试
                    await emit({"type": "error", "reason": "no_progress_repeat", "tool": name})
                    stop_reason = StopReason.NO_PROGRESS
                    break
                seen_call_keys.add(key)

            if stop_reason is not None:
                break
            await emit({"type": "plan", "round": budget.rounds, "progress": made_progress})

        if stop_reason is None:
            stop_reason = StopReason.SUFFICIENT_EVIDENCE

        evidence_all = self._store.all()
        budget_report = budget.report()

        # ---- 无证据 → 拒答 ----
        if not evidence_all:
            await emit({"type": "done", "status": "refused"})
            return AgentAnswer(
                status="refused",
                stop_reason=stop_reason,
                refusal_reason="no_evidence",
                trace=tuple(trace),
                budget_report=budget_report,
            )

        # ---- Reader 融合 + GENERATE + VERIFY（含一次重生成）----
        channels = self._collect_channels()
        top = fuse(channels)
        for attempt in range(2):  # 首次 + 一次重生成
            budget_check = budget.exceeded()
            if budget_check is not None:
                await emit({"type": "error", "reason": "budget_exhausted_before_generate"})
                return AgentAnswer(
                    status="refused",
                    stop_reason=budget_check,
                    refusal_reason="budget_exhausted",
                    evidence=tuple(top),
                    trace=tuple(trace),
                    budget_report=budget.report(),
                )
            try:
                answer_text, claims = await self._call_writer(question, top, attempt, emit)
            except (ValueError, KeyError) as exc:
                # writer 输出非法（坏 JSON/缺 claims）视为该轮验证失败，走重生成或拒答
                await emit({"type": "error", "reason": "invalid_writer_output", "attempt": attempt, "detail": str(exc)[:120]})
                continue
            await emit({"type": "citation", "claims": len(claims), "attempt": attempt})
            report = await self._gate.verify(claims, self._store)
            if report.passed:
                used = tuple(sorted({cid for c in claims for cid in c.citations}))
                await emit({"type": "done", "status": "answered"})
                return AgentAnswer(
                    status="answered",
                    stop_reason=StopReason.SUFFICIENT_EVIDENCE,
                    answer=answer_text,
                    claims=tuple(claims),
                    citations=used,
                    evidence=tuple(top),
                    trace=tuple(trace),
                    budget_report=budget.report(),
                )
            await emit(
                {
                    "type": "error",
                    "reason": "citation_gate_failed",
                    "attempt": attempt,
                    "failed": [c.reason for c in report.failed_claims],
                }
            )

        # 一次重生成后仍失败 → 拒答
        await emit({"type": "done", "status": "refused"})
        return AgentAnswer(
            status="refused",
            stop_reason=StopReason.CITATION_GATE_FAILED,
            refusal_reason="citation_gate_failed",
            evidence=tuple(top),
            trace=tuple(trace),
            budget_report=budget.report(),
        )

    def _collect_channels(self) -> dict[str, list[Evidence]]:
        """按 source_type 收集证据通道供 Reader 融合。"""
        channels: dict[str, list[Evidence]] = {"kb": [], "web": [], "arxiv": []}
        for ev in self._store.all():
            if ev.source_type == "kb_chunk":
                channels["kb"].append(ev)
            elif ev.source_type == "paper":
                channels["arxiv"].append(ev)
            else:
                channels["web"].append(ev)
        return channels

    async def _call_planner(self, question: str, emit: Any) -> dict:
        observations = [
            {"citation_id": ev.citation_id, "source_type": ev.source_type, "text": (ev.raw_text or "")[:200]}
            for ev in self._store.all()
        ]
        prompt = (
            "你是检索规划器。根据问题与已有证据决定下一步工具调用；"
            "证据充分时给出空 tool_calls 表示可以作答。\n"
            f"问题：{question}\n"
            f"已有证据：{json.dumps(observations, ensure_ascii=False)}\n"
            '输出 JSON：{"tool_calls": [{"tool": "kb_search", "args": {"query": "..."}}]}'
        )
        result = await self._planner.generate(
            [{"role": "user", "content": prompt}],
            {"stage": "plan", "remaining_tool_calls": self._budget.remaining_tool_calls()},
        )
        self._budget.charge_tokens(result.prompt_tokens + result.completion_tokens)
        await emit(
            {
                "type": "token_delta",
                "stage": "plan",
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
        )
        try:
            return json.loads(result.text)
        except json.JSONDecodeError:
            return {"tool_calls": []}

    async def _call_writer(self, question: str, top: list[Evidence], attempt: int, emit: Any) -> tuple[str, list[Claim]]:
        payload = {
            "question": question,
            "evidence": [
                {
                    "citation_id": ev.citation_id,
                    "scope": ev.content_scope,
                    "text": (ev.raw_text or "")[:1500],
                }
                for ev in top
            ],
        }
        instruction = (
            "基于证据回答问题，每个事实性结论必须引用证据。"
            "只能引用给出的 citation_id；证据不足的结论不要写。\n"
            '输出 JSON：{"answer": "...", "claims": [{"claim": "...", "citations": ["K..."], "scope": "fulltext"}]}'
        )
        if attempt > 0:
            instruction = "上一次引用验证未通过，请修正引用后重新输出。" + instruction
        result = await self._writer.generate(
            [{"role": "user", "content": f"{instruction}\n{json.dumps(payload, ensure_ascii=False)}"}],
            {"stage": "generate", "attempt": attempt},
        )
        self._budget.charge_tokens(result.prompt_tokens + result.completion_tokens)
        await emit(
            {
                "type": "token_delta",
                "stage": "generate",
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "attempt": attempt,
            }
        )
        data = json.loads(result.text)
        claims = parse_claims(data)
        return str(data.get("answer") or ""), claims
