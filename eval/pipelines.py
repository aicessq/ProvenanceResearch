"""P4 对照流水线（A KB-only / B fixed mixed / C agentic / D shared research graph）。

历史 A/B/C 共用同一 AgentLoop 的 GENERATE→VERIFY 段（同一 writer 提示词、
Reader RRF、Citation Gate、预算），只变"证据怎么来"：

- A：跑题前固定检索本地语料 top20 进 EvidenceStore，planner 恒停（无工具循环）。
- B：固定混合——本地 top10 + web_search/arxiv_search 各调一次，planner 恒停。
- C：旧 Agentic——planner 走 LLM 有界循环，按需调 kb_search/web_search/arxiv_search。
- D：三段式共享生产研究图，使用相同模型、工具来源、预算和引用闸门。

全部产出走 evidence.store 登记与引用闸门；检索排名（指标用）= 融合 top-8 截断前
的 RRF 全序（agent.reader.fuse 的池规则，不截断）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.budget import Budget  # noqa: E402
from agent.citation_gate import CitationGate, Claim  # noqa: E402
from agent.loop import AgentLoop  # noqa: E402
from agent.reader import fuse  # noqa: E402
from evidence.store import EvidenceStore  # noqa: E402
from tools.base import ToolMeta, ToolResult, validate_args  # noqa: E402

from eval.corpus_search import CorpusIndex  # noqa: E402

CONDITIONS = ("A", "B", "C", "D")


def writer_payload(messages) -> dict:
    # The legacy Writer appends the JSON to its prompt, the shared graph uses a JSON message.
    content = messages[-1].content
    _, marker, tail = content.partition('{"question"')
    return json.loads(marker + tail) if marker else {}


class UsageLLM:
    """LLM 用量记账包装（费用/成本未知标记依据）。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0
        self.reported_usage = True
        self.writer_evidence: list[list[dict]] = []

    async def generate(self, messages, metadata=None):
        if (metadata or {}).get("stage") == "generate":
            self.writer_evidence.append(writer_payload(messages).get("evidence", []))
        self.calls += 1
        try:
            result = await self._inner.generate(messages, metadata)
        except BaseException:
            # 已尝试的调用可能已计费；取消也不能报成零成本。异常原样向上传递。
            self.reported_usage = False
            raise
        pt = getattr(result, "prompt_tokens", None)
        ct = getattr(result, "completion_tokens", None)
        if pt is None or ct is None:
            self.reported_usage = False
        else:
            self.prompt_tokens += int(pt)
            self.completion_tokens += int(ct)
        return result


class StopPlanner:
    """A/B 的固定检索语义：绝不发起工具调用，首轮即作答。"""

    async def generate(self, messages, metadata=None):
        class R:
            pass

        r = R()
        r.text = '{"tool_calls": []}'
        r.prompt_tokens = 0
        r.completion_tokens = 0
        return r


class EvalKBSearchTool:
    """eval 语料 KB 工具：与 tools/kb_search 同契约（call_id/status/evidence/meta/error）。"""

    name = "kb_search"
    ALLOWED = {"query": str, "top_k": int}

    def __init__(self, corpus: CorpusIndex, store: EvidenceStore, index_identity: str) -> None:
        self._corpus = corpus
        self._store = store
        self._index_identity = index_identity

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, self.ALLOWED, ("query",))
        started = time.perf_counter()
        hits = self._corpus.search(str(args["query"]), top_k=int(args.get("top_k", 5)))
        evidence = [self._corpus.build_evidence(hit, self._store, self._index_identity) for hit in hits]
        return ToolResult(
            call_id=call_id,
            status="ok" if evidence else "empty",
            evidence=evidence,
            meta=ToolMeta(
                provider="eval_corpus",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                index_identity=self._index_identity,
                coverage=f"top_k={args.get('top_k', 5)}",
            ),
        )


@dataclass
class RunResult:
    question_id: str
    condition: str
    status: str  # answered / refused / error
    answer_text: str = ""
    claims: list[dict] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    refusal_reason: str = ""
    stop_reason: str = ""
    ranked_refs: list[dict] = field(default_factory=list)  # 融合 top-8 截断前的全序（指标用）
    evidence: list[dict] = field(default_factory=list)
    budget_report: dict = field(default_factory=dict)
    trace_types: list[str] = field(default_factory=list)
    candidate_evidence: list[dict] = field(default_factory=list)
    writer_evidence: list[list[dict]] = field(default_factory=list)
    citation_checks: list[dict] = field(default_factory=list)
    writer_diagnostics: list[dict] = field(default_factory=list)
    scope_fallback: str = ""
    model_stages: list[dict] = field(default_factory=list)
    budget_rejections: list[dict] = field(default_factory=list)
    search_summary: list[dict] = field(default_factory=list)
    missing_questions: list[str] = field(default_factory=list)
    partial: bool = False
    latency_ms: float = 0.0
    usage: dict = field(default_factory=dict)
    cost_unknown: bool = False
    error: str = ""
    gaps: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    tool_trace: list[dict] = field(default_factory=list)


def _evidence_ref(ev: Any) -> dict:
    """gold 匹配用的来源引用：语料 (doc_id,page) / 论文 (arxiv_id,version) / 网页 URL。"""
    return {
        "citation_id": ev.citation_id,
        "doc_id": ev.provenance.doc_id,
        "page": ev.locator.page,
        "arxiv_id": ev.provenance.arxiv_id,
        "arxiv_version": ev.provenance.arxiv_version,
        "url": ev.provenance.canonical_url or ev.provenance.fulltext_url,
        "source_type": ev.source_type,
    }


def _channels_of(store: EvidenceStore) -> dict[str, list]:
    channels: dict[str, list] = {"kb": [], "web": [], "arxiv": []}
    for ev in store.all():
        if ev.source_type == "kb_chunk":
            channels["kb"].append(ev)
        elif ev.source_type == "paper":
            channels["arxiv"].append(ev)
        else:
            channels["web"].append(ev)
    return channels


async def run_condition(
    condition: str,
    question: dict,
    *,
    llm: Any,
    checker: Any,
    corpus: CorpusIndex,
    store: EvidenceStore,
    executor: Any = None,
    budget: Budget | None = None,
    index_identity: str = "",
    loop_factory: Any = AgentLoop,
) -> RunResult:
    """跑一个条件的一道题。llm 需已包 UsageLLM；checker 为引用闸门语义复检。

    store 由调用方持有：工具产出登记进同一 store 供循环/Reader/闸门消费
    （与生产同构——AgentLoop 不自行登记工具证据）。
    """
    if condition not in CONDITIONS:
        raise ValueError(f"未知条件: {condition}")
    budget = budget or Budget()
    question_text = str(question["question"])
    question_id = str(question.get("id", ""))
    started = time.perf_counter()

    try:
        if condition == "D":
            from researcher.deep_research_system.app.graphs.research_graph import run_research

            runtime = SimpleNamespace(llm=llm, executor=executor, store=store, semantic_checker=checker)
            answer = await run_research(question_text, runtime, budget)
        else:
            async with asyncio.timeout(max(0, budget.deadline_seconds - budget.elapsed())):
                answer = await _run_legacy(condition, question_text, llm, checker, corpus, store, executor,
                                           budget, index_identity, loop_factory)

        ranked = fuse(_channels_of(store), output_top=10_000)

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = {}
        cost_unknown = False
        if isinstance(llm, UsageLLM):
            usage = {
                "prompt_tokens": llm.prompt_tokens,
                "completion_tokens": llm.completion_tokens,
                "llm_calls": llm.calls,
            }
            cost_unknown = not llm.reported_usage
        else:
            cost_unknown = True
        return RunResult(
            question_id=question_id,
            condition=condition,
            status=answer.status,
            answer_text=answer.answer,
            claims=[{"claim": c.display_text, "citations": list(c.citations), "scope": c.scope} for c in answer.claims],
            citations=list(answer.citations),
            refusal_reason=answer.refusal_reason,
            stop_reason=getattr(answer.stop_reason, "value", str(answer.stop_reason)),
            ranked_refs=[_evidence_ref(ev) for ev in ranked],
            evidence=[
                {
                    "citation_id": ev.citation_id,
                    "source_type": ev.source_type,
                    "content_scope": ev.content_scope,
                    "doc_id": ev.provenance.doc_id,
                    "page": ev.locator.page,
                    "arxiv_id": ev.provenance.arxiv_id,
                    "url": ev.provenance.canonical_url,
                }
                for ev in answer.evidence
            ],
            budget_report=dict(answer.budget_report),
            trace_types=[t.get("type", "") for t in answer.trace],
            candidate_evidence=[_evidence_ref(ev) for ev in store.all()],
            writer_evidence=llm.writer_evidence if isinstance(llm, UsageLLM) else [],
            citation_checks=[check for event in answer.trace if event["type"] == "citation"
                             for check in event.get("checks", [])],
            writer_diagnostics=[{"reason": event["reason"], "attempt": event["attempt"]}
                                for event in answer.trace if event["type"] == "error"
                                and event.get("stage") == "generate"],
            scope_fallback=next((event["reason"] for event in answer.trace
                                 if event["type"] == "plan" and event.get("action") == "scope_fallback"), ""),
            model_stages=[{key: value for key, value in event.items() if key != "type"}
                          for event in answer.trace if event["type"] == "token_delta"],
            budget_rejections=[{key: value for key, value in event.items() if key != "type"}
                               for event in answer.trace if event["type"] == "budget_check"],
            search_summary=list(getattr(answer, "search_summary", ())),
            missing_questions=list(getattr(answer, "missing_questions", ())),
            partial=getattr(answer, "partial", False),
            latency_ms=latency_ms,
            usage=usage,
            cost_unknown=cost_unknown,
            gaps=list(getattr(answer, "gaps", ())),
            limitations=list(getattr(answer, "limitations", ())),
            tool_trace=[t for t in answer.trace if t.get("type") in ("tool_call", "tool_result")],
        )
    except Exception as exc:  # noqa: BLE001 —— provider 失败如实记录为 error 运行
        return RunResult(
            question_id=question_id,
            condition=condition,
            status="error",
            candidate_evidence=[_evidence_ref(ev) for ev in store.all()],
            writer_evidence=llm.writer_evidence if isinstance(llm, UsageLLM) else [],
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error=f"{type(exc).__name__}: {exc}"[:200],
            usage=({"prompt_tokens": llm.prompt_tokens, "completion_tokens": llm.completion_tokens,
                    "llm_calls": llm.calls} if isinstance(llm, UsageLLM) else {}),
            cost_unknown=True,
        )


async def _run_legacy(condition, question_text, llm, checker, corpus, store, executor, budget,
                      index_identity, loop_factory):
    if condition == "A":
        for hit in corpus.search(question_text, top_k=20):
            corpus.build_evidence(hit, store, index_identity)
        planner = StopPlanner()
    elif condition == "B":
        if budget.remaining_tool_calls():
            budget.charge_tool_call()
            for hit in corpus.search(question_text, top_k=10):
                corpus.build_evidence(hit, store, index_identity)
        if executor is not None:
            for name in ("web_search", "arxiv_search"):
                remaining = budget.deadline_seconds - budget.elapsed()
                if not budget.remaining_tool_calls() or remaining <= 0:
                    break
                budget.charge_tool_call()
                async with asyncio.timeout(remaining):
                    await executor.execute(name, query=question_text, top_k=5)
        planner = StopPlanner()
    else:  # C：证据全靠 Agent 有界循环
        planner = llm

    gate = CitationGate(semantic_checker=checker)
    loop = loop_factory(
        planner=planner,
        writer=llm,
        executor=executor,
        store=store,
        gate=gate,
        budget=budget,
    )
    return await loop.run(question_text)
